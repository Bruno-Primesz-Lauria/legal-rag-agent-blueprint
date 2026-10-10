"""Guardrails aplicados por CÓDIGO depois que o modelo escreveu.

Nenhum destes limites depende de o modelo obedecer ao prompt: cada função
recebe o texto do LLM e prevalece sobre ele.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable

REFUSAL_NO_RETRIEVAL = (
    "Não encontrei base legal no acervo para responder a essa pergunta. "
    "Não é possível fundamentar uma resposta sem passagem recuperada."
)
REFUSAL_ADVERSARIAL = "Não posso atender a esse pedido. Posso ajudar com perguntas sobre legislação e conformidade."
REFUSAL_OUT_OF_DOMAIN = "Esse assunto está fora do meu escopo. Sou especializado em legislação e conformidade."
SCOPE_WITHOUT_IDENTITY_NOTICE = (
    "Não é possível afirmar a situação da sua unidade sem identidade válida "
    "e normas vinculadas ao cadastro."
)

_PDF_RE = re.compile(r"[\w\-./]+\.pdf", re.IGNORECASE)
_LEGAL_REF_RE = re.compile(
    r"\b(?:Lei|Decreto|Portaria|Resolu[cç][aã]o)\s+(?:n[º°o.]\s*)?\d[\d.]*(?:/\d{2,4})?|\bNE-\d+\b",
    re.IGNORECASE,
)
_SCOPE_CLAIM_RE = re.compile(
    r"\b(?:sua\s+unidade|no\s+escopo|fora\s+do\s+escopo|atende[mu]?|"
    r"n[aã]o\s+conforme|em\s+conformidade)\b",
    re.IGNORECASE,
)


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    return re.sub(r"[\s_\-.º°]+", "", value.lower())


def finalize_answer(text: str, retrieved_files: set[str]) -> str:
    """Sem trecho recuperado, o texto do modelo é descartado (nada de memória paramétrica)."""
    if not retrieved_files:
        return REFUSAL_NO_RETRIEVAL
    return (text or "").strip() or REFUSAL_NO_RETRIEVAL


def citation_post_filter(answer: str, retrieved_files: set[str], evidence: Iterable[str]) -> str:
    """Remove arquivo ou referência legal sem lastro nos trechos recuperados."""
    allowed_files = {_norm(f) for f in retrieved_files}
    corpus = _norm(" ".join(evidence) + " " + " ".join(retrieved_files))

    def _file(m: re.Match) -> str:
        return m.group(0) if _norm(m.group(0)) in allowed_files else "[citação removida]"

    def _ref(m: re.Match) -> str:
        return m.group(0) if _norm(m.group(0)) in corpus else "[referência legal removida]"

    return _LEGAL_REF_RE.sub(_ref, _PDF_RE.sub(_file, answer))


def scope_claim_post_filter(answer: str, upn_present: bool) -> str:
    """Sem identidade, frases que afirmam escopo/conformidade saem do texto."""
    if upn_present:
        return answer
    sentences = re.split(r"(?<=[.!?])\s+|(?<=[.!?][\"”])\s+|\n+", answer)
    kept = [s.strip() for s in sentences if s.strip() and not _SCOPE_CLAIM_RE.search(s)]
    body = " ".join(kept)
    return f"{body}\n{SCOPE_WITHOUT_IDENTITY_NOTICE}" if body else SCOPE_WITHOUT_IDENTITY_NOTICE
