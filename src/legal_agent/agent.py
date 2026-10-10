"""Agente de legislação: roteador + pipeline fixo + guardrails em código.

Fluxo por mensagem:
    identidade (envelope) -> roteia -> [busca -> escopo -> redige 1x] -> confere -> responde

Invariantes garantidas por código (e por teste), não pelo prompt:
  * ADR-0001 — a identidade (UPN) é lida UMA vez do envelope da requisição e só
    chega à ferramenta de escopo. Nunca entra em mensagem para o LLM, nunca vem
    do texto da conversa.
  * ADR-0002 — a busca no acervo nunca é filtrada por usuário: a norma é pública.
  * ADR-0003 — pipeline fixo: 1 busca, 1 consulta de
    escopo, 1 redação por pergunta.

A entrada e a saída seguem o formato Responses (`input`, `output[]`,
`custom_inputs`, `custom_outputs`), o mesmo do MLflow `ResponsesAgent`.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from . import guardrails as g
from .config import PROJECT_ROOT, AgentConfig, load_config
from .ports import LLM, Chunk, CoverageRow, CoverageTool, LLMMessage, Retriever, Trace
from .router import NO_RETRIEVAL_INTENTS, apply_sliced_fail_safe, classify_intent_rules, parse_intent_label

PROMPTS_DIR = PROJECT_ROOT / "prompts"
_PDF_RE = re.compile(r"[\w\-./]+\.pdf", re.IGNORECASE)


def _prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


# ---------------------------------------------------------------------------
# Leitura do envelope (formato Responses)
# ---------------------------------------------------------------------------
def read_identity(request: dict) -> Optional[str]:
    """Fronteira de confiança: UPN só de `custom_inputs.upn` (ou `context.user_id`)."""
    upn = (request.get("custom_inputs") or {}).get("upn") or (request.get("context") or {}).get("user_id")
    return str(upn).strip() if upn and str(upn).strip() else None


def message_items(request: dict) -> list[dict]:
    """Só itens `type: message` são conversa; `function_call*` são rastro de auditoria."""
    items = request.get("input") or []
    if isinstance(items, str):
        items = [{"role": "user", "content": items}]
    turns = []
    for item in items:
        if (item.get("type") or "message") != "message":
            continue
        content = item.get("content") or ""
        if isinstance(content, list):
            content = " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
        turns.append({"role": (item.get("role") or "user").lower(), "content": content})
    return turns


def _last(turns: list[dict], role: str) -> str:
    return next((t["content"] for t in reversed(turns) if t["role"] == role), "")


def excerpt(text: str, query: str, budget: int) -> str:
    """Recorte centrado nos termos da pergunta, não os primeiros N caracteres."""
    if len(text) <= budget:
        return text
    terms = [t for t in re.findall(r"\w{4,}", query.lower())]
    pos = min((text.lower().find(t) for t in terms if t in text.lower()), default=0)
    start = max(0, pos - budget // 4)
    return text[start : start + budget]


# ---------------------------------------------------------------------------
# Agente
# ---------------------------------------------------------------------------
class ComplianceAgent:
    def __init__(
        self,
        llm: LLM,
        retriever: Retriever,
        coverage: CoverageTool,
        cfg: Optional[AgentConfig] = None,
    ):
        self.llm = llm
        self.retriever = retriever
        self.coverage = coverage
        self.cfg = cfg or load_config()
        self.system_prompt = _prompt("system_pt_br.txt")

    # -- ponto de entrada --------------------------------------------------
    def predict(self, request: dict) -> dict:
        upn = read_identity(request)  # lido UMA vez; daqui só segue para a ferramenta de escopo
        request_id = (request.get("custom_inputs") or {}).get("request_id")
        turns = message_items(request)
        user_text = _last(turns, "user")
        trace = Trace()

        intent = self._route(user_text, turns, trace) if self.cfg.router_enabled else "legal"
        trace.intent = intent

        if intent in NO_RETRIEVAL_INTENTS:
            text, chunks, coverage = self._fast_path(intent, turns, trace), [], []
            mode = "direct"
        else:
            text, chunks, coverage, mode = self._pipeline(intent, user_text, turns, upn, trace)

        return self._respond(text, intent, mode, chunks, coverage, upn, request_id, trace)

    # -- 1. roteamento -----------------------------------------------------
    def _route(self, user_text: str, turns: list[dict], trace: Trace) -> str:
        ruled = classify_intent_rules(user_text, has_history=bool(_last(turns, "assistant")))
        if ruled:
            trace.steps.append(f"route:rules:{ruled}")
            return ruled
        raw = self._call_llm(
            [LLMMessage("system", _prompt("router_pt_br.txt")), LLMMessage("user", user_text)],
            self.cfg.max_tokens_router,
            trace,
        )
        intent = apply_sliced_fail_safe(parse_intent_label(raw), user_text)
        trace.steps.append(f"route:llm:{intent}")
        return intent

    # -- 2a. rotas sem busca -----------------------------------------------
    def _fast_path(self, intent: str, turns: list[dict], trace: Trace) -> str:
        if intent == "adversarial":
            return g.REFUSAL_ADVERSARIAL
        if intent == "out_of_domain":
            return g.REFUSAL_OUT_OF_DOMAIN
        if intent == "smalltalk":
            msgs = [LLMMessage("system", _prompt("smalltalk_pt_br.txt")), LLMMessage("user", _last(turns, "user"))]
            return self._call_llm(msgs, self.cfg.max_tokens_smalltalk, trace)
        # reformulate: reescreve a última resposta, sem nova busca
        previous = _last(turns, "assistant")
        if not previous:
            return "Ainda não há uma resposta anterior para reformular. Qual é a sua pergunta?"
        msgs = [
            LLMMessage("system", _prompt("reformulate_pt_br.txt")),
            LLMMessage("user", f"Resposta anterior:\n{previous}\n\nPedido: {_last(turns, 'user')}"),
        ]
        rewritten = self._call_llm(msgs, self.cfg.max_tokens_summary, trace)
        # a reescrita também não pode citar o que a resposta original não citava
        return g.citation_post_filter(rewritten, set(_PDF_RE.findall(previous)), [previous])

    # -- 2b. pipeline fixo: busca -> escopo -> redação ---------------------
    def _pipeline(self, intent, user_text, turns, upn, trace):
        focus_file = None
        if intent == "expand":
            cited = _PDF_RE.findall(_last(turns, "assistant"))
            if not cited:
                return ("Para detalhar, preciso saber qual norma aprofundar. "
                        "Pode repetir a pergunta original ou citar o documento?"), [], [], "detail"
            focus_file = cited[0]

        # Ferramenta A — acervo público, sem filtro por usuário (ADR-0002)
        chunks = self.retriever.search(user_text, k=self.cfg.k, file_name=focus_file)
        if focus_file and not chunks:  # nome não casou: volta à busca aberta
            chunks = self.retriever.search(user_text, k=self.cfg.k)
        if self.cfg.retrieval_min_score is not None:
            chunks = [c for c in chunks if c.score >= self.cfg.retrieval_min_score]
        trace.steps.append(f"retrieve:{len(chunks)}")
        mode = "detail" if intent == "expand" else self.cfg.answer_mode_default
        if not chunks:
            return g.REFUSAL_NO_RETRIEVAL, [], [], mode

        # Ferramenta C — escopo, só com identidade e com normas vinculadas.
        # O UPN é argumento de CÓDIGO; o LLM não o vê nem o preenche (ADR-0001).
        coverage: list[CoverageRow] = []
        law_ids = sorted({c.law_id for c in chunks if c.law_id})
        if upn and law_ids:
            coverage = self.coverage.compare(law_ids, upn)
            trace.steps.append(f"coverage:{len(coverage)}")

        # Redação única
        budget = self.cfg.max_tokens_detail if mode == "detail" else self.cfg.max_tokens_summary
        context = "\n".join(
            f"[{c.file_name} | {c.section}] {excerpt(c.text, user_text, self.cfg.chunk_excerpt_chars)}"
            for c in chunks
        )
        board = self._coverage_board(coverage) if coverage else "Quadro de escopo: indisponível."
        msgs = [
            LLMMessage("system", self.system_prompt),
            LLMMessage("system", _prompt("summary_pt_br.txt" if mode == "summary" else "detail_pt_br.txt")),
            LLMMessage("user", f"Pergunta: {user_text}\n\nTrechos recuperados:\n{context}\n\n{board}"),
        ]
        return self._call_llm(msgs, budget, trace), chunks, coverage, mode

    @staticmethod
    def _coverage_board(rows: list[CoverageRow]) -> str:
        lines = ["Quadro de escopo da unidade (escopo e atendimento são eixos separados):"]
        for r in rows:
            if r.in_scope:
                lines.append(f"- {r.law_id}: no escopo; {r.compliant} de {r.articles_total} artigos atendem, "
                             f"{r.partial} parcial, {r.non_compliant} não atendem")
            else:
                lines.append(f"- {r.law_id}: fora do escopo da unidade")
        return "\n".join(lines)

    # -- 3. conferência + resposta -----------------------------------------
    def _respond(self, text, intent, mode, chunks, coverage, upn, request_id, trace) -> dict:
        if intent not in NO_RETRIEVAL_INTENTS and text not in (g.REFUSAL_NO_RETRIEVAL,) and chunks:
            files = {c.file_name for c in chunks}
            text = g.finalize_answer(text, files)
            text = g.citation_post_filter(text, files, [c.text for c in chunks])
        if intent in ("legal", "expand", "reformulate") and text != g.REFUSAL_NO_RETRIEVAL:
            # reformulate reescreve uma resposta que já passou pelos guardrails com identidade
            has_scope = bool(upn) and (bool(coverage) or intent == "reformulate")
            text = g.scope_claim_post_filter(text, upn_present=has_scope)
        trace.steps.append("guardrails")

        custom_outputs: dict[str, Any] = {
            "intent": intent,
            "answer_mode": mode,
            "citations": sorted({c.file_name for c in chunks if c.file_name in text}),
            "scope": [
                {"law_id": r.law_id, "in_scope": r.in_scope,
                 "articles": {"total": r.articles_total, "compliant": r.compliant, "partial": r.partial,
                              "non_compliant": r.non_compliant, "not_applicable": r.not_applicable}}
                for r in (coverage if upn else [])
            ],
            "trace": trace.steps,
        }
        if request_id:
            custom_outputs["request_id"] = request_id  # eco puro, para correlação no app
        return {
            "output": [{"type": "message", "role": "assistant",
                        "content": [{"type": "output_text", "text": text}]}],
            "custom_outputs": custom_outputs,
        }

    def _call_llm(self, messages: list[LLMMessage], max_tokens: int, trace: Trace) -> str:
        trace.llm_calls += 1
        return self.llm.complete(messages, max_tokens=max_tokens)


def answer_text(response: dict) -> str:
    return response["output"][0]["content"][0]["text"]
