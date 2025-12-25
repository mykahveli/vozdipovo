#!filepath: src/vozdipovo_app/audio_generator.py
from __future__ import annotations

import asyncio
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import edge_tts
import nest_asyncio
from pydub import AudioSegment

from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)
nest_asyncio.apply()

AudioSegment.converter = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
AudioSegment.ffprobe = shutil.which("ffprobe") or "/usr/bin/ffprobe"


@dataclass(frozen=True, slots=True)
class AudioConfig:
    """Audio generation configuration."""

    voice: str = "pt-PT-RaquelNeural"


def _formatar_moeda_para_leitura(match: re.Match[str]) -> str:
    numero_str = match.group(1).replace(".", "").replace(",", "")
    try:
        numero = int(numero_str)
        if numero >= 1_000_000_000:
            valor = numero / 1_000_000_000
            unidade = "biliões de" if valor > 1 else "bilião de"
            valor_str = f"{valor:.3f}".rstrip("0").rstrip(".")
            return f"{valor_str} {unidade} escudos"
        if numero >= 1_000_000:
            valor = numero / 1_000_000
            unidade = "milhões de" if valor > 1 else "milhão de"
            valor_str = f"{valor:.3f}".rstrip("0").rstrip(".")
            return f"{valor_str} {unidade} escudos"
        if numero >= 1_000:
            valor = numero / 1_000
            valor_str = f"{valor:.3f}".rstrip("0").rstrip(".")
            return f"{valor_str} mil escudos"
        return f"{numero_str} escudos"
    except (ValueError, TypeError):
        return match.group(0)


def _limpar_texto_para_tts(texto: str) -> str:
    if not texto:
        return ""

    texto_limpo = re.sub(r"([\d\.,\s]+)\$(\d{2})", _formatar_moeda_para_leitura, texto)
    substituicoes = {
        "n.º": "número",
        "art.º": "artigo",
        "p. ex.": "por exemplo",
        "S.A.": "S A",
        "Lda.": "Limitada",
        "Dr.": "Doutor",
        "Dra.": "Doutora",
        "Eng.": "Engenheiro",
    }
    for abrev, expansao in substituicoes.items():
        texto_limpo = texto_limpo.replace(abrev, expansao)

    texto_limpo = texto_limpo.replace("\n", " . ")
    texto_limpo = re.sub(r"[\*#_]", "", texto_limpo)
    texto_limpo = re.sub(r"\s+", " ", texto_limpo).strip()
    return texto_limpo


async def _gerar_audio_edge(texto: str, ficheiro_saida: str, voice: str) -> bool:
    try:
        communicate = edge_tts.Communicate(texto, voice)
        await communicate.save(ficheiro_saida)
        return True
    except Exception as e:
        logger.error(f"Erro interno EdgeTTS: {e}")
        return False


def gerar_audio_para_artigo(
    texto_do_artigo: str,
    diretorio_output: str,
    nome_ficheiro: str,
    cfg: Optional[AudioConfig] = None,
) -> Optional[str]:
    texto_limpo = _limpar_texto_para_tts(texto_do_artigo)
    if not texto_limpo:
        logger.warning("Texto para geração de áudio está vazio após limpeza.")
        return None

    audio_cfg = cfg or AudioConfig()

    try:
        output_path = Path(diretorio_output)
        output_path.mkdir(parents=True, exist_ok=True)
        caminho_final = output_path / f"{nome_ficheiro}.mp3"

        ok = asyncio.run(
            _gerar_audio_edge(texto_limpo, str(caminho_final), audio_cfg.voice)
        )
        if not ok:
            return None

        if caminho_final.exists() and caminho_final.stat().st_size > 0:
            return str(caminho_final)
        logger.error("Ficheiro de áudio não foi criado corretamente.")
        return None
    except Exception as e:
        logger.error(f"Erro fatal ao gerar áudio para '{nome_ficheiro}': {e}")
        return None
