O VozDiPovo App é um pipeline de jornalismo automatizado projetado para otimizar o ciclo de vida completo das notícias, desde a ingestão de dados brutos até a publicação no WordPress. O sistema utiliza uma arquitetura modular de quatro fases — Scraping, Julgamento, Geração e Publicação — e emprega um Roteador LLM centralizado para gerenciar decisões editoriais e geração de conteúdo de alta qualidade em vários fornecedores de IA, como Groq e Gemini.

Principais funcionalidades
Pipeline sequencial de 4 fases (raspagem, avaliação, geração, publicação) para fluxo de dados estruturado.
Rastreamento de artigos baseado em estado dentro de um banco de dados SQLite local para garantir a resiliência do processo.
Roteador LLM centralizado para alternância perfeita entre fornecedores e modelos de IA.
Lógica editorial configurável usando ficheiros externos YAML, JSON e Markdown para prompts e limites.
Otimização SEO automatizada e formatação de conteúdo personalizada para integração com o WordPress.





```bash
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
```

````markdown
#!README.md
# VozDiPovo v6

## Objetivo

Operacionalizar o pipeline completo, seguindo o fluxo:
Scraping, Judging, Generation, Revisão, Publishing, Curadoria, Áudio.

## Requisitos

1. Python 3.12
2. SQLite
3. Variáveis de ambiente para o provedor LLM que estiveres a usar
4. Acesso de rede para scraping e chamadas ao provedor LLM

## Instalação

1. Cria ambiente e instala dependências

```bash
./launch.sh reset_env
````

2. Inicializa base de dados

```bash
./launch.sh reset_db
```

## Configuração

1. Config base: configs/default.yaml
2. Config por ambiente: configs/config.development.yaml, configs/config.production.yaml
3. Sites e ordem de scraping: configs/sites.yaml

Variáveis de ambiente típicas

1. APP_ENV
2. GROQ_API_KEY
3. OPENAI_API_KEY
4. PUBLICAI_API_KEY
5. JUDGE_GROQ_MODELS
6. DIRECTOR_TIMEOUT_SECONDS
7. GROQ_TIMEOUT_SECONDS

## Execução do pipeline

Pipeline completo

```bash
./launch.sh full
```

Pipeline parcial

```bash
./launch.sh partial
```

Executar um stage específico

```bash
./launch.sh stage scraping --limit 200 --http-debug
./launch.sh stage judging --limit 50 --significance-threshold 3.0
./launch.sh stage generation --limit 10 --significance-threshold 3.0
```

Ver estatísticas da base

```bash
./launch.sh stats
```

## Observações operacionais

1. O Scraping segue a ordem do configs/sites.yaml
2. Em caso de falha, o Scraping faz requeue e tenta mais uma vez o site que falhou
3. Após o Scraping, o pipeline continua com Judging

## Troubleshooting rápido

1. Se o Scraping falhar, corre com http debug

```bash
HTTP_DEBUG=1 ./launch.sh stage scraping --limit 200 --http-debug
```

2. Se o Judging estiver lento, usa um modelo mais rápido na lista do Groq

```bash
export JUDGE_GROQ_MODELS="meta-llama/llama-4-scout-17b-16e-instruct,qwen/qwen3-32b,llama-3.3-70b-versatile"
./launch.sh stage judging --limit 50 --http-debug
```

3. Se Generation disser fonte curta, é um problema de qualidade de fonte, não um crash
4. Se Generation disser baixa fidelidade, o texto gerado não está suficientemente ancorado na fonte, reduz threshold e ajusta prompt, ou melhora o content_text no scraping

````

```markdown
#!CHEATSHEET.md
# VozDiPovo v6, Cheatsheet

## Setup

```bash
./launch.sh reset_env
./launch.sh reset_db
./launch.sh stats
````

## Scraping

Scraping de todos os sites por ordem do configs/sites.yaml

```bash
./launch.sh stage scraping --limit 200
```

Scraping com detalhe de rede

```bash
HTTP_DEBUG=1 ./launch.sh stage scraping --limit 200 --http-debug
```

Scraping de um site

```bash
./launch.sh stage scraping --site bo_cv --limit 200
./launch.sh stage scraping --site governo_cv --limit 50
```

## Judging

```bash
export JUDGE_GROQ_MODELS="meta-llama/llama-4-scout-17b-16e-instruct,qwen/qwen3-32b,llama-3.3-70b-versatile"
export DIRECTOR_TIMEOUT_SECONDS=90
export GROQ_TIMEOUT_SECONDS=90
./launch.sh stage judging --limit 50 --http-debug
```

## Generation

Sem threshold, escreve tudo o que está marcado como WRITE

```bash
./launch.sh stage generation --limit 10 --http-debug
```

Com threshold, restringe por score

```bash
./launch.sh stage generation --limit 10 --significance-threshold 3.0 --http-debug
```

## Revisão

```bash
./launch.sh stage revisao --limit 10 --http-debug
```

## Publishing

```bash
./launch.sh stage publishing --limit 10 --http-debug
```

## Curadoria

```bash
./launch.sh stage curadoria --limit 20 --http-debug
```

## Áudio

```bash
./launch.sh stage audio --limit 20 --http-debug
```

## SQL rápido

```bash
python3.12 - <<'PY'
import sqlite3
from vozdipovo_app.settings import get_settings
p = str(get_settings().db_path)
c = sqlite3.connect(p)
print("legal_docs", c.execute("select count(1) from legal_docs").fetchone()[0])
print("news_articles", c.execute("select count(1) from news_articles").fetchone()[0])
print("decisions", c.execute("select decision, count(1) from news_articles group by decision").fetchall())
c.close()
PY
```

````

```markdown
#!TODO.md
# TODO, VozDiPovo v6

