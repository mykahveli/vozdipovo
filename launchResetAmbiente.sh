#!/bin/bash
# launchResetAmbiente.sh

clear

echo "🧹 [1/5] Limpando ambiente anterior..."
rm -rf .venv
rm -rf src/vozdipovo_app.egg-info
rm -rf build
rm -rf dist
find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null
find . -name '*.pyc' -delete
find . -name '._*' -type f -delete

echo "🐍 [2/5] Configurando Python 3.12..."
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

echo "🔧 [3/5] Criando ambiente virtual..."
python -m venv .venv --clear

# ATIVAR o ambiente de forma explícita
source .venv/bin/activate

# Verificar que estamos no ambiente correto
echo "Python sendo usado: $(which python)"
echo "Pip sendo usado: $(which pip)"

echo "📦 [4/5] Atualizando pip e instalando dependências..."
python -m pip install --upgrade pip setuptools wheel

# Instalar o projeto em modo desenvolvimento
echo "Instalando projeto e dependências..."
pip install -e .

# Verificar instalação específica do PyYAML
echo "Verificando PyYAML..."
pip show pyyaml || pip install pyyaml

echo "✅ [5/5] Ambiente configurado com sucesso!"
echo ""
echo "Para ativar manualmente:"
echo "source .venv/bin/activate"
echo ""
echo "Versões instaladas:"
python --version
pip list | grep -E "(pyyaml|setuptools|pip)"
