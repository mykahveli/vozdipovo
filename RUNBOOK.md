# RUNBOOK — VozDiPovo App

## Objetivo
Documento operacional para execução, monitorização e recuperação do pipeline VozDiPovo.

---

## Pipeline
Scraping → Judging → Generation → Revisão → Publishing → Curadoria → Áudio

Estados principais na tabela `news_articles`:
- `review_status`: `JUDGED` | `SUCCESS` | `FAILED`
- `publishing_status`: `PENDING` | `SUCCESS` | `FAILED`
- `highlight_type`: `BREAKING` | `FEATURED` | `NULL`

---

## Execução

### Execução completa
```bash
python3.12 scripts/run_once.py --stage full
````

### Execução faseada

```bash
python3.12 scripts/run_once.py --stage scraping
python3.12 scripts/run_once.py --stage judging
python3.12 scripts/run_once.py --stage generation
python3.12 scripts/run_once.py --stage revising
python3.12 scripts/run_once.py --stage publishing
python3.12 scripts/run_once.py --stage curation
python3.12 scripts/run_once.py --stage audio
```

---

## Reclassificação (Categoria)

Usar quando artigos ficaram com `categoria_tematica = 'Geral'` ou vazia.

```bash
python3.12 scripts/run_once.py --stage revising --limit 50
```

Auditoria:

```bash
sqlite3 configs/vozdipovo.db "
SELECT legal_doc_id, categoria_tematica, subcategoria
FROM news_articles
WHERE review_status='SUCCESS'
ORDER BY legal_doc_id DESC
LIMIT 50;
"
```

---

## Curadoria (Homepage)

A curadoria usa thresholds e limites do `configs/editorial.json` para:

* marcar `highlight_type=BREAKING` ou `FEATURED`
* sincronizar categorias highlight no WordPress

Auditoria:

```bash
sqlite3 configs/vozdipovo.db "
SELECT legal_doc_id, wp_post_id, score_editorial, highlight_type, published_at
FROM news_articles
WHERE highlight_type IS NOT NULL
ORDER BY score_editorial DESC;
"
```

---

## Análises Estatísticas (Scores & Thresholds)

### Objetivo

Apoiar decisões sobre:

* `scoring.significance_threshold`
* `homepage.breaking.editorial_threshold` e `homepage.featured.editorial_threshold`
* limites de Breaking/Featured para homepage

### Execução do relatório

```bash
python3.12 scripts/stats_scores.py
```

O relatório imprime estatísticas por score, tipicamente:

* `count`
* `avg`
* `median`
* `p75` (percentil 75)
* `p90` (percentil 90)
* `min`
* `max`

### Como interpretar (heurística prática)

Use percentis para ajustar thresholds de forma estável:

* **Featured**

  * Objetivo: manter uma lista “cheia” e consistente
  * Ponto de partida: `featured.editorial_threshold ≈ p75(score_editorial)`
  * Se a homepage ficar vazia: baixar para `median`
  * Se estiver “cheia demais”: subir para `p90`

* **Breaking**

  * Objetivo: poucos itens e realmente fortes
  * Ponto de partida: `breaking.editorial_threshold ≈ p90(score_editorial)`
  * Se estiver a entrar demasiado conteúdo: subir acima de `p90`
  * Se não entrar nada por longos períodos: descer para perto de `p75`

* **Significance threshold (entrada na redação)**

  * Controla quantos artigos passam de `JUDGED` para redação
  * Ponto de partida: `significance_threshold ≈ median(final_score)` ou `p75(final_score)` dependendo do volume
  * Se a redação estiver a “engasgar”: subir o threshold
  * Se estiver “seca”: baixar o threshold

### Auditoria: distribuição na BD

Últimos scores julgados (amostra rápida):

```bash
sqlite3 configs/vozdipovo.db "
SELECT legal_doc_id, site_name, final_score, score_editorial, score_cv_relevance, created_at
FROM news_articles
WHERE review_status IN ('JUDGED','SUCCESS')
ORDER BY legal_doc_id DESC
LIMIT 50;
"
```

Itens publicados (para validar se a curadoria está coerente):

```bash
sqlite3 configs/vozdipovo.db "
SELECT legal_doc_id, wp_post_id, final_score, score_editorial, highlight_type, categoria_tematica, published_at
FROM news_articles
WHERE publishing_status='SUCCESS'
ORDER BY published_at DESC
LIMIT 50;
"
```

### Auditoria: quantos candidatos existem para Featured/Breaking

```bash
sqlite3 configs/vozdipovo.db "
WITH recent AS (
  SELECT *
  FROM news_articles
  WHERE review_status='SUCCESS'
    AND published_at >= datetime('now', '-24 hours')
)
SELECT
  SUM(CASE WHEN score_editorial >= 4.0 THEN 1 ELSE 0 END) AS breaking_candidates,
  SUM(CASE WHEN score_editorial >= 1.5 THEN 1 ELSE 0 END) AS featured_candidates,
  COUNT(*) AS total_success_recent
FROM recent;
"
```

### Recomendações para estabilidade

* Só alterar thresholds depois de ter:

  * pelo menos **30–50 artigos julgados** (amostra mínima)
  * pelo menos **1–2 janelas completas** de `homepage.time_window_hours`
* Manter um registo de alterações (data/valor) ao ajustar `editorial.json`

---

## WordPress — Verificação

Publicados:

```bash
sqlite3 configs/vozdipovo.db "
SELECT legal_doc_id, wp_post_id, publishing_status, categoria_tematica, highlight_type, published_at
FROM news_articles
WHERE publishing_status='SUCCESS'
ORDER BY published_at DESC
LIMIT 50;
"
```

Pendentes:

```bash
sqlite3 configs/vozdipovo.db "
SELECT legal_doc_id, review_status, publishing_status, categoria_tematica
FROM news_articles
WHERE review_status='SUCCESS'
  AND (publishing_status='PENDING' OR publishing_status IS NULL)
ORDER BY legal_doc_id DESC
LIMIT 50;
"
```

---

## Problemas Comuns

### Tudo vai para "Geral"

Causa típica: revisor devolveu `categoria_tematica` vazia/fora da lista; pipeline cai em fallback.
Ação:

```bash
python3.12 scripts/run_once.py --stage revising --limit 50
```

### Nada para publicar

Verificar se existem itens `SUCCESS` e `PENDING`:

```bash
sqlite3 configs/vozdipovo.db "
SELECT COUNT(*)
FROM news_articles
WHERE review_status='SUCCESS'
  AND (publishing_status='PENDING' OR publishing_status IS NULL);
"
```

### database is locked

Causa típica: duas execuções simultâneas.
Ação: garantir single-instance (prod: systemd timer + sem cron duplicado).

---

## Logs

```bash
tail -f data/logs/bot.log
```

```bash
export LOG_LEVEL=DEBUG
```

---

## Reset Total (Perigoso)

```bash
rm configs/vozdipovo.db
python3 scripts/init_db.py
python3 scripts/reset_wp.py
```
