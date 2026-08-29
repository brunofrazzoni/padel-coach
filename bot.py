"""
Coach Pádel Bot — Telegram + Whisper + Claude + Supabase
Stack: python-telegram-bot 21.6, anthropic, groq (whisper), supabase-py
"""

import os, json, logging, tempfile, re
from datetime import datetime
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.constants import ParseMode, ChatAction

import anthropic
from groq import Groq
from supabase import create_client

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── CLIENTES ──────────────────────────────────────────────────────────────────
claude    = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
groq      = Groq(api_key=os.environ["GROQ_API_KEY"])
supabase  = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

ALLOWED   = set(int(x) for x in os.environ.get("ALLOWED_USER_IDS","").split(",") if x.strip())

# ── ESTADO DE SESIÓN (en memoria — persiste mientras el bot corre) ────────────
# sessions[chat_id] = { "draft": {...}, "step": "waiting_input"|"confirming"|"done" }
sessions: dict = {}

# ── CATEGORÍAS CHILENAS (FEPACHI) ─────────────────────────────────────────────
# 6ta = principiante, 1ra = semiprofesional
CATEGORIAS = ["6ta", "5ta baja", "5ta", "5ta alta", "4ta baja", "4ta", "4ta alta",
               "3ra baja", "3ra", "3ra alta", "2da", "1ra"]

# Descripción de cada categoría para que Claude las entienda
CATEGORIAS_DESC = {
    "6ta":      "Principiante absoluto. Aprendiendo reglas, grip y golpes básicos.",
    "5ta baja": "Conoce las reglas. Saque inconsistente, evita el revés, no usa paredes.",
    "5ta":      "Golpes básicos funcionales. Saque con dobles faltas ocasionales. Posicionamiento elemental.",
    "5ta alta": "Consistencia básica. Participa en campeonatos de 5ta y algunos de 4ta con resultados variables.",
    "4ta baja": "Usa paredes con criterio. Globo defensivo funcional. Empieza a subir a la red.",
    "4ta":      "Rotaciones en pareja. Bandeja básica. Entiende cuándo subir y cuándo no.",
    "4ta alta": "Golpes con efecto incipientes. Construcción de puntos. Táctica de dobles sólida.",
    "3ra baja": "Víbora y bandeja con efecto. Ritmo más rápido. Torneos fuera de su ciudad.",
    "3ra":      "Todos los golpes. Tácticas para ganar. Complementa con entrenamiento físico.",
    "3ra alta": "Nivel competitivo sólido. Preparación física integrada. Consistencia en torneos.",
    "2da":      "Jugador avanzado. Gran variedad de golpes. Participa en selectivos regionales.",
    "1ra":      "Semiprofesional. Preparación física y mental completa. Selectivos nacionales.",
}

# ── CUESTIONARIO DE EVALUACIÓN INICIAL (Conecta-style) ───────────────────────
# Cada dimensión tiene 6 niveles (0–5). El índice corresponde al nivel dentro de esa dimensión.
# Se presentan de peor a mejor — el usuario elige la descripción que mejor lo representa.

