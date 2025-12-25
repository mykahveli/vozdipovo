# src/vozdipovo_app/image_manager.py

import os
import random
import re
import shutil
from pathlib import Path
from typing import List, Optional, Set

import requests
from unidecode import unidecode

from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)

# --- CONFIGURAÇÃO ---
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parent.parent.parent
BASE_IMG_DIR = PROJECT_ROOT / "data" / "images"
STOCK_DIR = BASE_IMG_DIR / "stock"
DOWNLOAD_ROOT = BASE_IMG_DIR / "download"

# Garantir que as pastas existem
for p in [STOCK_DIR, DOWNLOAD_ROOT]:
    p.mkdir(parents=True, exist_ok=True)

# Stopwords (palavras a ignorar na busca)
STOPWORDS = {
    "de",
    "do",
    "da",
    "dos",
    "das",
    "a",
    "o",
    "e",
    "em",
    "para",
    "com",
    "no",
    "na",
    "nos",
    "nas",
    "ao",
    "aos",
    "por",
    "pelo",
    "pela",
    "um",
    "uma",
    "uns",
    "umas",
}

# --- FUNÇÕES UTILITÁRIAS ---


def normalize_text(text: str) -> str:
    """Simplifica texto para comparação (remove acentos, pontuação, lower)."""
    if not text:
        return ""
    # Remove acentos e converte para minúsculas
    text = unidecode(str(text).lower())
    # Mantém apenas letras, números e espaços
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    # Remove espaços múltiplos
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_keywords(text: str) -> List[str]:
    """Extrai palavras-chave relevantes de um texto."""
    normalized = normalize_text(text)
    words = normalized.split()

    # Filtra palavras muito comuns e curtas
    keywords = [w for w in words if len(w) > 2 and w not in STOPWORDS]

    return keywords


def download_image(url: str) -> str | None:
    """Baixa imagem de URL (usado para RSS)."""
    if not url:
        return None
    try:
        filename = normalize_text(url.split("/")[-1].split("?")[0]).replace(" ", "_")
        if len(filename) > 50:
            filename = filename[:50]
        if not filename.endswith((".jpg", ".png", ".webp")):
            filename += ".jpg"

        local_path = DOWNLOAD_ROOT / filename
        if local_path.exists() and local_path.stat().st_size > 0:
            return str(local_path)

        logger.info(f"🖼️ A baixar imagem: {url}")
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, stream=True, timeout=10)

        if res.status_code == 200:
            with open(local_path, "wb") as f:
                shutil.copyfileobj(res.raw, f)
            return str(local_path)
    except Exception as e:
        logger.error(f"Erro download imagem {url}: {e}")

    return None


# --- LÓGICA CORE DE SELEÇÃO ---


