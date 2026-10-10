"""Config-as-code: todos os botões do agente em um único YAML.

Em produção o mesmo arquivo é passado a `mlflow.pyfunc.log_model(model_config=...)`
e viaja junto com a versão registrada — mudar um valor é publicar uma versão nova.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Optional



def _project_root() -> Path:
    """Raiz com `config/` e `prompts/`.

    Local: `src/legal_agent/` -> dois níveis acima. No modelo registrado com
    `code_paths=["src/legal_agent", "config", "prompts"]` as três pastas ficam
    lado a lado em `code/` -> um nível acima.
    """
    here = Path(__file__).resolve()
    for candidate in (here.parents[1], here.parents[2]):
        if (candidate / "prompts").is_dir():
            return candidate
    return here.parents[2]


PROJECT_ROOT = _project_root()
DEFAULT_PATH = PROJECT_ROOT / "config" / "agent_config.yaml"


@dataclass
class AgentConfig:
    llm_endpoint: str = "databricks-claude-sonnet"
    router_enabled: bool = True
    answer_mode_default: str = "summary"  # summary | detail
    max_tokens_summary: int = 320
    max_tokens_detail: int = 1024
    max_tokens_router: int = 32
    max_tokens_smalltalk: int = 128
    chunk_excerpt_chars: int = 320
    k: int = 5
    query_type: str = "HYBRID"
    retrieval_min_score: Optional[float] = None  # só depois de calibrar com eval
    vs_index: str = "<catalog>.silver.legal_chunks_idx"
    fn_compare_coverage: str = "<catalog>.gold.fn_compare_coverage"


def _parse_scalar(raw: str):
    value = raw.split("#", 1)[0].strip()
    if value in ("", "null", "~"):
        return None
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            pass
    return value.strip("'\"")


def config_from_dict(values: dict) -> AgentConfig:
    """Constrói a config a partir de um dict (ex.: `mlflow.models.ModelConfig().to_dict()`)."""
    known = {f.name for f in fields(AgentConfig)}
    return AgentConfig(**{k: v for k, v in values.items() if k in known})


def load_config(path: Optional[Path] = None) -> AgentConfig:
    """Leitor YAML plano (chave: valor) — sem dependência externa para o smoke."""
    path = Path(path or DEFAULT_PATH)
    known = {f.name for f in fields(AgentConfig)}
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
                continue
            key, raw = line.split(":", 1)
            key = key.strip()
            if key in known:
                values[key] = _parse_scalar(raw)
    return AgentConfig(**values)
