import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from legal_agent.adapters.stubs import InMemoryCoverage, InMemoryRetriever, ScriptedLLM  # noqa: E402
from legal_agent.agent import ComplianceAgent  # noqa: E402

UPN_NORTE = "maria.exemplo@empresa-ficticia.com"


def req(text, upn=None, history=None, request_id=None):
    items = list(history or []) + [{"type": "message", "role": "user", "content": text}]
    custom = {}
    if upn:
        custom["upn"] = upn
    if request_id:
        custom["request_id"] = request_id
    return {"input": items, "custom_inputs": custom}


@pytest.fixture
def parts():
    return ScriptedLLM(), InMemoryRetriever(), InMemoryCoverage()


@pytest.fixture
def agent(parts):
    llm, retriever, coverage = parts
    return ComplianceAgent(llm=llm, retriever=retriever, coverage=coverage)
