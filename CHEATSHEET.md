# CHEATSHEET — VozDiPovo (Comandos Rápidos)

Coleção de comandos “copy/paste” para operar o pipeline, inspecionar a base de dados e auditorias estatísticas para ajustes editoriais.

---

## 0) Setup rápido

Ativar venv (se aplicável):
source .venv/bin/activate

Confirmar Python:

python3.12 --version

---

## 1) Executar pipeline

Pipeline completo:

python3.12 scripts/run_once.py --stage full

Por etapas:

python3.12 scripts/run_once.py --stage scraping
python3.12 scripts/run_once.py --stage judging
python3.12 scripts/run_once.py --stage generation
python3.12 scripts/run_once.py --stage revising
python3.12 scripts/run_once.py --stage publishing
python3.12 scripts/run_once.py --stage curation
python3.12 scripts/run_once.py --stage audio

Executar com limite (quando suportado):

python3.12 scripts/run_once.py --stage judging --limit 50
python3.12 scripts/run_once.py --stage publishing --limit 50

---

## 2) Logs

Ver log em “tail”:

tail -f data/logs/bot.log

Forçar verbose:

export LOG_LEVEL=DEBUG
python3.12 scripts/run_once.py --stage full

---

## 3) Base de dados — Schema e sanity checks

Ver schema completo:

sqlite3 configs/vozdipovo.db ".schema"

Ver schema específico:

sqlite3 configs/vozdipovo.db ".schema news_articles"
sqlite3 configs/vozdipovo.db ".schema legal_docs"
sqlite3 configs/vozdipovo.db ".schema pipeline_log"

Contar quantos artigos existem:

sqlite3 configs/vozdipovo.db "SELECT COUNT(*) FROM news_articles;"

Últimos 20 artigos (estado):

sqlite3 configs/vozdipovo.db "
SELECT legal_doc_id, review_status, publishing_status, wp_post_id, highlight_type, created_at
FROM news_articles
ORDER BY legal_doc_id DESC
LIMIT 20;
"

Quantos estão prontos para publicar (SUCCESS + PENDING):

sqlite3 configs/vozdipovo.db "
SELECT COUNT(*) AS ready_to_publish
FROM news_articles
WHERE review_status='SUCCESS'
  AND (publishing_status='PENDING' OR publishing_status IS NULL);
"

---

## 4) Dataset global (editorial-grade)

### 4.1) Dataset global “tudo numa linha” (SQL)

sqlite3 configs/vozdipovo.db "
SELECT
  na.legal_doc_id,
  ld.site_name,
  ld.url,
  na.titulo,
  na.categoria_tematica,
  na.subcategoria,
  na.tags,
  na.review_status,
  na.publishing_status,
  na.highlight_type,
  na.reviewed_by_model,
  na.final_score,
  na.score_editorial,
  na.score_cv_relevance,
  na.score_scale,
  na.score_impact,
  na.score_novelty,
  na.score_potential,
  na.score_legacy,
  na.score_credibility,
  na.score_positivity,
  na.wp_post_id,
  na.published_at,
  na.created_at,
  na.updated_at
FROM news_articles na
JOIN legal_docs ld ON ld.id = na.legal_doc_id
ORDER BY na.legal_doc_id DESC
LIMIT 200;
"

### 4.2) Export global para CSV/JSONL (recomendado)

python3.12 scripts/export_articles_dataset.py --db configs/vozdipovo.db --format both

Arquivos gerados (default do script):

* `data/exports/articles.csv`
* `data/exports/articles.jsonl`

---

## 5) Estatísticas (Scores & Thresholds)

### 5.1) Estatísticas rápidas do script atual

python3.12 scripts/stats_scores.py

### 5.2) Estatísticas globais (recomendado)

python3.12 scripts/stats_scores_global.py --scope all
python3.12 scripts/stats_scores_global.py --scope judged
python3.12 scripts/stats_scores_global.py --scope success
python3.12 scripts/stats_scores_global.py --scope published

---

## 6) Estatísticas por janelas e candidatos (SQL)

### 6.0) Scrapping

sqlite3 configs/vozdipovo.db << 'EOF'
.headers on
.mode column
.nullvalue NULL

.tables

.schema legal_docs
.schema news_articles

-- Contagem total de documentos legais
SELECT COUNT(*) AS total_legal_docs FROM legal_docs;

-- Documentos por site
SELECT
  site_name,
  COUNT(*) AS n
FROM legal_docs
GROUP BY site_name
ORDER BY n DESC;

-- Últimos 30 documentos
SELECT
  id,
  site_name,
  substr(COALESCE(pub_date, ''), 1, 10) AS pub,
  substr(COALESCE(title, ''), 1, 90) AS title,
  substr(COALESCE(url, ''), 1, 80) AS url
FROM legal_docs
ORDER BY id DESC
LIMIT 30;

-- Documentos com texto mais curto
SELECT
  id,
  site_name,
  length(COALESCE(text, '')) AS text_len,
  substr(COALESCE(title, ''), 1, 90) AS title
FROM legal_docs
ORDER BY text_len ASC, id DESC
LIMIT 30;

-- URLs duplicadas
SELECT
  url_hash,
  COUNT(*) AS n
FROM legal_docs
GROUP BY url_hash
HAVING n > 1
ORDER BY n DESC;

-- Status de revisão dos artigos
SELECT
  na.review_status,
  COUNT(*) AS n
FROM news_articles na
GROUP BY na.review_status
ORDER BY n DESC;

-- Documentos legais não processados ou com falha
SELECT
  ld.id AS legal_doc_id,
  ld.site_name,
  substr(COALESCE(ld.pub_date, ''), 1, 10) AS pub,
  substr(COALESCE(ld.title, ''), 1, 90) AS title
