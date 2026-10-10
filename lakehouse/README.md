# Caminho offline — como o acervo é preparado (Medallion)

Os notebooks de ingestão não estão versionados aqui (são específicos de cada ambiente);
este é o desenho, com os trechos que importam.

```
Volume UC (PDFs) ─► bronze.pdf_raw ─► silver.pdf ─► silver.parsed ─► silver.chunks ─► Vector Search (Delta-Sync)
                    Auto Loader        chave +       ai_parse_       chunking por      índice HYBRID,
                    binaryFile+MERGE   vínculo (CDF) document        seção (CDF)       embeddings gerenciados
```

| Etapa | Decisão | Por quê |
|---|---|---|
| **Bronze** | `binaryFile` + `MERGE` por caminho | Reprocessar não duplica; o resto do pipeline não depende do arquivo solto |
| **Silver · pdf** | Vínculo `law_id` com o cadastro + Change Data Feed | O vínculo permite cruzar a norma pública com o escopo privado; o CDF processa só o que mudou |
| **Silver · parsed** | `ai_parse_document` → `VARIANT`, quarentena para falhas, lotes, janelas de páginas para PDFs grandes | Parse persistido: reindexar não exige parsear de novo |
| **Silver · chunks** | Chunking por seção (artigo, item, anexo), preservando o rótulo | A citação precisa apontar `arquivo + seção`, não "página 37" |
| **Índice** | `DELTA_SYNC` com pipeline `TRIGGERED`, chave `chunk_id`, query `HYBRID` | Semântica + termo exato (`NE-01`, `art. 4`); sync disparado pelo job, não contínuo |

```sql
-- parse (SQL)
SELECT path, ai_parse_document(content) AS parsed
FROM <catalog>.bronze.pdf_raw;
```

```python
# índice (SDK)
from databricks.vector_search.client import VectorSearchClient

vsc = VectorSearchClient()
vsc.create_delta_sync_index(
    endpoint_name="<vs-endpoint>",
    index_name="<catalog>.silver.legal_chunks_idx",
    source_table_name="<catalog>.silver.legal_chunks",
    primary_key="chunk_id",
    pipeline_type="TRIGGERED",
    embedding_source_column="chunk_text",
    embedding_model_endpoint_name="<embedding-endpoint>",
)
```