EVAL_DIMENSIONES = [
    {
        "id": "anos_experiencia",
        "pregunta": "⏱ *¿Cuántos años llevas jugando pádel?*",
        "tipo": "opciones",
        "opciones": ["Menos de 6 meses", "6 meses – 1 año", "1–2 años", "2–4 años", "4–7 años", "Más de 7 años"],
        "valores": [0, 1, 2, 3, 4, 5],
    },
    {
        "id": "derecha",
        "pregunta": "🎾 *Derecha — elige la descripción que mejor te representa:*",
        "tipo": "opciones",
        "opciones": [
            "No consigo poner en juego más de 5 bolas seguidas",
            "Gesto incompleto, golpeo lento y sin control direccional",
            "Mantengo peloteos largos con velocidad moderada",
            "Buena consistencia y control direccional, desarrollando efectos",
            "Fiable, con buen control incluso en golpes defensivos",
            "Muy fiable, golpes rápidos y variados, preparando subida a red",
        ],
        "valores": [0, 1, 2, 3, 4, 5],
    },
    {
        "id": "reves",
        "pregunta": "🔄 *Revés — elige la descripción que mejor te representa:*",
        "tipo": "opciones",
        "opciones": [
            "No consigo poner en juego 5 bolas seguidas",
            "Evito golpear de revés, falta de control y golpeo tardío",
            "Preparación correcta, capaz de mantener peloteos de más de 5 bolas",
            "Control direccional consistente, velocidad moderada y efectos",
            "Controla dirección y profundidad, sufre en golpes muy difíciles",
            "Capaz de ser agresivo con control direccional también en defensa",
        ],
        "valores": [0, 1, 2, 3, 4, 5],
    },
    {
        "id": "servicio",
        "pregunta": "🎯 *Saque — elige la descripción que mejor te representa:*",
        "tipo": "opciones",
        "opciones": [
            "Cometo dobles faltas, golpeo lento y pasa muy alto",
            "Preparación incompleta, bote inconsistente, velocidad lenta",
            "Muchos fallos si busca potencia, segundo saque muy blando",
            "Comienza a sacar con control y cierta potencia",
            "Coloca primeros con potencia, control direccional en el segundo",
            "Con efectividad, busca punto débil, variedad y profundidad",
        ],
        "valores": [0, 1, 2, 3, 4, 5],
    },
    {
        "id": "volea",
        "pregunta": "🕸 *Volea — elige la descripción que mejor te representa:*",
        "tipo": "opciones",
        "opciones": [
            "Evito subir a la red, mala colocación y no impacto la bola",
            "Me siento incómodo en red, mala posición de espera",
            "Consistente ante golpes lentos, problemas con bolas bajas",
            "Control direccional en voleas altas",
            "Agresividad en voleas altas, desarrollando voleas bajas",
            "Golpea con profundidad y potencia buscando el punto débil",
        ],
        "valores": [0, 1, 2, 3, 4, 5],
    },
    {
        "id": "rebotes",
        "pregunta": "🪟 *Rebotes (paredes) — elige la descripción que mejor te representa:*",
        "tipo": "opciones",
        "opciones": [
            "No dejo rebotar ninguna bola porque no soy capaz de devolverla",
            "Permito rebotes pero mi colocación es mala",
            "Me coloco a buena distancia en bolas lentas",
            "Ante bolas lentas me coloco bien, en bolas fuertes me cuesta",
            "Buena salida ante bolas fuertes, desarrollando bajada de derecha",
            "Gano puntos respondiendo a rebotes fuertes con control",
        ],
        "valores": [0, 1, 2, 3, 4, 5],
    },
    {
        "id": "globos",
        "pregunta": "🎈 *Globo — elige la descripción que mejor te representa:*",
        "tipo": "opciones",
        "opciones": [
            "No realizo globos conscientemente",
            "Intento el globo pero se quedan cortos o muy largos",
            "Realizo globos intencionados pero con poco control",
            "Globo consistente para ganar la red",
            "Globo consistente ante bolas difíciles para defenderme",
            "Globo en los momentos adecuados, alternando con intentos por abajo",
        ],
        "valores": [0, 1, 2, 3, 4, 5],
    },
    {
        "id": "bolas_altas",
        "pregunta": "💥 *Bolas altas / remate / bandeja — elige la descripción:*",
        "tipo": "opciones",
        "opciones": [
            "Casi nunca subo a la red y rara vez golpeo una bola alta",
            "Ante bolas altas suelo retroceder para golpear tras el bote",
            "Intento rematar sin bote pero contacto tarde y se va al cristal",
            "Comienzo a leer el partido y desarrollo la bandeja",
            "Defino puntos regularmente con el remate, bandeja en progresión",
            "Golpeo por alto desde cualquier zona, saco la bola por 3 y 4",
        ],
        "valores": [0, 1, 2, 3, 4, 5],
    },
    {
        "id": "estilo_juego",
        "pregunta": "🧠 *Estilo de juego general — elige la descripción:*",
        "tipo": "opciones",
        "opciones": [
            "Acabo de empezar, trato de meter bolas sin control",
            "Juego de fondo, sin subir a la red ni usar rebotes en cristal",
            "Controlo posiciones básicas pero me coloco mal y llego tarde",
            "Consistente a velocidad moderada, empezando a compenetrarme con mi pareja",
            "Consistente en golpes, buen juego en equipo, a veces falta paciencia",
            "Varía su juego según el rival, bueno leyendo el partido, fortaleza mental",
        ],
        "valores": [0, 1, 2, 3, 4, 5],
    },
]

# Mapeo de score promedio (0–5) a categoría chilena
# Score 0–0.5 → 6ta, 0.5–1 → 5ta baja, ... 4.5–5 → 1ra
def score_a_categoria(score: float) -> str:
    umbrales = [
        (0.4,  "6ta"),
        (0.9,  "5ta baja"),
        (1.4,  "5ta"),
        (1.9,  "5ta alta"),
        (2.4,  "4ta baja"),
        (2.9,  "4ta"),
        (3.4,  "4ta alta"),
        (3.9,  "3ra baja"),
        (4.2,  "3ra"),
        (4.5,  "3ra alta"),
        (4.8,  "2da"),
        (5.0,  "1ra"),
    ]
    for umbral, cat in umbrales:
        if score <= umbral:
            return cat
    return "1ra"

# ── SUPABASE — PERFIL DE JUGADOR ─────────────────────────────────────────────

def obtener_perfil(user_id: int) -> dict | None:
    """Devuelve el perfil del jugador si existe, None si es primera vez."""
    try:
        resp = (supabase.table("jugadores")
                .select("*")
                .eq("user_id", str(user_id))
                .limit(1)
                .execute())
        return resp.data[0] if resp.data else None
    except Exception as e:
        log.error(f"Error obteniendo perfil: {e}")
        return None

def guardar_perfil(user_id: int, username: str, eval_data: dict, nivel_inicial: str) -> None:
    """Crea o actualiza el perfil del jugador con su evaluación inicial."""
    row = {
        "user_id":        str(user_id),
        "username":       username,
        "nivel_inicial":  nivel_inicial,
        "nivel_actual":   nivel_inicial,
        "eval_inicial":   json.dumps(eval_data, ensure_ascii=False),
        "fecha_eval":     datetime.utcnow().isoformat(),
        "partidos_total": 0,
    }
    # Upsert — crea si no existe, actualiza si ya existe
    supabase.table("jugadores").upsert(row, on_conflict="user_id").execute()

def actualizar_nivel_jugador(user_id: int, nuevo_nivel: str) -> None:
    """Actualiza el nivel actual del jugador después de cada partido."""
    try:
        supabase.table("jugadores").update({
            "nivel_actual": nuevo_nivel,
            "partidos_total": supabase.table("jugadores")
                .select("partidos_total")
                .eq("user_id", str(user_id))
                .execute().data[0].get("partidos_total", 0) + 1
        }).eq("user_id", str(user_id)).execute()
    except Exception as e:
        log.error(f"Error actualizando nivel: {e}")


