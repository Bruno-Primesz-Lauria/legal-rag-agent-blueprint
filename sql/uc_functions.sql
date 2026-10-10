-- =====================================================================
-- Camada Gold governada pelo Unity Catalog — modelo GENÉRICO de exemplo.
-- Substitua <catalog>. O agente só enxerga fn_compare_coverage.
-- =====================================================================

-- Lista de acesso: quais unidades cada identidade (UPN) pode ver.
CREATE TABLE IF NOT EXISTS <catalog>.gold.d_user_acl (
  upn      STRING NOT NULL,
  unit_id  STRING NOT NULL
);

-- Fato de conformidade: situação de cada artigo de cada norma, por unidade.
CREATE TABLE IF NOT EXISTS <catalog>.gold.f_compliance (
  unit_id     STRING NOT NULL,
  law_id      STRING NOT NULL,
  article_id  STRING NOT NULL,
  status      STRING NOT NULL   -- compliant | non_compliant | partial | not_applicable
);

-- Ferramenta B (interna, NÃO registrada no agente): escopo de uma identidade.
-- Menos superfície exposta ao modelo; ponto de apoio para um futuro OBO.
CREATE OR REPLACE FUNCTION <catalog>.gold.fn_query_client_scope(p_upn STRING)
RETURNS TABLE (unit_id STRING, law_id STRING, article_id STRING, status STRING)
RETURN
  SELECT f.unit_id, f.law_id, f.article_id, f.status
  FROM <catalog>.gold.f_compliance f
  JOIN <catalog>.gold.d_user_acl a
    ON a.unit_id = f.unit_id
  WHERE p_upn IS NOT NULL
    AND lower(a.upn) = lower(p_upn);           -- sem UPN válido => vazio (fechada por padrão)

-- Ferramenta C (a única de escopo que o agente vê): cruza as normas
-- recém-recuperadas com o escopo da unidade. Escopo e atendimento separados.
CREATE OR REPLACE FUNCTION <catalog>.gold.fn_compare_coverage(ids STRING, p_upn STRING)
RETURNS TABLE (law_id STRING, in_scope BOOLEAN, articles_total INT, compliant INT,
               non_compliant INT, partial INT, not_applicable INT)
COMMENT 'Escopo da unidade do usuário para as normas informadas. UPN injetado pelo código, nunca pelo LLM.'
RETURN
  WITH wanted AS (SELECT trim(id) AS law_id FROM (SELECT explode(split(ids, ',')) AS id)),
       scope  AS (SELECT * FROM <catalog>.gold.fn_query_client_scope(p_upn))
  SELECT w.law_id,
         count(s.article_id) > 0                             AS in_scope,
         CAST(count(s.article_id) AS INT)                    AS articles_total,
         CAST(count_if(s.status = 'compliant') AS INT)       AS compliant,
         CAST(count_if(s.status = 'non_compliant') AS INT)   AS non_compliant,
         CAST(count_if(s.status = 'partial') AS INT)         AS partial,
         CAST(count_if(s.status = 'not_applicable') AS INT)  AS not_applicable
  FROM wanted w
  LEFT JOIN scope s ON s.law_id = w.law_id
  WHERE p_upn IS NOT NULL
  GROUP BY w.law_id;

-- Identidade de serviço do endpoint: só EXECUTE na função de comparação.
-- GRANT EXECUTE ON FUNCTION <catalog>.gold.fn_compare_coverage TO `<service-principal>`;
