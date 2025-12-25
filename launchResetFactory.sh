#!/bin/bash
# resetFactoryLaunch.sh
# Script para configurar e executar o ambiente do projeto
# macOS compatible

clear

echo "🧹 [1/10] Limpando ambiente anterior..."
rm -rf .venv
rm -rf src/vozdipovo_app.egg-info
rm -rf build
rm -rf dist
find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null
find . -name '*.log' -delete
find . -name '*.pyc' -delete
find . -name '._*' -type f -delete
rm data/exports/articles.csv
rm data/exports/articles.jsonl

echo "🐍 [2/10] Configurando Python 3.12..."
# FORÇAR uso do pyenv
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"

# Instalar Python se necessário
if ! pyenv versions | grep -q "3.12.0"; then
    echo "Instalando Python 3.12.0..."
    pyenv install 3.12.0 -s
fi

pyenv local 3.12.0

echo "🔧 [3/10] Criando ambiente virtual..."
python -m venv .venv --clear

# ATIVAR o ambiente de forma explícita
source .venv/bin/activate

# Verificar que estamos no ambiente correto
echo "Python sendo usado: $(which python)"
echo "Pip sendo usado: $(which pip)"

echo "📦 [4/10] Atualizando pip e instalando dependências..."
python -m pip install --upgrade pip setuptools wheel

# Instalar o projeto em modo desenvolvimento
echo "Instalando projeto e dependências..."
pip install -e .

echo "✅ [5/10] Ambiente configurado com sucesso!"
echo ""

# Limpar ficheiros locais
echo "🧹 [6/10] A limpar ficheiros locais..."
find . -type f \( -name "*.db" -o -name "*.pyc" -o -name "*.mp3" -o -name "*.log" -o -name "*.csv" -o -name "*.db-wal" -o -name "*.db-shm" \) -delete
echo "✅ Ficheiros locais limpos!"
echo ""

# Reset WordPress remoto
echo "🧹 [7/10] A limpar WordPress remoto..."
python3 scripts/reset_wp.py
if [ $? -eq 0 ]; then
    echo "✅ WordPress limpo com sucesso!"
else
    echo "⚠️  Atenção: reset_wp.py pode ter encontrado problemas"
fi
echo ""

# Inicializar base de dados
echo "🚀 [8/10] A inicializar base de dados..."
python3 scripts/init_db.py
if [ $? -eq 0 ]; then
    echo "✅ Base de dados inicializada!"
else
    echo "⚠️  Atenção: init_db.py pode ter encontrado problemas"
fi
echo ""

# Executar pipeline
echo "🏁 [9/10] A iniciar pipeline..."
export LOG_LEVEL=INFO

# Verificar se o script run_once.py existe
if [ -f "scripts/run_once.py" ]; then
    python3.12 scripts/run_once.py --stage full
    EXIT_CODE=$?

    if [ $EXIT_CODE -eq 0 ]; then
        echo ""
        echo "🎉 Pipeline executado com sucesso!"
    else
        echo ""
        echo "❌ Pipeline falhou com código de saída: $EXIT_CODE"
        exit $EXIT_CODE
    fi
else
    echo "❌ Erro: scripts/run_once.py não encontrado!"
    exit 1
fi

# Estatísticas
echo ""
echo "🏁 [10/10] calcular estatísticas..."
python3.12 scripts/stats_scores.py
python3.12 scripts/export_articles_dataset.py --db configs/vozdipovo.db --format both

echo ""
echo "✨ Pipeline concluído! ✨"