# nivel_propio eliminado — el bot lo infiere del historial
CAMPOS = {
    "resultado":        "¿Cuál fue el resultado del partido? (ej. 6-4 / 4-6)",
    "nivel_rivales":    "¿En qué categoría jugaban los rivales? (ej. 5ta alta, 4ta baja)",
    "saque":            "Saque (0-10): efectividad y dirección",
    "devolucion":       "Devolución de saque (0-10)",
    "peloteo":          "Peloteo de fondo — consistencia (0-10)",
    "juego_red":        "Juego de red — volea y bandeja (0-10)",
    "globo":            "Globo defensivo — altura y profundidad (0-10)",
    "posicionamiento":  "Posicionamiento en pareja — rotaciones y centro (0-10)",
    "uso_red":          "Uso inteligente de la red — subir y mantener (0-10)",
    "construccion":     "Construcción del punto — sacar al rival de posición (0-10)",
    "gestion_marcador": "Gestión del marcador en momentos clave (0-10)",
    "ansiedad":         "Ansiedad pre-partido (0=tranquilo, 10=muy nervioso)",
    "foco":             "Foco durante el partido (0=distraído, 10=presente)",
    "gestion_errores":  "Gestión de errores (0=me afectaron, 10=los acepté y seguí)",
    "comunicacion":     "Comunicación con tu pareja (0=nula/negativa, 10=clara/positiva)",
}

CAMPOS_OPCIONALES = {
    "error_golpe":    "¿Qué golpe falló más? (opcional)",
    "golpe_bueno":    "¿Qué golpe fue más consistente? (opcional)",
    "error_tactico":  "¿Cuándo perdieron la red y por qué? (opcional)",
    "patron_bueno":   "¿Qué patrón táctico funcionó? (opcional)",
    "momento_presion":"¿En qué momento sentiste más presión? (opcional)",
    "dialogo_interno":"¿Qué pensaste tras un error clave? (opcional)",
    "em_bueno":       "¿Qué hiciste emocionalmente bien hoy? (opcional)",
}

ESCALAS_0_10 = {k for k in list(CAMPOS.keys())[2:]}  # todos excepto resultado y nivel_rivales

# ── HELPERS ───────────────────────────────────────────────────────────────────

def autorizado(user_id: int) -> bool:
    return not ALLOWED or user_id in ALLOWED

def get_session(chat_id: int) -> dict:
    if chat_id not in sessions:
        sessions[chat_id] = {"draft": {}, "step": "waiting_input", "pending_field": None}
    return sessions[chat_id]

def teclado_confirmacion(campo: str, opciones: list[str]) -> InlineKeyboardMarkup:
    """Genera teclado inline con opciones para un campo."""
    filas = []
    fila = []
    for i, op in enumerate(opciones):
        fila.append(InlineKeyboardButton(op, callback_data=f"set|{campo}|{op}"))
        if (i + 1) % 3 == 0:
            filas.append(fila)
            fila = []
    if fila:
        filas.append(fila)
    filas.append([InlineKeyboardButton("✏️ Escribir valor", callback_data=f"manual|{campo}")])
    return InlineKeyboardMarkup(filas)

def teclado_escala(campo: str) -> InlineKeyboardMarkup:
    """Teclado 0-10 para campos numéricos."""
    filas = [
        [InlineKeyboardButton(str(n), callback_data=f"set|{campo}|{n}") for n in range(0, 6)],
        [InlineKeyboardButton(str(n), callback_data=f"set|{campo}|{n}") for n in range(6, 11)],
    ]
    return InlineKeyboardMarkup(filas)

def teclado_categorias(campo: str) -> InlineKeyboardMarkup:
    """Teclado con las categorías chilenas para nivel de rivales."""
    filas = []
    # Mostrar de 6ta (más fácil) a 1ra, 2 por fila para que entren bien
    cats = list(reversed(CATEGORIAS))  # de 1ra a 6ta visualmente — invertimos para mostrar de menor a mayor
    cats = CATEGORIAS  # 6ta primero = más accesible
    for i in range(0, len(cats), 3):
        fila = [InlineKeyboardButton(c, callback_data=f"set|{campo}|{c}") for c in cats[i:i+3]]
        filas.append(fila)
    return InlineKeyboardMarkup(filas)

def teclado_confirmacion_final() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Analizar partido", callback_data="analizar"),
        InlineKeyboardButton("✏️ Corregir algo", callback_data="corregir"),
    ]])

def resumen_draft(draft: dict) -> str:
    """Texto con los datos actuales del borrador."""
    lines = ["*Datos del partido hasta ahora:*\n"]
    for campo, etiqueta in {**CAMPOS, **CAMPOS_OPCIONALES}.items():
        val = draft.get(campo)
        if val is not None:
            label = etiqueta.split("(")[0].strip().rstrip("—").strip()
            lines.append(f"• {label}: *{val}*")
    return "\n".join(lines)

# ── TRANSCRIPCIÓN ─────────────────────────────────────────────────────────────

async def transcribir_audio(file_bytes: bytes, suffix: str = ".ogg") -> str:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        with open(tmp_path, "rb") as f:
            result = groq.audio.transcriptions.create(
                model="whisper-large-v3-turbo",  # más rápido y preciso que whisper-1
                file=f,
                language="es",
                response_format="text",
            )
        return result
    finally:
        os.unlink(tmp_path)

# ── EXTRACCIÓN CON CLAUDE ─────────────────────────────────────────────────────

