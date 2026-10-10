"""Adapters de produção sobre serviços Databricks (import preguiçoso).

Não é exercitado no CI: exige workspace, endpoint de Vector Search e as funções
de `sql/uc_functions.sql`. O agente é LIVE-only — recurso ausente levanta erro
acionável (fail-fast); ele nunca responde a partir de fixture.
"""
from __future__ import annotations

import csv
import io
from typing import Optional

from ..config import AgentConfig
from ..ports import Chunk, CoverageRow, LLMMessage

_COLUMNS = ["chunk_id", "file_name", "section", "chunk_text", "law_id"]


class DatabricksLLM:
    """Foundation Model API. `llm_endpoint` no YAML é o único ponto de troca do modelo."""

    def __init__(self, cfg: AgentConfig):
        from databricks_langchain import ChatDatabricks

        self.endpoint = cfg.llm_endpoint
        self._chat = ChatDatabricks
        self._clients: dict[int, object] = {}

    def complete(self, messages: list[LLMMessage], max_tokens: int) -> str:
        client = self._clients.setdefault(max_tokens, self._chat(endpoint=self.endpoint, max_tokens=max_tokens))
        reply = client.invoke([(m.role, m.content) for m in messages])
        return reply.content if isinstance(reply.content, str) else str(reply.content)


class VectorSearchRetriever:
    """Ferramenta A — índice Delta-Sync sobre `silver.legal_chunks`. Sem filtro por usuário."""

    def __init__(self, cfg: AgentConfig):
        from databricks.vector_search.client import VectorSearchClient

        try:
            self.index = VectorSearchClient(disable_notice=True).get_index(index_name=cfg.vs_index)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Índice {cfg.vs_index} indisponível. Rode lakehouse/ até o sync do índice "
                "antes de servir o agente."
            ) from exc
        self.query_type = cfg.query_type

    def search(self, query: str, k: int, file_name: Optional[str] = None) -> list[Chunk]:
        res = self.index.similarity_search(
            query_text=query,
            columns=_COLUMNS,
            num_results=k,
            query_type=self.query_type,
            filters={"file_name": file_name} if file_name else None,  # foco por documento, nunca por usuário
        )
        rows = (res.get("result") or {}).get("data_array") or []
        return [
            Chunk(chunk_id=r[0], file_name=r[1], section=r[2], text=r[3], law_id=r[4], score=float(r[-1]))
            for r in rows
        ]


class UCCoverageTool:
    """Ferramenta C — função SQL governada do Unity Catalog (RLS via lista de acesso)."""

    def __init__(self, cfg: AgentConfig):
        from unitycatalog.ai.core.databricks import DatabricksFunctionClient

        self.client = DatabricksFunctionClient()
        self.function = cfg.fn_compare_coverage

    def compare(self, law_ids: list[str], upn: str) -> list[CoverageRow]:
        result = self.client.execute_function(
            self.function, parameters={"ids": ",".join(law_ids), "p_upn": upn}
        )
        if getattr(result, "error", None):
            raise RuntimeError(f"{self.function} falhou: {result.error}")
        rows = csv.DictReader(io.StringIO(result.value or ""))
        return [
            CoverageRow(
                law_id=r["law_id"],
                in_scope=str(r["in_scope"]).lower() == "true",
                articles_total=int(r["articles_total"] or 0),
                compliant=int(r["compliant"] or 0),
                non_compliant=int(r["non_compliant"] or 0),
                partial=int(r["partial"] or 0),
                not_applicable=int(r["not_applicable"] or 0),
            )
            for r in rows
        ]
