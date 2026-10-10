from legal_agent.agent import answer_text
from conftest import UPN_NORTE, req


def test_legal_one_retrieval_one_scope_one_draft(agent, parts):
    llm, retriever, coverage = parts
    out = agent.predict(req("A comissão de prevenção da NE-01 é por CNPJ?", upn=UPN_NORTE, request_id="r-1"))
    co = out["custom_outputs"]
    assert (len(retriever.calls), len(coverage.calls), len(llm.seen)) == (1, 1, 1)
    assert co["intent"] == "legal" and co["answer_mode"] == "summary"
    assert co["citations"] == ["NE-01-comissao-de-prevencao.pdf"]
    assert co["request_id"] == "r-1"
    assert "3 de 4 artigos atendem" in answer_text(out)


def test_expand_focuses_on_cited_document(agent, parts):
    _, retriever, _ = parts
    first = agent.predict(req("A comissão de prevenção da NE-01 é por CNPJ?", upn=UPN_NORTE))
    history = [{"type": "message", "role": "user", "content": "A comissão de prevenção da NE-01 é por CNPJ?"},
               {"type": "message", "role": "assistant", "content": answer_text(first)},
               {"type": "function_call", "name": "recuperar_legislacao", "arguments": "{}"}]
    out = agent.predict(req("Detalhe mais sobre o mandato dos membros", upn=UPN_NORTE, history=history))
    assert out["custom_outputs"]["answer_mode"] == "detail"
    assert retriever.calls[-1]["file_name"] == "NE-01-comissao-de-prevencao.pdf"


def test_expand_without_history_asks_for_context(agent, parts):
    _, retriever, _ = parts
    out = agent.predict(req("Detalhe o item 1.3 da norma"))
    assert "preciso saber qual norma" in answer_text(out)
    assert retriever.calls == []


def test_reformulate_does_not_search(agent, parts):
    _, retriever, _ = parts
    history = [{"type": "message", "role": "user", "content": "x"},
               {"type": "message", "role": "assistant", "content": "Segundo NE-02-residuos-industriais.pdf (art. 4): inventário anual."}]
    out = agent.predict(req("Explique de forma mais simples", history=history))
    assert out["custom_outputs"]["intent"] == "reformulate"
    assert retriever.calls == []
    assert "NE-02-residuos-industriais.pdf" in answer_text(out)