def extraer_datos_claude(texto: str, draft_actual: dict) -> dict:
    """
    Claude lee el texto del usuario y extrae todos los campos que pueda.
    Devuelve un dict con los campos encontrados.
    """
    campos_json = json.dumps({k: v for k, v in {**CAMPOS, **CAMPOS_OPCIONALES}.items()}, ensure_ascii=False, indent=2)
    draft_json  = json.dumps(draft_actual, ensure_ascii=False)

    categorias_validas = ", ".join(CATEGORIAS)

    prompt = f"""Eres un asistente extrayendo datos de un reporte post-partido de pádel.

CAMPOS QUE NECESITAS EXTRAER:
{campos_json}

DATOS YA RECOPILADOS (no los repitas):
{draft_json}

TEXTO DEL USUARIO:
"{texto}"

REGLAS DE EXTRACCIÓN:
- Para campos numéricos 0-10: convierte "bien"→7, "regular"→5, "mal"→3, "muy bien"→8, "excelente"→9, "pésimo"→2, "bastante bien"→8, "no tan bien"→4.
- Para "resultado": usa formato "X-Y / A-B" (ej. "6-4 / 3-6"). Si mencionan un solo set usa "X-Y".
- Para "nivel_rivales": mapea a una de estas categorías chilenas exactas: {categorias_validas}. Interpreta "cuarta" como "4ta", "quinta alta" como "5ta alta", etc.
- NUNCA extraigas "nivel_propio" — ese campo lo calcula el sistema, no el usuario.
- Solo incluye campos que hayas podido extraer con confianza. No inventes valores.

Responde SOLO con JSON.
Ejemplo: {{"resultado": "6-4 / 3-6", "nivel_rivales": "4ta baja", "saque": 7, "ansiedad": 4}}"""

    resp = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = resp.content[0].text.strip()
    clean = re.sub(r"```json|```", "", raw).strip()
    try:
        return json.loads(clean)
    except Exception:
        return {}

def analizar_con_claude(draft: dict, historial: list, nivel_inferido: str) -> dict:
    """Genera el análisis completo del partido, usando el nivel inferido por el bot."""

    hist_txt = ""
    if historial:
        hist_txt = "Historial reciente (más reciente primero):\n" + "\n".join(
            f"- {str(p.get('fecha','?'))[:10]}: resultado={p.get('resultado','?')} "
            f"T={p.get('score_tecnica','?')} TÁC={p.get('score_tactica','?')} EM={p.get('score_emocional','?')} "
            f"rivales={p.get('nivel_rivales','?')}"
            for p in historial[:5]
        )

    desc_nivel = CATEGORIAS_DESC.get(nivel_inferido, "")

    prompt = f"""Eres un coach de pádel experto con formación en psicología deportiva.

NIVEL ACTUAL DEL JUGADOR (inferido por el sistema): {nivel_inferido}
Descripción de este nivel: {desc_nivel}

DATOS DEL PARTIDO:
{json.dumps(draft, ensure_ascii=False, indent=2)}

{hist_txt}

INSTRUCCIONES IMPORTANTES:
- Todos tus consejos deben ser apropiados para un jugador de {nivel_inferido}.
- Los consejos técnicos/tácticos deben enfocarse en lo que corresponde a su nivel (no pidas víbora a un jugador de 5ta, ni solo trabajes el saque con uno de 3ra).
- Celebra progresos reales, no infles los logros.
- Si el nivel de los rivales fue más alto que el propio y el resultado fue competitivo o ganado, reconócelo explícitamente.

Responde SOLO con este JSON (sin markdown):
{{
  "score_tecnica": <promedio de saque+devolucion+peloteo+juego_red+globo, un decimal>,
  "score_tactica": <promedio de posicionamiento+uso_red+construccion+gestion_marcador, un decimal>,
  "score_emocional": <promedio de (10-ansiedad)+foco+gestion_errores+comunicacion dividido 4, un decimal>,
  "nivel_inferido": "{nivel_inferido}",
  "emoji_partido": "<un emoji representativo>",
  "resumen": "<2-3 frases directas del partido. Empieza con algo positivo real.>",
  "celebracion_tecnica": "<qué hizo bien técnicamente, específico para su nivel>",
  "celebracion_tactica": "<qué hizo bien tácticamente, específico>",
  "celebracion_emocional": "<celebra si fue bueno, sé honesto si fue malo>",
  "consejo_tecnico": "<UN consejo técnico accionable y apropiado para {nivel_inferido}>",
  "consejo_tactico": "<UN consejo táctico con ejercicio o frase clave>",
  "consejo_emocional": "<herramienta concreta: respiración, frase ancla, rutina>",
  "prioridad_semana": "<una frase: la prioridad #1 para entrenar esta semana>",
  "patron_detectado": "<si hay historial, comenta repeticiones buenas y malas. Si es el primero, dilo.>",
  "mensaje_nivel": "<una frase sobre su nivel actual y qué necesita para subir a la siguiente categoría>"
}}"""

    resp = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1400,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = resp.content[0].text.strip()
    clean = re.sub(r"```json|```", "", raw).strip()
    return json.loads(clean)

# ── SUPABASE ──────────────────────────────────────────────────────────────────

def guardar_partido(user_id: int, username: str, draft: dict, analysis: dict, nivel_inferido: str) -> None:
    row = {
        "user_id":         str(user_id),
        "username":        username,
        "fecha":           datetime.utcnow().isoformat(),
        "nivel_inferido":  nivel_inferido,
        "resultado":       draft.get("resultado"),
        "nivel_rivales":   draft.get("nivel_rivales"),
        "score_tecnica":   analysis.get("score_tecnica"),
        "score_tactica":   analysis.get("score_tactica"),
        "score_emocional": analysis.get("score_emocional"),
        "datos_raw":       json.dumps(draft, ensure_ascii=False),
        "analisis_raw":    json.dumps(analysis, ensure_ascii=False),
    }
    supabase.table("partidos").insert(row).execute()

def obtener_historial(user_id: int, limite: int = 10) -> list:
    resp = (supabase.table("partidos")
            .select("fecha,resultado,score_tecnica,score_tactica,score_emocional,nivel_inferido,nivel_rivales,datos_raw")
            .eq("user_id", str(user_id))
            .order("fecha", desc=True)
            .limit(limite)
            .execute())
    return resp.data or []

