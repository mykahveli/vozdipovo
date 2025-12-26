#!launch.sh
#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

PYTHON_BIN="${PYTHON_BIN:-python3.12}"
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  PYTHON_BIN="${PYTHON_FALLBACK_BIN:-python3}"
fi

VENV_DIR="${VENV_DIR:-.venv}"
PIP_BIN="${VENV_DIR}/bin/pip"
PY_BIN="${VENV_DIR}/bin/python"

export PYTHONPATH="${PYTHONPATH:-src}"

die() {
  printf '%s\n' "$*" 1>&2
  exit 1
}

need_venv() {
  if [[ ! -x "${PY_BIN}" ]]; then
    die "venv não encontrado, executa: ./launch.sh reset_env"
  fi
}

run_python() {
  if [[ -x "${PY_BIN}" ]]; then
    "${PY_BIN}" "$@"
    return 0
  fi
  "${PYTHON_BIN}" "$@"
}

run_stage() {
  local stage="$1"
  shift || true
  local args=()
  args+=("--stage" "${stage}")
  while [[ $# -gt 0 ]]; do
    args+=("$1")
    shift
  done
  run_python -m vozdipovo_app.tools.pipeline_doctor "${args[@]}"
}

reset_env() {
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
  "${PY_BIN}" -m pip install --upgrade pip setuptools wheel
  "${PIP_BIN}" install -e ".[dev]"
}

reset_db_only() {
  run_python scripts/reset_db.py
  run_python scripts/init_db.py
}

reset_factory() {
  reset_env
  reset_db_only
  if [[ "${RESET_WP:-0}" == "1" ]]; then
    run_python scripts/reset_wp.py
  fi
}

pipeline_full() {
  local limit="${LIMIT:-50}"
  local threshold="${SIGNIFICANCE_THRESHOLD:-0.0}"
  local http_debug="${HTTP_DEBUG:-0}"

  local args_common=()
  args_common+=("--limit" "${limit}")
  args_common+=("--significance-threshold" "${threshold}")
  if [[ "${http_debug}" == "1" ]]; then
    args_common+=("--http-debug")
  fi

  run_stage scraping "${args_common[@]}"
  run_stage judging "${args_common[@]}"
  run_stage generation "${args_common[@]}"
  run_stage revisao "${args_common[@]}"
  run_stage publishing "${args_common[@]}"
  run_stage curadoria "${args_common[@]}"
  run_stage audio "${args_common[@]}"
}

pipeline_partial() {
  local limit="${LIMIT:-50}"
  local threshold="${SIGNIFICANCE_THRESHOLD:-0.0}"
  local http_debug="${HTTP_DEBUG:-0}"

  local args_common=()
  args_common+=("--limit" "${limit}")
  args_common+=("--significance-threshold" "${threshold}")
  if [[ "${http_debug}" == "1" ]]; then
    args_common+=("--http-debug")
  fi

  run_stage scraping "${args_common[@]}"
  run_stage judging "${args_common[@]}"
  run_stage generation "${args_common[@]}"
  run_stage revisao "${args_common[@]}"
}

pipeline_stage() {
  [[ $# -ge 1 ]] || die "uso: ./launch.sh stage <nome_do_stage> [args]"
  local stage="$1"
  shift || true
  run_stage "${stage}" "$@"
}

db_stats() {
  run_python - <<'PY'
import sqlite3
from vozdipovo_app.settings import get_settings

p = str(get_settings().db_path)
c = sqlite3.connect(p)
c.row_factory = sqlite3.Row

legal_docs = c.execute("select count(1) n from legal_docs").fetchone()["n"]
news_articles = c.execute("select count(1) n from news_articles").fetchone()["n"]
write = c.execute("select count(1) n from news_articles where decision='WRITE'").fetchone()["n"]
judged = c.execute("select count(1) n from news_articles where review_status='JUDGED'").fetchone()["n"]
failed = c.execute("select count(1) n from news_articles where review_status='FAILED'").fetchone()["n"]
success = c.execute("select count(1) n from news_articles where review_status='SUCCESS'").fetchone()["n"]

print(f"db_path={p}")
print(f"legal_docs={legal_docs}")
print(f"news_articles={news_articles}")
print(f"decision_write={write}")
print(f"review_judged={judged}")
print(f"review_failed={failed}")
print(f"review_success={success}")
c.close()
PY
}

help_text() {
  cat <<'TXT'
uso:
  ./launch.sh reset_env
  ./launch.sh reset_db
  ./launch.sh reset_factory
  ./launch.sh full
  ./launch.sh partial
  ./launch.sh stage <nome_do_stage> [args]
  ./launch.sh stats

env:
  PYTHON_BIN=python3.12
  VENV_DIR=.venv
  LIMIT=50
  SIGNIFICANCE_THRESHOLD=0.0
  HTTP_DEBUG=0
  RESET_WP=0
TXT
}

cmd="${1:-help}"
shift || true

case "${cmd}" in
  reset_env) reset_env ;;
  reset_db) reset_db_only ;;
  reset_factory) reset_factory ;;
  full) need_venv; pipeline_full ;;
  partial) need_venv; pipeline_partial ;;
  stage) need_venv; pipeline_stage "$@" ;;
  stats) db_stats ;;
  help|-h|--help) help_text ;;
  *) help_text; die "comando inválido: ${cmd}" ;;
esac
