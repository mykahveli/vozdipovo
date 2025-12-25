#!/bin/bash

# Script para configurar e executar o ambiente do projeto
# macOS compatible

clear

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

echo ""
echo "✨ Processo concluído! ✨"

python3.12 scripts/stats_scores.py