def inferir_nivel_claude(historial: list, perfil: dict | None) -> str:
    """
    Claude analiza el historial y ajusta el nivel desde el baseline del perfil.
    Si no hay historial suficiente, devuelve el nivel del perfil sin cambios.
    """
    nivel_base = (perfil or {}).get("nivel_actual", "6ta")

    if not historial:
        return nivel_base

    # Con menos de 3 partidos, ser conservador
    if len(historial) < 3:
        return nivel_base

    hist_lines = []
    for p in historial:
        datos = p.get("datos_raw") or {}
        if isinstance(datos, str):
            datos = json.loads(datos)
        hist_lines.append(
            f"- {str(p.get('fecha','?'))[:10]} | "
            f"resultado={p.get('resultado','?')} | "
            f"rivales={p.get('nivel_rivales','?')} | "
            f"T={p.get('score_tecnica','?')} TÁC={p.get('score_tactica','?')} EM={p.get('score_emocional','?')} | "
            f"nivel asignado={p.get('nivel_inferido', nivel_base)}"
        )

    categorias_desc = "\n".join(f"- {k}: {v}" for k, v in CATEGORIAS_DESC.items())

    prompt = f"""Eres un coach experto en pádel chileno. Debes ajustar la categoría del jugador.

NIVEL BASE (evaluación inicial): {nivel_base}
DESCRIPCIÓN: {CATEGORIAS_DESC.get(nivel_base, '')}

ESCALA COMPLETA:
{categorias_desc}

HISTORIAL ({len(historial)} partidos, más reciente primero):
{chr(10).join(hist_lines)}

REGLAS:
1. El nivel base viene de una evaluación técnica rigurosa — dale peso alto.
2. Sube una subcategoría si: score técnico+táctico promedio > 7 en los últimos 3 partidos Y resultados competitivos vs rivales de categoría similar o superior.
3. Baja una subcategoría si: score técnico+táctico promedio < 4 en los últimos 3 partidos Y pierde consistentemente vs rivales de su misma categoría.
4. Con menos de 5 partidos, solo sube/baja si la evidencia es muy clara.
5. No saltes más de una categoría por evaluación.

Responde SOLO con el nombre exacto de la categoría. Sin explicación."""

    resp = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=20,
        messages=[{"role": "user", "content": prompt}]
    )
    nivel = resp.content[0].text.strip().strip('"').strip("'")
    if nivel not in CATEGORIAS:
        for cat in CATEGORIAS:
            if cat.lower() in nivel.lower():
                return cat
        return nivel_base
    return nivel

# ── FORMATO DE ANÁLISIS PARA TELEGRAM ────────────────────────────────────────

def formatear_analisis(a: dict, draft: dict) -> str:
    st = a.get("score_tecnica", 0)
    sa = a.get("score_tactica", 0)
    se = a.get("score_emocional", 0)
    nivel = a.get("nivel_inferido", "—")

    def emoji_score(s):
        return "🟢" if s >= 7 else "🟡" if s >= 4.5 else "🔴"

    return f"""{a.get('emoji_partido','🎾')} *Resultado: {draft.get('resultado','—')}*
Tu nivel: *{nivel}* · Rivales: {draft.get('nivel_rivales','—')}

{emoji_score(st)} Técnica: *{st}/10* · {emoji_score(sa)} Táctica: *{sa}/10* · {emoji_score(se)} Emocional: *{se}/10*

─────────────────────
📋 *RESUMEN*
{a.get('resumen','')}

─────────────────────
🎉 *LO QUE HICISTE BIEN*

⚡ Técnica: {a.get('celebracion_tecnica','')}

🧠 Táctica: {a.get('celebracion_tactica','')}

💚 Emocional: {a.get('celebracion_emocional','')}

─────────────────────
🔧 *CÓMO MEJORAR*

🎾 Técnica: {a.get('consejo_tecnico','')}

🧩 Táctica: {a.get('consejo_tactico','')}

🧘 Emocional: {a.get('consejo_emocional','')}

─────────────────────
🎯 *PRIORIDAD #1 ESTA SEMANA*
_{a.get('prioridad_semana','')}_

─────────────────────
📊 *PATRÓN DETECTADO*
{a.get('patron_detectado','')}

─────────────────────
📈 *TU NIVEL ACTUAL: {nivel}*
{a.get('mensaje_nivel','')}"""

# ── FLUJO PRINCIPAL ───────────────────────────────────────────────────────────

async def pedir_siguiente_campo(chat_id: int, context: ContextTypes.DEFAULT_TYPE, session: dict) -> bool:
    """
    Busca el primer campo obligatorio sin completar y envía su teclado.
    Retorna True si había algo pendiente, False si todo está completo.
    """
    draft = session["draft"]
    for campo, etiqueta in CAMPOS.items():
        if draft.get(campo) is None:
            session["pending_field"] = campo
            session["step"] = "confirming"
            if campo == "nivel_rivales":
                kb = teclado_categorias(campo)
            elif campo in ESCALAS_0_10:
                kb = teclado_escala(campo)
            else:
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✏️ Escribir respuesta", callback_data=f"manual|{campo}")
                ]])
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❓ *{etiqueta}*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb
            )
            return True
    return False  # todos completos

async def mostrar_resumen_y_confirmar(chat_id: int, context: ContextTypes.DEFAULT_TYPE, session: dict):
    session["step"] = "ready"
    texto = resumen_draft(session["draft"])
    texto += "\n\n¿Todo correcto? Puedo analizar el partido ahora."
    await context.bot.send_message(
        chat_id=chat_id,
        text=texto,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=teclado_confirmacion_final()
    )

