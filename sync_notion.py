"""
sync_notion.py — Sincroniza la base de conocimiento de Notion → Supabase
Ejecutar manualmente o como cron en Railway.

Uso:
    python sync_notion.py

Variables de entorno requeridas:
    NOTION_TOKEN       — token de integración (ntn_...)
    NOTION_DB_ID       — ID de la base de datos de Notion
    SUPABASE_URL
    SUPABASE_KEY
"""

import os, json, logging
from datetime import datetime
import httpx
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DB_ID = os.environ.get("NOTION_DB_ID", "3cbcc5b1585380129610fa527cc98995")
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

NOTION_HEADERS = {
    "Authorization":  f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type":   "application/json",
}

# ── HELPERS NOTION ────────────────────────────────────────────────────────────

def get_text(prop: dict) -> str:
    """Extrae texto de una propiedad rich_text o title."""
    tipo = prop.get("type")
    if tipo == "title":
        items = prop.get("title", [])
    elif tipo == "rich_text":
        items = prop.get("rich_text", [])
    else:
        return ""
    return "".join(t.get("plain_text", "") for t in items).strip()

def get_select(prop: dict) -> str:
    """Extrae valor de una propiedad select."""
    sel = prop.get("select") or {}
    return sel.get("name", "").strip().lower()

def get_url(prop: dict) -> str:
    """Extrae URL."""
    return (prop.get("url") or "").strip()

def get_checkbox(prop: dict) -> bool:
    """Extrae checkbox."""
    return bool(prop.get("checkbox", True))

def extraer_contenido_bloques(page_id: str) -> str:
    """
    Lee los bloques hijo de una página Notion y extrae el texto completo.
    Útil cuando el contenido está en el cuerpo de la página, no solo en propiedades.
    """
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    try:
        resp = httpx.get(url, headers=NOTION_HEADERS, timeout=10)
        resp.raise_for_status()
        bloques = resp.json().get("results", [])
    except Exception as e:
        log.warning(f"No pude leer bloques de {page_id}: {e}")
        return ""

    textos = []
    for bloque in bloques:
        tipo = bloque.get("type", "")
        contenido_bloque = bloque.get(tipo, {})
        rich = contenido_bloque.get("rich_text", [])
        texto = "".join(t.get("plain_text", "") for t in rich).strip()
        if texto:
            textos.append(texto)

    return "\n".join(textos)

# ── FETCH NOTION ──────────────────────────────────────────────────────────────

def fetch_notion_pages() -> list:
    """Trae todas las páginas activas de la base de Notion."""
    url    = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query"
    pages  = []
    cursor = None

    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor

        resp = httpx.post(url, headers=NOTION_HEADERS, json=body, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        pages.extend(data.get("results", []))

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    log.info(f"Notion: {len(pages)} páginas encontradas")
    return pages

def parsear_pagina(page: dict) -> dict | None:
    """Convierte una página de Notion en un dict listo para Supabase."""
    props = page.get("properties", {})
    page_id = page["id"].replace("-", "")

    # Campo activo — si no existe la propiedad, asumir True
    activo = get_checkbox(props.get("activo", {"type": "checkbox", "checkbox": True}))
    if not activo:
        return None  # saltar entradas desactivadas

    # Título obligatorio
    titulo = get_text(props.get("titulo", props.get("Título", props.get("Name", {}))))
    if not titulo:
        log.warning(f"Página {page_id} sin título — saltando")
        return None

    # Contenido: primero la propiedad, luego los bloques del cuerpo
    contenido = get_text(props.get("contenido", props.get("Contenido", {})))
    if not contenido:
        contenido = extraer_contenido_bloques(page["id"])

    return {
        "notion_id":      page_id,
        "titulo":         titulo,
        "categoria":      get_select(props.get("categoria",       props.get("Categoría", {}))),
        "nivel_objetivo": get_select(props.get("nivel_objetivo",  props.get("Nivel objetivo", {}))),
        "golpe":          get_select(props.get("golpe",           props.get("Golpe", {}))),
        "contenido":      contenido,
        "frase_coach":    get_text(props.get("frase_coach",       props.get("Frase coach", {}))),
        "media_url":      get_url(props.get("media_url",          props.get("Media URL", {}))),
        "activo":         True,
        "ultima_sync":    datetime.utcnow().isoformat(),
    }

# ── SYNC → SUPABASE ───────────────────────────────────────────────────────────

def sync():
    log.info("Iniciando sync Notion → Supabase...")
    pages   = fetch_notion_pages()
    ok = err = skip = 0

    for page in pages:
        row = parsear_pagina(page)
        if row is None:
            skip += 1
            continue
        try:
            supabase.table("conocimiento_padel").upsert(
                row, on_conflict="notion_id"
            ).execute()
            ok += 1
            log.info(f"  ✅ {row['titulo']}")
        except Exception as e:
            err += 1
            log.error(f"  ❌ {row.get('titulo','?')}: {e}")

    # Desactivar en Supabase entradas que ya no están en Notion
    notion_ids = [
        page["id"].replace("-", "")
        for page in pages
    ]
    if notion_ids:
        supabase.table("conocimiento_padel").update(
            {"activo": False}
        ).not_.in_("notion_id", notion_ids).execute()

    log.info(f"Sync completo: {ok} ok · {skip} saltadas · {err} errores")
    return ok, err

if __name__ == "__main__":
    sync()
