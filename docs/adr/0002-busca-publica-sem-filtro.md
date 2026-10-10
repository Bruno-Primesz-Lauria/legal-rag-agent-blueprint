# ADR-0002 — A busca no acervo não é filtrada por usuário

**Status:** aceito

## Contexto
A norma é pública e igual para todos. Filtrar a busca por usuário misturaria duas
fronteiras (relevância e autorização) e esconderia normas relevantes.

## Decisão
A ferramenta A (Vector Search) nunca recebe identidade. A fronteira de autorização
vive só nas funções governadas do Unity Catalog (ferramentas B/C). O único filtro
permitido na busca é o foco por documento (`file_name`), usado no pedido de detalhe.

## Consequências
Uma resposta pode ter a parte pública completa e a privada vazia — e o agente diz isso.