async def procesar_texto_libre(chat_id: int, user_id: int, username: str,
                                texto: str, context: ContextTypes.DEFAULT_TYPE):
    session = get_session(chat_id)

    # Si estamos esperando un campo manual específico
    if session["step"] == "waiting_manual" and session.get("pending_field"):
        campo = session["pending_field"]
        val   = texto.strip()
        if campo in ESCALAS_0_10:
            try:
                val = int(float(val))
                if not 0 <= val <= 10:
                    await context.bot.send_message(chat_id, "⚠️ Escribe un número entre 0 y 10.")
                    return
            except ValueError:
                await context.bot.send_message(chat_id, "⚠️ Necesito un número entre 0 y 10.")
                return
        session["draft"][campo] = val
        session["pending_field"] = None
        session["step"] = "waiting_input"
        await context.bot.send_message(chat_id, f"✅ Guardado.")
        faltan = await pedir_siguiente_campo(chat_id, context, session)
        if not faltan:
            await mostrar_resumen_y_confirmar(chat_id, context, session)
        return

    # Extracción libre con Claude
    await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
    extraido = extraer_datos_claude(texto, session["draft"])

    if extraido:
        session["draft"].update(extraido)
        campos_guardados = ", ".join(extraido.keys())
        await context.bot.send_message(chat_id, f"✅ Entendido. Guardé: _{campos_guardados}_",
                                       parse_mode=ParseMode.MARKDOWN)
    else:
        await context.bot.send_message(chat_id, "🤔 No pude extraer datos de eso. Intenta ser más específico.")

    # Verificar si faltan campos
    faltan = await pedir_siguiente_campo(chat_id, context, session)
    if not faltan:
        await mostrar_resumen_y_confirmar(chat_id, context, session)

