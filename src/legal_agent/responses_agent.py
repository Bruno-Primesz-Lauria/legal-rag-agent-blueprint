"""Empacotamento MLflow 3 (`ResponsesAgent`) para Model Serving.

Uso no Databricks (models-from-code):

    mlflow.pyfunc.log_model(
        name="agent",
        python_model="src/legal_agent/responses_agent.py",
        code_paths=["src/legal_agent", "config", "prompts"],
        model_config="config/agent_config.yaml",
        pip_requirements="requirements-databricks.txt",
        registered_model_name="<catalog>.gold.legal_agent",
    )

Com `LEGAL_AGENT_SKIP_EXPORT=1` o módulo pode ser importado sem instanciar o agente.
"""
from __future__ import annotations

import os

import mlflow
from mlflow.pyfunc import ResponsesAgent
from mlflow.types.responses import ResponsesAgentRequest, ResponsesAgentResponse

from legal_agent.adapters.databricks import DatabricksLLM, UCCoverageTool, VectorSearchRetriever
from legal_agent.agent import ComplianceAgent
from legal_agent.config import DEFAULT_PATH, config_from_dict


class LegalResponsesAgent(ResponsesAgent):
    def __init__(self):
        # em serving, o YAML vem de `model_config` (viaja com a versão registrada)
        cfg = config_from_dict(mlflow.models.ModelConfig(development_config=str(DEFAULT_PATH)).to_dict())
        self.agent = ComplianceAgent(
            llm=DatabricksLLM(cfg),
            retriever=VectorSearchRetriever(cfg),
            coverage=UCCoverageTool(cfg),
            cfg=cfg,
        )

    @mlflow.trace(span_type="AGENT", name="legal_agent.predict")
    def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
        out = self.agent.predict(request.model_dump(exclude_none=True))
        return ResponsesAgentResponse(output=out["output"], custom_outputs=out["custom_outputs"])


if os.environ.get("LEGAL_AGENT_SKIP_EXPORT") != "1":
    mlflow.models.set_model(LegalResponsesAgent())
