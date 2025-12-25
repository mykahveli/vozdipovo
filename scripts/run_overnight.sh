#!/usr/bin/env bash
#!filepath: scripts/run_overnight.sh
# Tornar executável: chmod +x scripts/run_overnight.sh
# Rodar: ./scripts/run_overnight.sh
# Rodar com a shell fechada: nohup ./scripts/run_overnight.sh >/dev/null 2>&1 &
# Logs ficam em: ls -lah data/logs/overnight_*.log

set -euo pipefail

export LOG_LEVEL="${LOG_LEVEL:-INFO}"

PY="${PY:-python3.12}"
DB="${DB:-configs/vozdipovo.db}"
LOG_DIR="${LOG_DIR:-data/logs}"
mkdir -p "$LOG_DIR"

TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/overnight_$TS.log"

exec > >(tee -a "$LOG_FILE") 2>&1

echo "🛌 Overnight run started at $(date)"
echo "📄 Log: $LOG_FILE"
echo

run_stage () {
  local stage="$1"
  echo "▶️  Stage: $stage @ $(date)"
  "$PY" scripts/run_once.py --stage "$stage"
  echo "✅ Done: $stage @ $(date)"
  echo
}

counts_snapshot () {
  echo "📊 Snapshot @ $(date)"
  sqlite3 "$DB" "
  SELECT 'legal_docs' AS metric, COUNT(*) AS n FROM legal_docs
  UNION ALL
  SELECT 'news_articles' AS metric, COUNT(*) AS n FROM news_articles
  UNION ALL
  SELECT 'judged_pending' AS metric, COUNT(*) AS n
    FROM news_articles
    WHERE review_status='JUDGED' AND (publishing_status='PENDING' OR publishing_status IS NULL)
  UNION ALL
  SELECT 'success_pending_publish' AS metric, COUNT(*) AS n
    FROM news_articles
    WHERE review_status='SUCCESS' AND (publishing_status='PENDING' OR publishing_status IS NULL)
  UNION ALL
  SELECT 'published' AS metric, COUNT(*) AS n
    FROM news_articles
    WHERE publishing_status='SUCCESS'
  UNION ALL
  SELECT 'highlights' AS metric, COUNT(*) AS n
    FROM news_articles
    WHERE highlight_type IS NOT NULL;
  "
  echo
}

no_more_work () {
  local judged_pending
  local success_pending
  judged_pending="$(sqlite3 "$DB" "SELECT COUNT(*) FROM news_articles WHERE review_status='JUDGED' AND (publishing_status='PENDING' OR publishing_status IS NULL);")"
  success_pending="$(sqlite3 "$DB" "SELECT COUNT(*) FROM news_articles WHERE review_status='SUCCESS' AND (publishing_status='PENDING' OR publishing_status IS NULL);")"
  if [[ "${judged_pending:-0}" == "0" && "${success_pending:-0}" == "0" ]]; then
    return 0
  fi
  return 1
}

CYCLES="${CYCLES:-999}"
SLEEP_BETWEEN_CYCLES="${SLEEP_BETWEEN_CYCLES:-10}"

counts_snapshot

for ((i=1; i<=CYCLES; i++)); do
  echo "🔁 Cycle $i"
  echo

  run_stage "judging"
  run_stage "generation"
  run_stage "revising"
  run_stage "publishing"
  run_stage "curation"
  run_stage "audio"

  counts_snapshot

  if no_more_work; then
    echo "🎉 No more eligible work. Finishing at $(date)"
    exit 0
  fi

  echo "⏳ Sleeping ${SLEEP_BETWEEN_CYCLES}s before next cycle..."
  sleep "$SLEEP_BETWEEN_CYCLES"
  echo
done

echo "⚠️ Reached max cycles ($CYCLES). Stopping at $(date)"
exit 0
