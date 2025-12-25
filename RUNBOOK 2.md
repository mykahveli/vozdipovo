# RUNBOOK — VozDiPovo App

## Objetivo
Documento operacional para execução, monitorização e recuperação do pipeline VozDiPovo.

## Pipeline
Scraping → Judging → Generation → Revisão → Publishing → Curadoria → Áudio

## Execução
python3.12 scripts/run_once.py --stage full

Execução faseada:
python3.12 scripts/run_once.py --stage scraping
python3.12 scripts/run_once.py --stage judging
python3.12 scripts/run_once.py --stage generation
python3.12 scripts/run_once.py --stage revising
python3.12 scripts/run_once.py --stage publishing
python3.12 scripts/run_once.py --stage curation
python3.12 scripts/run_once.py --stage audio

## Reclassificação
python3.12 scripts/run_once.py --stage revising --limit 50

## Auditoria Categoria
sqlite3 configs/vozdipovo.db "
SELECT legal_doc_id, categoria_tematica, subcategoria
FROM news_articles
WHERE review_status='SUCCESS';
"

## Curadoria
sqlite3 configs/vozdipovo.db "
SELECT legal_doc_id, score_editorial, highlight_type
FROM news_articles
WHERE highlight_type IS NOT NULL;
"

## Logs
tail -f data/logs/bot.log

export LOG_LEVEL=DEBUG

## Reset Total
rm configs/vozdipovo.db
python3 scripts/init_db.py
python3 scripts/reset_wp.py
