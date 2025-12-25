#!/usr/bin/env python3
import os
import sys
import time

# Adiciona o diretório src ao path para importar os módulos
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

from vozdipovo_app.config import load_app_config
from vozdipovo_app.wordpress.client import WPClient, WPConfig


def get_json_data(response):
    """Helper para extrair dados independentemente da versão do WPClient."""
    # Se já for um dicionário ou lista, devolve direto
    if isinstance(response, (dict, list)):
        return response
    # Se for um objeto Response do requests, extrai o .json()
    if hasattr(response, "json"):
        return response.json()
    return response


def reset_wordpress():
    print("⚠️  ATENÇÃO: LIMPEZA DO WORDPRESS ⚠️")
    print("------------------------------------")
    print("1. Apagar TODOS os posts do Bot")
    print("2. Apagar TODAS as imagens do Bot")
    print("3. Apagar TODAS as tags")
    print("4. MANTER todas as categorias")
    print("------------------------------------")

    try:
        # Carregar configurações
        cfg = load_app_config()
        wpcfg = WPConfig(
            base_url=cfg["wordpress"]["base_url"],
            username=cfg["wordpress"]["username"],
            app_password=cfg["wordpress"]["app_password"],
        )
        client = WPClient(wpcfg)

        # 1. Verificar identidade
        print("🔍 A verificar autenticação...")
        # O cliente atual lança exceção se falhar, por isso não precisamos ver status_code
        me_response = client.get("/wp-json/wp/v2/users/me")
        user_data = get_json_data(me_response)

        author_id = user_data.get("id")
        if not author_id:
            print("❌ Não foi possível obter o ID do utilizador.")
            return

        print(f"🤖 Identificado como: {user_data.get('name')} (ID: {author_id})")

        # --- APAGAR POSTS ---
        print(f"\n🗑️  A apagar POSTS do utilizador {user_data.get('name')}...")
        deleted_posts = 0
        while True:
            # Pede posts (status=any apanha rascunhos, publicados, lixo, etc.)
            posts_response = client.get(
                f"/wp-json/wp/v2/posts?author={author_id}&per_page=50&status=any"
            )
            posts_data = get_json_data(posts_response)

            if not posts_data:
                break

            for post in posts_data:
                pid = post["id"]
                title = post.get("title", {}).get("rendered", "(sem título)")
                print(f"   [Delete] Post {pid}: {title[:40]}...")

                # force=true apaga permanentemente (ignora lixeira)
                # Aqui usamos client.s (sessão) para ter acesso ao delete cru
                client.s.delete(
                    f"{wpcfg.base_url}/wp-json/wp/v2/posts/{pid}?force=true"
                )
                deleted_posts += 1

        print(f"✅ Posts apagados: {deleted_posts}")

        # --- APAGAR MEDIA (IMAGENS) ---
        # Importante: Só apagamos media que pertença ao autor (bot) para não apagar logo do site inteiro
        print(f"\n🖼️  A apagar MEDIA/IMAGENS do utilizador {user_data.get('name')}...")
        deleted_media = 0
        while True:
            media_response = client.get(
                f"/wp-json/wp/v2/media?author={author_id}&per_page=50"
            )
            media_data = get_json_data(media_response)

            if not media_data:
                break

            for item in media_data:
                mid = item["id"]
                slug = item.get("slug", str(mid))
                print(f"   [Delete] Imagem {mid}: {slug}")

                # force=true é essencial para apagar o ficheiro do disco do servidor
                client.s.delete(
                    f"{wpcfg.base_url}/wp-json/wp/v2/media/{mid}?force=true"
                )
                deleted_media += 1

        print(f"✅ Imagens apagadas: {deleted_media}")

        # --- APAGAR TAGS ---
        print("\n🏷️  A apagar TODAS as TAGS...")
        deleted_tags = 0
        while True:
            tags_response = client.get("/wp-json/wp/v2/tags?per_page=50")
            tags_data = get_json_data(tags_response)

            if not tags_data:
                break

            for tag in tags_data:
                tid = tag["id"]
                print(f"   [Delete] Tag {tid}: {tag['name']}")
                client.s.delete(f"{wpcfg.base_url}/wp-json/wp/v2/tags/{tid}?force=true")
                deleted_tags += 1

        print(f"✅ Tags apagadas: {deleted_tags}")

        # --- CATEGORIAS ---
        print("\n📂 Categorias: Mantidas (Ignoradas por segurança).")

        print("\n✨ Limpeza Concluída! ✨")

    except Exception as e:
        print(f"\n❌ Erro crítico durante a limpeza: {e}")


if __name__ == "__main__":
    # Pausa de segurança de 2 segundos
    print("A iniciar em 2 segundos...")
    time.sleep(2)
    reset_wordpress()