FROM legal_docs ld
LEFT JOIN news_articles na ON na.legal_doc_id = ld.id
WHERE na.legal_doc_id IS NULL
   OR na.review_status IS NULL
   OR na.review_status = ''
   OR na.review_status = 'FAILED'
ORDER BY ld.id DESC
LIMIT 50;

-- Documentos específicos para análise
SELECT
  ld.id AS legal_doc_id,
  na.review_status,
  substr(COALESCE(na.review_error, ''), 1, 140) AS err,
  na.final_score,
  substr(COALESCE(ld.title, ''), 1, 90) AS title
FROM legal_docs ld
LEFT JOIN news_articles na ON na.legal_doc_id = ld.id
WHERE ld.id IN (63, 110)
ORDER BY ld.id DESC;
EOF

### 6.1) Candidatos Breaking/Featured numa janela de 24h

Ajusta os thresholds para os teus valores em `configs/editorial.json`.

sqlite3 configs/vozdipovo.db "
WITH recent AS (
  SELECT *
  FROM news_articles
  WHERE review_status='SUCCESS'
    AND created_at >= datetime('now', '-24 hours')
)
SELECT
  COUNT(*) AS total_success_recent,
  SUM(CASE WHEN score_editorial >= 4.0 THEN 1 ELSE 0 END) AS breaking_candidates,
  SUM(CASE WHEN score_editorial >= 1.5 THEN 1 ELSE 0 END) AS featured_candidates
FROM recent;
"

### 6.2) Top publicados por score_editorial

sqlite3 configs/vozdipovo.db "
SELECT
  na.legal_doc_id,
  ld.site_name,
  na.wp_post_id,
  na.score_editorial,
  na.final_score,
  na.highlight_type,
  na.categoria_tematica,
  na.published_at,
  na.titulo
FROM news_articles na
JOIN legal_docs ld ON ld.id = na.legal_doc_id
WHERE na.publishing_status='SUCCESS'
ORDER BY na.score_editorial DESC
LIMIT 50;
"

### 6.3) Distribuição por fonte (site_name) — volume e médias

sqlite3 configs/vozdipovo.db "
SELECT
  ld.site_name,
  COUNT(*) AS n,
  ROUND(AVG(na.final_score), 3) AS avg_final,
  ROUND(AVG(na.score_editorial), 3) AS avg_editorial,
  ROUND(AVG(na.score_cv_relevance), 3) AS avg_cv_rel
FROM news_articles na
JOIN legal_docs ld ON ld.id = na.legal_doc_id
WHERE na.review_status IN ('JUDGED','SUCCESS')
GROUP BY ld.site_name
ORDER BY n DESC;
"

### 6.4) Distribuição por categoria — volume e médias

sqlite3 configs/vozdipovo.db "
SELECT
  na.categoria_tematica,
  COUNT(*) AS n,
  ROUND(AVG(na.final_score), 3) AS avg_final,
  ROUND(AVG(na.score_editorial), 3) AS avg_editorial,
  ROUND(AVG(na.score_cv_relevance), 3) AS avg_cv_rel
FROM news_articles na
WHERE na.review_status IN ('JUDGED','SUCCESS')
GROUP BY na.categoria_tematica
ORDER BY n DESC;
"

---

## 7) Curadoria / Highlights (SQL)

Ver todos os highlights:

sqlite3 configs/vozdipovo.db "
SELECT
  na.legal_doc_id,
  ld.site_name,
  na.wp_post_id,
  na.highlight_type,
  na.score_editorial,
  na.final_score,
  na.categoria_tematica,
  na.published_at,
  na.titulo
FROM news_articles na
JOIN legal_docs ld ON ld.id = na.legal_doc_id
WHERE na.highlight_type IS NOT NULL
ORDER BY na.score_editorial DESC;
"

Breaking (apenas):

sqlite3 configs/vozdipovo.db "
SELECT legal_doc_id, wp_post_id, score_editorial, published_at, titulo
FROM news_articles
WHERE highlight_type='BREAKING'
ORDER BY score_editorial DESC;
"

Featured (apenas):

sqlite3 configs/vozdipovo.db "
SELECT legal_doc_id, wp_post_id, score_editorial, published_at, titulo
FROM news_articles
WHERE highlight_type='FEATURED'
ORDER BY score_editorial DESC;
"

---

## 8) Problemas comuns (diagnóstico rápido)

### 8.1) Tudo vai para “Geral”

Ver se o revisor está a devolver `categoria_tematica`:

sqlite3 configs/vozdipovo.db "
SELECT legal_doc_id, categoria_tematica, subcategoria, reviewed_by_model, review_status
FROM news_articles
WHERE review_status='SUCCESS'
ORDER BY legal_doc_id DESC
LIMIT 50;
"

### 8.2) “database is locked”

Ver processos concorrentes (macOS/Linux):

ps aux | grep -E "run_once.py|python3.12" | grep -v grep

### 8.3) Confirmar se o pipeline_log tem details_json (p/ modelo do juiz)

sqlite3 configs/vozdipovo.db "
SELECT stage,
       COUNT(*) AS n,
       SUM(CASE WHEN details_json IS NOT NULL AND details_json != '' THEN 1 ELSE 0 END) AS with_details
FROM pipeline_log
GROUP BY stage
ORDER BY n DESC;
"

---

## 9) Reset (perigoso)

Apagar BD local e reinicializar:

rm -f configs/vozdipovo.db
python3.12 scripts/init_db.py

Limpar WordPress remoto (cuidado):

python3.12 scripts/reset_wp.py