## Prioridade 1, Pipeline operacional ponta a ponta

1. Scraping robusto em todos os sites configurados
2. Judging com limites, retries e modelos rápidos como default
3. Generation com fonte confiável, e validação de fidelidade ao texto fonte
4. Revisão consistente, com fallback quando o editor falhar
5. Publishing com idempotência, retry e logs úteis
6. Curadoria com regras claras de destaque
7. Áudio com pydub e produção dos ficheiros com naming estável

## Prioridade 2, Qualidade de dados

1. Normalizar content_text no scraping para fontes RSS, HTML e NextJs
2. Guardar raw_payload_json sempre que existir payload estruturado
3. Melhorar deduplicação por url_hash e títulos equivalentes

## Prioridade 3, Observabilidade

1. Logs estruturados por corr id
2. Métricas por stage, processados, falhas, tempo médio por item
3. Modo verbose para LLM, request, response, latências e erros

## Prioridade 4, Operação

1. launch.sh como entrypoint único
2. README, CHEATSHEET e RUNBOOK alinhados com pipeline_doctor
3. Scripts antigos mantidos só como legado, marcados como deprecated

## Prioridade 5, Produto

1. Templates editoriais
2. Regras de categoria e subcategoria
3. Curadoria por relevância CV e diversidade temática
````

````markdown
#!RUNBOOK.md
# RUNBOOK, VozDiPovo v6

## Objetivo

Manter o pipeline operacional e previsível, com comandos únicos, diagnóstico rápido e recuperação de falhas sem adivinhação.

## Setup

1. Ambiente

```bash
./launch.sh reset_env
````

2. Base de dados

```bash
./launch.sh reset_db
./launch.sh stats
```

## Execução diária

Pipeline completo

```bash
./launch.sh full
./launch.sh stats
```

## Execução por etapas

Scraping

```bash
./launch.sh stage scraping --limit 200
```

Judging

```bash
export JUDGE_GROQ_MODELS="meta-llama/llama-4-scout-17b-16e-instruct,qwen/qwen3-32b,llama-3.3-70b-versatile"
export DIRECTOR_TIMEOUT_SECONDS=90
export GROQ_TIMEOUT_SECONDS=90
./launch.sh stage judging --limit 50 --http-debug
```

Generation

```bash
./launch.sh stage generation --limit 10 --significance-threshold 3.0 --http-debug
```

Revisão

```bash
./launch.sh stage revisao --limit 10 --http-debug
```

Publishing

```bash
./launch.sh stage publishing --limit 10 --http-debug
```

Curadoria

```bash
./launch.sh stage curadoria --limit 20 --http-debug
```

Áudio

```bash
./launch.sh stage audio --limit 20 --http-debug
```

## Política de scraping

1. A ordem de execução é a ordem do configs/sites.yaml
2. Se um site falhar, ele vai para o fim e recebe mais uma tentativa no mesmo run
3. Se falhar novamente, o pipeline segue para Judging

## Recuperação de falhas

### Falhas no Scraping

1. Reexecuta com http debug
2. Reduz limit para isolar
3. Confirma que o site está no configs/sites.yaml e com type correto

```bash
HTTP_DEBUG=1 ./launch.sh stage scraping --limit 30 --http-debug
```

### Falhas no Judging

1. Se houver timeouts, troca o modelo para um mais rápido
2. Aumenta DIRECTOR_TIMEOUT_SECONDS só se o provider estiver consistente

```bash
export JUDGE_GROQ_MODELS="meta-llama/llama-4-scout-17b-16e-instruct,qwen/qwen3-32b"
./launch.sh stage judging --limit 20 --http-debug
```

### Falhas no Generation

1. Fonte curta, é esperado para itens com pouco conteúdo, ajusta min_source_chars no editorial config se for necessário
2. Baixa fidelidade, indica desalinhamento com a fonte, ajusta prompt e valida content_text no scraping
3. review_status fica FAILED, o item volta a ser elegível quando corrigires o problema

### Falhas no Publishing

1. Confirma wordpress.username e wordpress.app_password
2. Usa http debug e limit baixo para repetibilidade
3. Idempotência, se wp_post_id já existe, o stage deve atualizar sem duplicar

## Reset total

1. Reset de ambiente e base, opcional reset de WordPress

```bash
RESET_WP=0 ./launch.sh reset_factory
./launch.sh full
```

## Scripts legados

1. launchPipelineFull.sh
2. launchPipelineParcial.sh
3. launchResetAmbiente.sh
4. launchResetFactory.sh

Estes ficam como referência histórica, o entrypoint único é o launch.sh

```
::contentReference[oaicite:0]{index=0}
```
