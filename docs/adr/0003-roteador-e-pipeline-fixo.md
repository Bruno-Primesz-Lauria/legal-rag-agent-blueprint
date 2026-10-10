# ADR-0003 — Roteador de intenções + pipeline fixo

**Status:** aceito

## Contexto
Perguntas de conformidade têm um formato estável: localizar a norma, cruzar com o
escopo da unidade e redigir uma resposta citada. Nem toda mensagem é uma pergunta
desse tipo — há saudações, pedidos de reformulação e assuntos de outros domínios.
O desenho deve dar a cada tipo de mensagem o caminho mais curto possível, com
latência e custo conhecidos de antemão.

## Decisão
1. **Roteador** com 6 intenções (`legal`, `expand`, `reformulate`, `smalltalk`,
   `out_of_domain`, `adversarial`). Regras determinísticas primeiro; o LLM só
   desempata, com teto de 32 tokens. Fail-safe fatiado: dúvida conversa × legislação →
   `legal`; dúvida entre pedido fora da política e fora do tema → rota sem busca.
2. **Pipeline fixo** no ramo legal: 1 busca → 1 consulta de escopo → 1 redação.
3. **Resposta em duas camadas:** resumo curto no 1º turno, detalhe só sob pedido
   (busca focada no documento já citado).

## Consequências
- Custo e latência por pergunta são previsíveis: no máximo uma chamada a cada recurso.
- Rotas sem busca respondem em poucos segundos e não consomem o acervo.
- O agente é stateless: multi-turno usa o histórico reenviado pelo app (só itens
  `type: "message"`).
