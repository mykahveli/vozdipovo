# Lista de Tarefas (To Do) - VozDiPovo App

Esta lista de tarefas (To Do) foi gerada com base na análise da arquitetura e do fluxo de trabalho do pipeline de notícias automatizado VozDiPovo.

---
- Introduzir uma etapa de validação de múltiplas fontes na fase de avaliação para cruzar referências de factos e minimizar alucinações do LLM.

- Implemente uma camada de observabilidade usando ferramentas como Prometheus ou um painel Streamlit para rastrear o uso de tokens, o custo por artigo e o rendimento do pipeline.

## 1. Melhorias na Arquitetura e Código

| Prioridade | Módulo | Tarefa | Descrição |
| :--- | :--- | :--- | :--- |
| **Alta** | `providers/` | **Refatorar LLM Router** | Padronizar a interface de todos os clientes LLM (incluindo `cerebras_client.py`) para que o `llm_router.py` dependa apenas de uma interface abstrata. Isto reforça a compartimentalização. |
| **Média** | `config.py` | **Centralizar Configuração** | Consolidar todas as variáveis de ambiente e configurações de ficheiro num único objeto de configuração global, garantindo que o código não acede diretamente a `os.environ`. |
| **Média** | `database.py` | **Abstração de DB** | Criar uma camada de abstração para a base de dados (ex: usar SQLAlchemy ou Pydantic para mapeamento) para facilitar a migração futura de SQLite para PostgreSQL/TiDB, se a escalabilidade se tornar um problema. |
| **Baixa** | `scrapers/` | **Unificar Scrapers** | Analisar se é possível unificar `nextjs_scraper.py`, `html_scraper.py`, `rss_scraper.py` e `bo_scraper.py` numa única classe base com estratégias de *parsing* configuráveis. |

## 2. Otimização e Desempenho do Pipeline

| Prioridade | Módulo | Tarefa | Descrição |
| :--- | :--- | :--- | :--- |
| **Alta** | `pipeline/judging.py` | **Otimizar Judge** | Implementar *batching* de chamadas ao LLM para a fase de *Judging* (se a API do fornecedor permitir) para reduzir a latência e o custo por artigo. |
| **Média** | `pipeline/generation.py` | **Geração Assíncrona** | Explorar a execução assíncrona (`asyncio`) para chamadas de LLM na fase de Geração, permitindo que o pipeline processe vários artigos em paralelo enquanto espera pelas respostas da API. |
| **Média** | `utils/backoff.py` | **Ajustar Backoff** | Rever e ajustar os parâmetros de *backoff* e *retry* para otimizar a resiliência contra *rate-limiting* (especialmente para o Groq/LLM Router). |
| **Baixa** | `image_manager.py` | **Geração de Imagens** | Adicionar a funcionalidade de geração de imagens por IA (ex: DALL-E, Midjourney API) para criar imagens de destaque para os artigos, em vez de depender apenas de imagens existentes. |

## 3. Manutenção e Operação (DevOps)

| Prioridade | Módulo | Tarefa | Descrição |
| :--- | :--- | :--- | :--- |
| **Alta** | `RUNBOOK.md` | **Documentar Curadoria** | Adicionar uma secção detalhada ao `RUNBOOK.md` sobre como usar o `vozdipovo-curate` (Curator CLI) para intervenção manual, incluindo exemplos de comandos SQL para correção de estado. |
| **Média** | `scripts/` | **Monitorização de Logs** | Implementar rotação de logs (`logrotate`) para `data/logs/bot.log` para evitar o preenchimento do disco em produção. |
| **Média** | `commands/status.py` | **Métricas em Tempo Real** | Melhorar o comando `vozdipovo-status` para incluir métricas de latência (tempo médio por fase) e *throughput* (artigos/hora). |
| **Baixa** | `pyproject.toml` | **Dependências** | Rever e atualizar todas as dependências do projeto para as versões mais recentes e seguras. |

## 4. Melhorias Editoriais e de Conteúdo

| Prioridade | Módulo | Tarefa | Descrição |
| :--- | :--- | :--- | :--- |
| **Alta** | `configs/prompts/` | **Revisão de Prompts** | Otimizar os *prompts* do Judge e da Generation para melhorar a qualidade do conteúdo e a precisão das decisões editoriais (ex: aumentar a ênfase na verificação de factos). |
| **Média** | `wordpress/publisher.py` | **Melhorar SEO/Tags** | Implementar lógica mais sofisticada para a geração de meta-descrições e tags/categorias do WordPress, utilizando o LLM para análise de SEO. |
| **Média** | `audio_generator.py` | **Qualidade de Áudio** | Investigar e integrar um fornecedor de *Text-to-Speech* (TTS) de maior qualidade para a geração de áudio dos artigos. |
| **Baixa** | `configs/sites.yaml` | **Adicionar Fontes** | Pesquisar e adicionar 5 a 10 novas fontes de notícias relevantes para aumentar a cobertura do *Scraping*. |

## 5. Melhorias no Bot do Telegram (Intervenção Remota)

| Prioridade | Módulo | Tarefa | Descrição |
| :--- | :--- | :--- | :--- |
| **Alta** | `utils/telegram_utils.py` | **Fluxo de Ingestão Manual** | Implementar a lógica para receber uma mensagem com um link e contexto editorial (ex: `!breaking`, `!featured`) e injetar o link diretamente na base de dados para processamento imediato pelo pipeline. |
| **Alta** | `utils/telegram_utils.py` | **Relatório de Status Diário** | Configurar o bot para enviar um relatório diário (ou a pedido) com o status do pipeline (ex: total de artigos *scraped*, *judged*, *published*), utilizando as queries de auditoria do `RUNBOOK.md`. |
| **Média** | `utils/telegram_utils.py` | **Notificações de Publicação** | Enviar uma notificação concisa (sem muitas mensagens) sempre que um artigo for publicado com sucesso, incluindo o título, a URL do WordPress e o *score* editorial final. |
| **Média** | `utils/telegram_utils.py` | **Comando de Estatísticas** | Adicionar um comando (`/stats`) para apresentar as estatísticas de desempenho do pipeline (ex: taxa de aprovação do Judge, gargalo atual) em tempo real. |
| **Baixa** | `utils/telegram_utils.py` | **Comando de Debug Remoto** | Adicionar um comando seguro (`/debug`) para permitir a execução remota de comandos de diagnóstico (ex: `vozdipovo-status`) e o envio do log mais recente. |