# ── HANDLERS DE TELEGRAM ──────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not autorizado(update.effective_user.id):
        return
    user = update.effective_user
    perfil = obtener_perfil(user.id)

    if perfil:
        # Ya tiene perfil — ir directo al flujo de partido
        sessions[update.effective_chat.id] = {"draft": {}, "step": "waiting_input", "pending_field": None}
        nivel = perfil.get("nivel_actual", "—")
        partidos = perfil.get("partidos_total", 0)
        await update.message.reply_text(
            f"👋 Bienvenido de vuelta, {user.first_name}.\n\n"
            f"📊 Nivel actual: *{nivel}* · Partidos registrados: *{partidos}*\n\n"
            "Cuando termines un partido, cuéntame qué pasó — audio, texto, lo que quieras.\n\n"
            "Comandos: /nuevo · /resumen · /historial · /minivel",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        # Primera vez — lanzar evaluación inicial
        sessions[update.effective_chat.id] = {
            "draft": {}, "step": "evaluacion",
            "pending_field": None,
            "eval_idx": 0,          # índice de la dimensión actual
            "eval_data": {},        # respuestas del cuestionario
        }
        await update.message.reply_text(
            f"🎾 ¡Hola {user.first_name}! Soy tu *Coach de Pádel*.\n\n"
            "Antes de tu primer partido, necesito conocer tu nivel actual. "
            "Voy a hacerte *9 preguntas rápidas* — elige la opción que mejor te describe.\n\n"
            "Esto me permite darte consejos y análisis adaptados exactamente a dónde estás. "
            "Solo toma 2 minutos. 👇",
            parse_mode=ParseMode.MARKDOWN
        )
        await enviar_pregunta_evaluacion(update.effective_chat.id, context, 0)

async def enviar_pregunta_evaluacion(chat_id: int, context: ContextTypes.DEFAULT_TYPE, idx: int):
    """Envía la pregunta de evaluación número idx."""
    if idx >= len(EVAL_DIMENSIONES):
        # Evaluación completa
        await finalizar_evaluacion(chat_id, context)
        return

    dim = EVAL_DIMENSIONES[idx]
    total = len(EVAL_DIMENSIONES)
    progreso = f"_{idx + 1}/{total}_"

    # Construir teclado inline — una opción por fila para que quepan los textos
    filas = []
    for i, opcion in enumerate(dim["opciones"]):
        filas.append([InlineKeyboardButton(
            f"{'●' if i == 0 else '○'} {opcion[:55]}{'…' if len(opcion) > 55 else ''}",
            callback_data=f"eval|{dim['id']}|{dim['valores'][i]}"
        )])

    kb = InlineKeyboardMarkup(filas)
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"{progreso}\n\n{dim['pregunta']}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )

async def finalizar_evaluacion(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Calcula nivel inicial y crea el perfil en Supabase."""
    session = sessions.get(chat_id, {})
    eval_data = session.get("eval_data", {})
    user_data = session.get("_user", {})

    # Calcular score promedio (excluye años de experiencia del promedio técnico)
    dims_tecnicas = ["derecha", "reves", "servicio", "volea", "rebotes", "globos", "bolas_altas", "estilo_juego"]
    valores = [eval_data.get(d, 0) for d in dims_tecnicas]
    score_promedio = sum(valores) / len(valores) if valores else 0

    # Boost menor por años de experiencia (max +0.3)
    anos_score = eval_data.get("anos_experiencia", 0)
    boost = min(anos_score * 0.06, 0.3)
    score_final = min(score_promedio + boost, 5.0)

    nivel_inicial = score_a_categoria(score_final)

    # Guardar perfil
    try:
        guardar_perfil(
            user_id=user_data.get("id"),
            username=user_data.get("username", ""),
            eval_data=eval_data,
            nivel_inicial=nivel_inicial,
        )
    except Exception as e:
        log.error(f"Error guardando perfil: {e}")

    # Descripción de ese nivel
    desc = CATEGORIAS_DESC.get(nivel_inicial, "")

    # Resetear sesión para flujo normal de partido
    sessions[chat_id] = {"draft": {}, "step": "waiting_input", "pending_field": None}

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"✅ *Evaluación completa.*\n\n"
            f"📊 *Tu nivel inicial: {nivel_inicial}*\n"
            f"_{desc}_\n\n"
            f"Este es tu punto de partida. Con cada partido que registres, voy ajustando tu nivel "
            f"según tus resultados reales.\n\n"
            f"¡Listo! Cuando termines un partido, cuéntame qué pasó. "
            f"Puedes mandarme un audio, escribir o mezclar los dos. 🎾\n\n"
            f"─────────────────────\n"
            f"*Comandos disponibles:*\n"
            f"/nuevo — registrar un partido nuevo\n"
            f"/resumen — ver el análisis de tu último partido\n"
            f"/historial — tus últimos 5 partidos con scores\n"
            f"/minivel — tu nivel actual y progreso\n"
            f"/borrar — borrar la sesión en curso"
        ),
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_minivel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra el nivel actual inferido y el progreso."""
    if not autorizado(update.effective_user.id):
        return
    user_id = update.effective_user.id
    perfil = obtener_perfil(user_id)
    if not perfil:
        await update.message.reply_text("Aún no tienes perfil. Usa /start para crear uno.")
        return

    nivel_inicial = perfil.get("nivel_inicial", "—")
    nivel_actual  = perfil.get("nivel_actual", "—")
    partidos      = perfil.get("partidos_total", 0)
    desc_actual   = CATEGORIAS_DESC.get(nivel_actual, "")

    # Calcular posición en la escala
    idx_inicial = CATEGORIAS.index(nivel_inicial) if nivel_inicial in CATEGORIAS else 0
    idx_actual  = CATEGORIAS.index(nivel_actual)  if nivel_actual  in CATEGORIAS else 0
    subio = idx_actual - idx_inicial

    progreso_txt = ""
    if subio > 0:
        progreso_txt = f"📈 Has subido *{subio}* categoría(s) desde que empezaste."
    elif subio < 0:
        progreso_txt = f"📉 Has bajado *{abs(subio)}* categoría(s) desde tu evaluación inicial."
    else:
        progreso_txt = "➡️ Mismo nivel que al inicio — necesitas más partidos para ver progresión."

    # Siguiente categoría
    if idx_actual < len(CATEGORIAS) - 1:
        siguiente = CATEGORIAS[idx_actual + 1]
        desc_siguiente = CATEGORIAS_DESC.get(siguiente, "")
        siguiente_txt = f"\n\n🎯 *Para subir a {siguiente}:*\n_{desc_siguiente}_"
    else:
        siguiente_txt = "\n\n🏆 Estás en el nivel más alto del sistema."

    await update.message.reply_text(
        f"📊 *Tu nivel de pádel*\n\n"
        f"🏁 Nivel inicial: *{nivel_inicial}*\n"
        f"🎾 Nivel actual:  *{nivel_actual}*\n"
        f"📅 Partidos registrados: *{partidos}*\n\n"
        f"{progreso_txt}"
        f"{siguiente_txt}",
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_nuevo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not autorizado(update.effective_user.id):
        return
    sessions[update.effective_chat.id] = {"draft": {}, "step": "waiting_input", "pending_field": None}
    await update.message.reply_text("✅ Sesión reiniciada. Cuéntame del partido.")

async def cmd_borrar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not autorizado(update.effective_user.id):
        return
    sessions.pop(update.effective_chat.id, None)
    await update.message.reply_text("🗑 Sesión borrada.")

async def cmd_historial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not autorizado(update.effective_user.id):
        return
    user_id = update.effective_user.id
    partidos = obtener_historial(user_id, limite=5)
    if not partidos:
        await update.message.reply_text("Sin partidos registrados aún.")
        return
    lines = ["*Últimos partidos:*\n"]
    for p in partidos:
        fecha = p.get("fecha","?")[:10]
        lines.append(
            f"📅 {fecha} — {p.get('resultado','?')} · "
            f"T:{p.get('score_tecnica','?')} TÁC:{p.get('score_tactica','?')} EM:{p.get('score_emocional','?')}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

async def cmd_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not autorizado(update.effective_user.id):
        return
    user_id = update.effective_user.id
    partidos = obtener_historial(user_id, limite=1)
    if not partidos:
        await update.message.reply_text("Sin partidos registrados aún.")
        return
    p = partidos[0]
    analisis = json.loads(p.get("analisis_raw","{}"))
    draft    = json.loads(p.get("datos_raw","{}"))
    await update.message.reply_text(
        formatear_analisis(analisis, draft),
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not autorizado(update.effective_user.id):
        return
    user = update.effective_user
    await procesar_texto_libre(
        update.effective_chat.id, user.id, user.username or str(user.id),
        update.message.text, context
    )

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not autorizado(update.effective_user.id):
        return
    msg = update.message
    file_obj = msg.voice or msg.audio
    if not file_obj:
        return

    await msg.reply_text("🎙 Transcribiendo tu audio…")
    tg_file = await context.bot.get_file(file_obj.file_id)

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        await tg_file.download_to_drive(tmp.name)
        with open(tmp.name, "rb") as f:
            audio_bytes = f.read()
        os.unlink(tmp.name)

    transcripcion = await transcribir_audio(audio_bytes, ".ogg")
    await msg.reply_text(f"📝 _{transcripcion}_", parse_mode=ParseMode.MARKDOWN)

    user = update.effective_user
    await procesar_texto_libre(
        update.effective_chat.id, user.id, user.username or str(user.id),
        transcripcion, context
    )

async def handle_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not autorizado(update.effective_user.id):
        return
    await update.message.reply_text(
        "📸 Foto recibida. Por ahora analizo el partido con texto/audio. "
        "Si hay un marcador en la foto, escríbelo manualmente: ej. _6-4 / 4-6_",
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not autorizado(update.effective_user.id):
        return
    await update.message.reply_text(
        "🎥 Video recibido. Análisis de video automático coming soon. "
        "Por ahora cuéntame en audio o texto qué observaste."
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    user    = update.effective_user
    session = get_session(chat_id)
    data    = query.data

    # ── eval|dimension|valor — respuesta del cuestionario inicial ────────────
    if data.startswith("eval|"):
        _, dim_id, valor_str = data.split("|", 2)
        session.setdefault("eval_data", {})[dim_id] = int(valor_str)
        session.setdefault("_user", {}).update({"id": user.id, "username": user.username or str(user.id)})
        session["eval_idx"] = session.get("eval_idx", 0) + 1

        # Confirmar selección editando el mensaje
        dim = next((d for d in EVAL_DIMENSIONES if d["id"] == dim_id), None)
        if dim:
            idx_opcion = dim["valores"].index(int(valor_str))
            opcion_texto = dim["opciones"][idx_opcion]
            await query.edit_message_text(
                f"✅ _{opcion_texto[:80]}_",
                parse_mode=ParseMode.MARKDOWN
            )

        await enviar_pregunta_evaluacion(chat_id, context, session["eval_idx"])
        return

    # ── set|campo|valor ──────────────────────────────────────────────────────
    if data.startswith("set|"):
        _, campo, valor = data.split("|", 2)
        try:
            session["draft"][campo] = int(valor) if campo in ESCALAS_0_10 else valor
        except ValueError:
            session["draft"][campo] = valor
        session["pending_field"] = None
        session["step"] = "waiting_input"
        await query.edit_message_text(
            f"✅ *{campo.replace('_',' ').capitalize()}*: {valor}",
            parse_mode=ParseMode.MARKDOWN
        )
        faltan = await pedir_siguiente_campo(chat_id, context, session)
        if not faltan:
            await mostrar_resumen_y_confirmar(chat_id, context, session)

    # ── manual|campo ─────────────────────────────────────────────────────────
    elif data.startswith("manual|"):
        _, campo = data.split("|", 1)
        session["pending_field"] = campo
        session["step"] = "waiting_manual"
        etiqueta = CAMPOS.get(campo, CAMPOS_OPCIONALES.get(campo, campo))
        await query.edit_message_text(
            f"✏️ Escribe el valor para: *{etiqueta}*",
            parse_mode=ParseMode.MARKDOWN
        )

    # ── analizar ─────────────────────────────────────────────────────────────
    elif data == "analizar":
        await query.edit_message_text("⏳ Calculando tu nivel y analizando el partido…")
        draft     = session["draft"]
        historial = obtener_historial(user.id, limite=10)
        perfil    = obtener_perfil(user.id)

        # 1. Inferir nivel anclado en el perfil
        try:
            nivel_inferido = inferir_nivel_claude(historial, perfil)
        except Exception as e:
            log.error(f"Error inferencia nivel: {e}")
            nivel_inferido = (perfil or {}).get("nivel_actual", "5ta alta")

        # 2. Generar análisis
        try:
            analysis = analizar_con_claude(draft, historial, nivel_inferido)
        except Exception as e:
            log.error(f"Error Claude análisis: {e}")
            await context.bot.send_message(chat_id, f"❌ Error en el análisis: {e}")
            return

        # 3. Guardar partido
        try:
            guardar_partido(user.id, user.username or str(user.id), draft, analysis, nivel_inferido)
        except Exception as e:
            log.error(f"Error Supabase partidos: {e}")
            await context.bot.send_message(chat_id, "⚠️ Análisis listo pero no pude guardar el partido.")

        # 4. Actualizar nivel en perfil del jugador
        try:
            actualizar_nivel_jugador(user.id, nivel_inferido)
        except Exception as e:
            log.error(f"Error actualizando perfil: {e}")

        texto = formatear_analisis(analysis, draft)
        await context.bot.send_message(chat_id, texto, parse_mode=ParseMode.MARKDOWN)

        # Preguntas opcionales
        await context.bot.send_message(
            chat_id,
            "💬 *¿Querés agregar algo más?* (opcional)\n"
            "Podés contarme sobre errores específicos, momentos emocionales clave, "
            "o cualquier detalle del partido. También podés escribir /nuevo para el próximo.",
            parse_mode=ParseMode.MARKDOWN
        )
        sessions.pop(chat_id, None)

    # ── corregir ─────────────────────────────────────────────────────────────
    elif data == "corregir":
        await query.edit_message_text(
            "✏️ Dime qué querés corregir. Ej: _'el saque fue 8, no 6'_ o _'el resultado fue 6-3 / 6-4'_",
            parse_mode=ParseMode.MARKDOWN
        )
        session["step"] = "waiting_input"

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app   = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("nuevo",     cmd_nuevo))
    app.add_handler(CommandHandler("borrar",    cmd_borrar))
    app.add_handler(CommandHandler("historial", cmd_historial))
    app.add_handler(CommandHandler("resumen",   cmd_resumen))
    app.add_handler(CommandHandler("minivel",   cmd_minivel))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_texto))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO,   handle_audio))
    app.add_handler(MessageHandler(filters.PHOTO,                   handle_foto))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
    app.add_handler(CallbackQueryHandler(handle_callback))

    log.info("Bot iniciado.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()