def find_best_match_simple(tags: List[str], article_title: str = "") -> Optional[str]:
    """
    Encontra a imagem mais relevante de forma SIMPLES.

    Lógica:
    1. Extrai keywords das tags + título
    2. Procura imagens cujos nomes/pastas contenham essas keywords
    3. Prioriza matches exatos, depois parciais

    Returns:
        Caminho absoluto da imagem ou None
    """
    # 1. Preparar termos de busca
    # Damos mais peso às tags, mas usamos o título para contexto extra
    all_text = " ".join(tags)
    if article_title:
        all_text += " " + article_title

    search_terms = extract_keywords(all_text)
    # Remove duplicados mantendo a ordem
    search_terms = list(dict.fromkeys(search_terms))

    if not search_terms:
        logger.warning("⚠️ Nenhum termo de busca válido extraído.")
        return None

    logger.info(f"🔎 Termos de busca: {search_terms}")

    # 2. Coletar todas as imagens do stock
    image_extensions = {".jpg", ".jpeg", ".png", ".webp"}
    all_images = []

    if STOCK_DIR.exists():
        for ext in image_extensions:
            # Procura recursivamente em todas as subpastas
            all_images.extend(STOCK_DIR.rglob(f"*{ext}"))
            all_images.extend(STOCK_DIR.rglob(f"*{ext.upper()}"))

    if not all_images:
        logger.error("❌ Nenhuma imagem encontrada na pasta stock.")
        return None

    # 3. Avaliar cada imagem
    scored_images = []

    for img_path in all_images:
        score = 0

        # Normalizar nome do arquivo e caminho relativo (para apanhar nomes de pastas)
        img_name = normalize_text(img_path.stem)
        # Ex: se o caminho for stock/seccoes/saude/hospital.jpg -> "seccoes saude hospital"
        img_path_str = normalize_text(str(img_path.relative_to(STOCK_DIR)))

        # PONTUAÇÃO SIMPLES:
        for term in search_terms:
            # A. Match no nome do arquivo (Prioridade Máxima)
            # Verifica se o termo existe como palavra isolada no nome
            if re.search(r"\b" + re.escape(term) + r"\b", img_name):
                score += 20
                # logger.debug(f"   ✓ Nome exato '{term}': {img_path.name} (+20)")
            elif term in img_name:
                score += 10
                # logger.debug(f"   ~ Nome parcial '{term}': {img_path.name} (+10)")

            # B. Match no caminho/pasta (Contexto)
            elif term in img_path_str:
                score += 5
                # logger.debug(f"   📂 Pasta '{term}': {img_path.parent.name} (+5)")

        if score > 0:
            scored_images.append((img_path, score))

    # 4. Selecionar vencedora
    if not scored_images:
        logger.warning(f"⚠️ Sem matches para: {search_terms}")
        # Tentar fallback para pasta default se existir
        default_dir = STOCK_DIR / "default"
        if default_dir.exists():
            defaults = list(default_dir.glob("*.*"))
            if defaults:
                chosen = random.choice(defaults)
                logger.info(f"🎲 Usando imagem default: {chosen.name}")
                return str(chosen)
        return None

    # Ordenar por score (maior para menor)
    scored_images.sort(key=lambda x: x[1], reverse=True)

    # Logs para debug
    logger.debug("🏆 Top Candidatas:")
    for i, (path, score) in enumerate(scored_images[:3], 1):
        logger.debug(f"  {i}. [{score} pts] {path.name}")

    # Escolher aleatoriamente entre as top 3 para variar
    # (Ou menos se houver menos de 3)
    top_n = scored_images[:3]
    chosen_path, chosen_score = random.choice(top_n)

    logger.info(f"✅ Selecionada: {chosen_path.name} ({chosen_score} pts)")

    return str(chosen_path)


# --- INTERFACE PÚBLICA (MANTÉM COMPATIBILIDADE) ---


def select_stock_image(
    keywords: str, subcategory: str, entity: str = "", randomize_top: int = 3
) -> str | None:
    """
    Função principal chamada pelo pipeline.
    Adapta os argumentos antigos para a nova lógica simplificada.
    Ignora 'randomize_top' pois a lógica interna já trata disso.
    """
    tags = []

    # Tratar keywords (string separada por vírgulas)
    if keywords:
        tags.extend([k.strip() for k in keywords.split(",")])

    # Tratar subcategoria (pode vir como lista ou string)
    if subcategory:
        if isinstance(subcategory, list):
            tags.extend(subcategory)
        else:
            tags.append(subcategory)

    # Adicionar entidade
    if entity:
        tags.append(entity)

    # Usamos o título vazio aqui porque o pipeline atual passa as keywords bem definidas
    return find_best_match_simple(tags, article_title="")


# --- TESTE RÁPIDO SE EXECUTADO DIRETAMENTE ---
if __name__ == "__main__":
    # Simulação do caso que reportaste
    test_tags = [
        "Administração Pública",
        "Assembleia Municipal",
        "Autarquias",
        "Orçamento",
        "Plano de Atividades",
        "Santa Catarina de Santiago",
    ]
    test_title = "Assembleia Municipal aprova Plano e Orçamento para 2026"

    print(f"🧪 Teste: {test_title}")
    result = find_best_match_simple(test_tags, test_title)
    print(f"🖼️ Resultado: {result}")
