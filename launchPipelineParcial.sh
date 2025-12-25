#!/usr/bin/env python3.12
# chmod +x launchPipelineRestante.sh
# python3.12 launchPipelineRestante.py 3
# Quantidade de loops no argumento
import subprocess
import sys

def main():
    if len(sys.argv) != 2:
        print("Uso: python run_loops.py <quantidade_de_loops>")
        print("Exemplo: python run_loops.py 5")
        sys.exit(1)

    try:
        loops = int(sys.argv[1])
        if loops <= 0:
            raise ValueError
    except ValueError:
        print("Erro: Por favor, forneça um número inteiro positivo")
        sys.exit(1)

    print(f"Executando {loops} loop(s) dos comandos...")

    commands = [
        ["python3.12", "scripts/run_once.py", "--stage", "judging"],
        ["python3.12", "scripts/run_once.py", "--stage", "generation"],
        ["python3.12", "scripts/run_once.py", "--stage", "revising"],
        ["python3.12", "scripts/run_once.py", "--stage", "publishing"],
        ["python3.12", "scripts/run_once.py", "--stage", "curation"],
        ["python3.12", "scripts/run_once.py", "--stage", "audio"]
    ]

    for i in range(loops):
        print(f"\n=== Loop {i+1}/{loops} ===")

        for cmd in commands:
            try:
                result = subprocess.run(cmd, check=True)
                if result.returncode != 0:
                    print(f"Erro ao executar: {' '.join(cmd)}")
                    sys.exit(1)
            except subprocess.CalledProcessError as e:
                print(f"Erro no processo: {e}")
                sys.exit(1)

    print(f"\nConcluído! {loops} loop(s) executados com sucesso.")

if __name__ == "__main__":
    main()
