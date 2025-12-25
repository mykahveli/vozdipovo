# VozDiPovo App: Pipeline de Notícias Automatizado

## 📰 Visão Geral do Projeto

A **VozDiPovo App** é um sistema de **jornalismo automatizado** concebido para transformar dados brutos de fontes de notícias externas em artigos prontos a publicar no WordPress. O projeto opera como um pipeline de processamento de dados contínuo, utilizando Modelos de Linguagem de Grande Escala (LLMs) para tomar decisões editoriais críticas e gerar conteúdo de alta qualidade.

O objetivo principal é automatizar o ciclo de vida da notícia: desde a recolha (Scraping) e avaliação (Judging) até à redação (Generation) e publicação (Publishing).

## 🏗️ Arquitetura e Componentes Chave

A aplicação segue uma arquitetura modular, focada na resiliência e na fácil manutenção.

### 1. Pipeline Sequencial de 4 Fases

O fluxo de trabalho é executado sequencialmente, com o estado de cada artigo rastreado na base de dados SQLite (`configs/vozdipovo.db`).

| Fase | Módulo Principal | Descrição | Estado de Transição (news\_articles) |
| :--- | :--- | :--- | :--- |
| **Scraping** | `scrapers/*` | Recolha de notícias de fontes configuradas em `sites.yaml`. | Cria registo em `news_articles` com `judge_status=PENDING`. |
| **Judging** | `pipeline/judging.py` | Avaliação editorial por LLM (Juiz) com base em critérios de relevância e credibilidade. | `judge_status=JUDGED` (Aprovado) ou `SKIPPED`/`FAILED`. |
| **Generation** | `pipeline/generation.py` | Geração do artigo final (título, corpo, SEO) por LLM, utilizando prompts editoriais. | `revision_status=revised`. |
| **Publishing** | `pipeline/publishing.py` | Publicação do artigo finalizado no WordPress. | `publishing_status=SUCCESS`. |

### 2. Abstração de LLM (LLM Router)

Para garantir a **compartimentalização** e a **flexibilidade**, a aplicação utiliza um **LLM Router** (`src/vozdipovo_app/providers/llm_router.py`). Este módulo centraliza todas as chamadas a LLMs (Groq, Gemini, Cerebras, etc.), permitindo que o pipeline mude de fornecedor ou adicione novos modelos sem alterar a lógica de negócio das fases.

| Fase           | Usa LLM? | Plataforma / Roteamento                                  | Modelos típicos (o que esperas ver)          | Output gravado                                  |
| -------------- | -------: | -------------------------------------------------------- | -------------------------------------------- | ----------------------------------------------- |
| **scraping**   |        ❌ | —                                                        | —                                            | `legal_docs` (raw/text)                         |
| **judging**    |        ✅ | **PublicAI → (Groq por padrão hoje)**                    | Normalmente 1 modelo “rápido” (ex.: Groq)    | scores + `review_status='JUDGED'`               |
| **generation** |        ✅ | **PublicAI → (Groq/OpenRouter, conforme implementação)** | modelo gerador (pode ser Groq ou OpenRouter) | `titulo`, `corpo_md`, `keywords`                |
| **revising**   |        ✅ | **PublicAI → Groq + OpenRouter (rotator)**               | Groq + OpenRouter (na tua ordem definida)    | `reviewed_by_model`, `categoria_tematica`, etc. |
| **publishing** |        ❌ | —                                                        | —                                            | WordPress post + `publishing_status`            |
| **curation**   |     ✅/⚠️ | Depende (às vezes é heurística; às vezes LLM)            | se LLM: modelo “leve”                        | `highlight_type`                                |
| **audio**      |     ❌/⚠️ | Depende do TTS (não é LLM de chat)                       | TTS engine                                   | `audio_filepath`                                |

### 3. Configuração Externa

A lógica editorial e operacional é configurada através de ficheiros externos, permitindo ajustes rápidos sem modificação do código:

*   **`configs/sites.yaml`**: Fontes de notícias e parâmetros de scraping.
*   **`configs/editorial.json`**: Limiares (thresholds) de pontuação e parâmetros operacionais do Juiz.
*   **`configs/prompts/*.md`**: Prompts de sistema para o Juiz e para a Geração de conteúdo.

## 🚀 Como Começar

### 1. Setup do Ambiente

O projeto requer Python 3.12+.

```bash
# 1. Criar e ativar o ambiente virtual
python3.12 -m venv .venv
source .venv/bin/activate

# 2. Instalar dependências
pip install -U pip setuptools wheel
pip install -e .
```

### 2. Configuração Inicial

1.  **Variáveis de Ambiente:** Defina as chaves de API necessárias no seu ambiente ou num ficheiro `.env`.
    ```bash
    export GROQ_API_KEY="sua_chave_groq"
    export NEWSROOM_MIN_FINAL_SCORE=0.6
    # ... outras variáveis conforme o RUNBOOK.md
    ```
2.  **Inicializar a Base de Dados:**
    ```bash
    python3 scripts/init_db.py
    ```

### 3. Execução do Pipeline

O pipeline pode ser executado em modo *full* ou faseado, utilizando o comando de *entrypoint* `vozdipovo-run`.

#### Execução Completa (Uma Vez)

```bash
vozdipovo-run --stage full
```

#### Execução Faseada (Para Debug ou Manutenção)

```bash
vozdipovo-run --stage scraping
vozdipovo-run --stage judging
vozdipovo-run --stage generation
vozdipovo-run --stage publishing
```

#### Execução Contínua (Produção)

Para produção, é recomendado configurar um `cron job` ou um `systemd timer` para executar o pipeline em intervalos regulares (ex: a cada 30 minutos). Consulte o **`RUNBOOK.md`** para exemplos de configuração de produção.

## 🛠️ Manutenção e Debug

### Curadoria Manual

A interface de linha de comandos para curadoria permite a intervenção manual no pipeline:

```bash
vozdipovo-curate
```

### Limpeza e Reset Total

**ATENÇÃO:** Este comando apaga todos os artigos e posts no WordPress remoto.

```bash
# Limpa a base de dados local e o WordPress remoto
vozdipovo-reset-wp
```

### Monitorização

Para monitorizar o progresso do pipeline e identificar gargalos, utilize o comando de status e as queries SQL de auditoria detalhadas no `RUNBOOK.md`.

```bash
vozdipovo-status
tail -f data/logs/bot.log
```

## 📚 Documentação Adicional

*   **`RUNBOOK.md`**: Detalhes operacionais, variáveis de ambiente críticas, recuperação de falhas e queries SQL de auditoria.
*   **`TODO.md`**: Lista de tarefas de desenvolvimento e melhorias futuras.
*   **`vozdipovo_schemaDB.txt`**: Esquema da base de dados SQLite.
