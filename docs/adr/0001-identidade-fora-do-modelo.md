# ADR-0001 — A identidade viaja por fora do modelo

**Status:** aceito

## Contexto
A resposta tem uma parte privada ("como a minha unidade está?"), que depende de quem
pergunta. Autorização é responsabilidade da plataforma de dados, não do modelo de
linguagem: o LLM redige, e a governança decide o que cada usuário pode ver.

## Decisão
- Um proxy confiável autentica o usuário e preenche o UPN em `custom_inputs.upn`.
- O agente lê o UPN **uma vez**, no topo de `predict`, e o entrega apenas à
  ferramenta de escopo, como argumento de código.
- O UPN nunca entra em mensagem para o LLM, nunca é argumento visível de ferramenta
  e nunca vem de `current_user()` (que seria a identidade do serviço).

## Consequências
- O texto da conversa não define identidade; ela vem sempre do envelope autenticado.
- `tests/test_no_spoof.py` mantém a regra verificada a cada push.
- A função SQL é fechada por padrão: só uma identidade presente na lista de acesso
  recebe escopo.
