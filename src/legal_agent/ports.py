"""Contratos (ports) entre o agente e o mundo externo.

O núcleo do agente só conhece estes três protocolos. Em produção eles são
implementados por serviços Databricks (Foundation Model API, Vector Search,
funções SQL do Unity Catalog); nos testes e no smoke, por stubs em memória.
Trocar a implementação não toca em uma linha do agente.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol


@dataclass(frozen=True)
class Chunk:
    """Um trecho de norma recuperado do acervo público."""

    chunk_id: str
    file_name: str
    section: str
    text: str
    law_id: Optional[str] = None  # vínculo com o cadastro de conformidade
    score: float = 0.0


@dataclass(frozen=True)
class CoverageRow:
    """Situação de uma norma para a unidade do usuário identificado.

    `in_scope` (a unidade tem essa norma no cadastro) e a contagem de artigos
    (como ela atende) são eixos SEPARADOS: "no escopo" não quer dizer "conforme".
    """

    law_id: str
    in_scope: bool
    articles_total: int = 0
    compliant: int = 0
    non_compliant: int = 0
    partial: int = 0
    not_applicable: int = 0


@dataclass
class LLMMessage:
    role: str  # system | user | assistant
    content: str


class LLM(Protocol):
    def complete(self, messages: list[LLMMessage], max_tokens: int) -> str: ...


class Retriever(Protocol):
    """Busca no acervo público. NUNCA recebe identidade (ADR-0002)."""

    def search(self, query: str, k: int, file_name: Optional[str] = None) -> list[Chunk]: ...


class CoverageTool(Protocol):
    """Cruza normas com o cadastro da unidade. Fechada por padrão: sem identidade, sem escopo."""

    def compare(self, law_ids: list[str], upn: str) -> list[CoverageRow]: ...


@dataclass
class Trace:
    """Rastro mínimo de uma resposta, para auditoria (espelha o MLflow Tracing)."""

    intent: str = ""
    steps: list[str] = field(default_factory=list)
    llm_calls: int = 0
