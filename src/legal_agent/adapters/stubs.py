"""Implementações em memória dos ports — usadas pelo smoke e pelos testes.

Nenhum dado real: o acervo e o cadastro em `data/` são fictícios.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Optional

from ..ports import Chunk, CoverageRow, LLMMessage

DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def _tokens(text: str) -> set[str]:
    text = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return {t for t in re.findall(r"[a-z0-9\-]{3,}", text)}


class InMemoryRetriever:
    """Busca "híbrida" de brinquedo: sobreposição de termos + bônus por termo exato (ex.: NE-01)."""

    def __init__(self, path: Path = DATA_DIR / "sample_corpus.jsonl"):
        self.chunks = [Chunk(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.calls: list[dict] = []

    def search(self, query: str, k: int, file_name: Optional[str] = None) -> list[Chunk]:
        self.calls.append({"query": query, "k": k, "file_name": file_name})
        q = _tokens(query)
        pool = [c for c in self.chunks if not file_name or c.file_name.lower() == file_name.lower()]
        scored = []
        for c in pool:
            body = _tokens(c.text + " " + c.section + " " + c.file_name)
            overlap = len(q & body)
            exact = sum(2 for t in q if "-" in t and t in body)
            if overlap + exact >= 2:
                scored.append((overlap + exact, c))
        scored.sort(key=lambda x: -x[0])
        top = max((s for s, _ in scored), default=1)
        return [Chunk(**{**c.__dict__, "score": round(s / top, 3)}) for s, c in scored[:k]]


class InMemoryCoverage:
    """Cadastro de conformidade + lista de acesso (UPN -> unidade). Fechada por padrão."""

    def __init__(self, path: Path = DATA_DIR / "sample_scope.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        self.acl: dict[str, str] = data["acl"]
        self.units: dict[str, dict] = data["units"]
        self.calls: list[dict] = []

    def compare(self, law_ids: list[str], upn: str) -> list[CoverageRow]:
        self.calls.append({"law_ids": list(law_ids), "upn": upn})
        unit = self.acl.get((upn or "").lower())
        if not unit:
            return []  # UPN fora da lista de acesso não vê escopo nenhum
        registry = self.units.get(unit, {})
        rows = []
        for law_id in law_ids:
            entry = registry.get(law_id)
            if entry is None:
                rows.append(CoverageRow(law_id=law_id, in_scope=False))
            else:
                rows.append(CoverageRow(law_id=law_id, in_scope=True, **entry))
        return rows


class ScriptedLLM:
    """LLM determinístico: redige a partir do que recebeu, sem memória paramétrica.

    Registra todas as mensagens recebidas — é assim que o teste de no-spoof prova
    que a identidade nunca chega ao modelo.
    """

    def __init__(self, router_label: str = "legal"):
        self.router_label = router_label
        self.seen: list[list[LLMMessage]] = []

    def complete(self, messages: list[LLMMessage], max_tokens: int) -> str:
        self.seen.append(messages)
        system = " ".join(m.content for m in messages if m.role == "system")
        user = messages[-1].content
        if "Classifique a intenção" in system:
            return json.dumps({"intent": self.router_label})
        if "Responda de forma breve e cordial" in system:
            return "Olá! Posso ajudar com dúvidas sobre normas e sobre a situação da sua unidade."
        if "Reescreva a resposta anterior" in system:
            previous = user.split("Resposta anterior:\n", 1)[-1].split("\n\nPedido:", 1)[0]
            return "Em termos simples: " + previous.split("\n")[0]
        return self._synthesize(user, detail="Resposta detalhada" in system)

    @staticmethod
    def _synthesize(user: str, detail: bool) -> str:
        passages = re.findall(r"^\[(.+?) \| (.+?)\] (.+)$", user, flags=re.MULTILINE)
        if not passages:
            return "Não encontrei base nos trechos."
        take = passages if detail else passages[:1]
        parts = [f"Segundo {f} ({sec}): \"{txt.strip()}\"" for f, sec, txt in take]
        scope = re.findall(r"^- (\S+): no escopo; (\d+) de (\d+) artigos atendem", user, flags=re.MULTILINE)
        if scope:
            law, ok, total = scope[0]
            parts.append(f"A norma {law} está no escopo da sua unidade: {ok} de {total} artigos atendem.")
        return " ".join(parts)
