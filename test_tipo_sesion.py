# -*- coding: utf-8 -*-
"""
Smoke test del router de intenciones, la taxonomía y el formato de salida.

Sólo ejercita funciones puras: los SDKs de red están stubbeados, así que no hace
falta ni conexión ni API keys reales. Ejecutar con:

    python test_tipo_sesion.py
"""
import os, sys, types

# Stubs de los SDKs de red: el smoke test sólo ejercita funciones puras.
_stub_anthropic = types.ModuleType("anthropic")
_stub_anthropic.Anthropic = lambda **kw: types.SimpleNamespace(messages=None)
sys.modules["anthropic"] = _stub_anthropic

_stub_groq = types.ModuleType("groq")
_stub_groq.Groq = lambda **kw: types.SimpleNamespace(audio=None)
sys.modules["groq"] = _stub_groq

_stub_supabase = types.ModuleType("supabase")
_stub_supabase.create_client = lambda url, key: types.SimpleNamespace(table=None)
sys.modules["supabase"] = _stub_supabase

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-dummy")
os.environ.setdefault("GROQ_API_KEY", "gsk-dummy")
os.environ.setdefault("SUPABASE_URL", "https://dummy.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "dummy-key")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "0:dummy")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot

fallos = []


def check(nombre, obtenido, esperado):
    ok = obtenido == esperado
    print(("  OK  " if ok else " FALLO") + " | %-52s -> %r" % (nombre, obtenido))
    if not ok:
        fallos.append("%s: esperaba %r, obtuvo %r" % (nombre, esperado, obtenido))


print("\n== campos y normalización ==")
check("normalizar_tipo(None)",           bot.normalizar_tipo(None), bot.TIPO_PARTIDO)
check("normalizar_tipo('basura')",       bot.normalizar_tipo("basura"), bot.TIPO_PARTIDO)
check("normalizar_tipo('entrenamiento')", bot.normalizar_tipo("entrenamiento"), bot.TIPO_ENTRENAMIENTO)
check("'resultado' en campos_de(partido)", "resultado" in bot.campos_de(bot.TIPO_PARTIDO), True)
check("'resultado' NO en campos entren.",  "resultado" in bot.campos_de(bot.TIPO_ENTRENAMIENTO), False)
check("'foco_sesion' en campos entren.",   "foco_sesion" in bot.campos_de(bot.TIPO_ENTRENAMIENTO), True)
check("'intensidad' en ESCALAS_0_10",      "intensidad" in bot.ESCALAS_0_10, True)
check("mínimos entrenamiento",
      bot.CAMPOS_MINIMOS_POR_TIPO[bot.TIPO_ENTRENAMIENTO],
      {"tipo_entrenamiento", "foco_sesion"})

print("\n== formato de salida ==")
analisis = {
    "score_tecnica": 7.2, "score_tactica": 6.0, "score_emocional": 8.0,
    "nivel_inferido": "5ta alta", "emoji_partido": "💪", "resumen": "Buena sesión.",
    "celebracion_tecnica": "a", "celebracion_tactica": "b", "celebracion_emocional": "c",
    "consejo_tecnico": "d", "consejo_tactico": "e", "consejo_emocional": "f",
    "prioridad_semana": "g", "patron_detectado": "h", "mensaje_nivel": "i",
}
draft_e = {"tipo_entrenamiento": "drills", "foco_sesion": "bandeja", "intensidad": 8}
draft_p = {"resultado": "6-4 / 3-6", "nivel_rivales": "4ta baja"}

msgs_e = bot.formatear_analisis(analisis, draft_e, bot.TIPO_ENTRENAMIENTO)
msgs_p = bot.formatear_analisis(analisis, draft_p, bot.TIPO_PARTIDO)
check("entrenamiento: 4 mensajes", len(msgs_e), 4)
check("entrenamiento: cabecera",   "Entrenamiento: bandeja" in msgs_e[0], True)
check("entrenamiento: intensidad", "Intensidad: 8/10" in msgs_e[0], True)
check("partido: cabecera",         "Resultado: 6-4 / 3-6" in msgs_p[0], True)
check("partido sin 'Entrenamiento'", "Entrenamiento" in msgs_p[0], False)

print("\n== resumen_draft y linea_historial ==")
r = bot.resumen_draft(draft_e, bot.TIPO_ENTRENAMIENTO)
check("resumen entrenamiento titula bien", "Datos del entrenamiento" in r, True)
check("resumen entrenamiento lista foco",  "bandeja" in r, True)

fila_e = {"fecha": "2026-08-30T10:00:00", "tipo_sesion": "entrenamiento",
          "datos_raw": '{"tipo_entrenamiento": "clase", "foco_sesion": "volea"}',
          "score_tecnica": 7, "score_tactica": 6, "score_emocional": 8}
fila_p = {"fecha": "2026-08-28T10:00:00", "tipo_sesion": "partido",
          "resultado": "6-2 / 6-4", "nivel_rivales": "5ta baja",
          "score_tecnica": 7, "score_tactica": 6, "score_emocional": 8}
check("linea_historial entrenamiento", "foco=volea" in bot.linea_historial(fila_e), True)
check("linea_historial partido",       "resultado=6-2 / 6-4" in bot.linea_historial(fila_p), True)
check("descriptor_sesion entrenamiento", bot.descriptor_sesion(fila_e), "volea")
check("descriptor_sesion partido",       bot.descriptor_sesion(fila_p), "6-2 / 6-4")
check("icono entrenamiento",             bot.icono_sesion(fila_e), "🏋️")

print("\n== inferir_nivel_claude ignora entrenamientos ==")
# Sólo entrenamientos en el historial -> devuelve el nivel base sin llamar a Claude
nivel = bot.inferir_nivel_claude([fila_e, fila_e, fila_e, fila_e],
                                 {"nivel_actual": "5ta alta"})
check("historial sólo entrenamientos -> nivel base", nivel, "5ta alta")

print("\n== teclados ==")
kb = bot.teclado_cambiar_tipo(bot.TIPO_PARTIDO)
check("botón cambia a entrenamiento",
      kb.inline_keyboard[0][0].callback_data, "set_tipo|entrenamiento")
kb2 = bot.teclado_confirmacion_final(bot.TIPO_ENTRENAMIENTO)
check("botón analizar entrenamiento",
      kb2.inline_keyboard[0][0].text, "✅ Analizar entrenamiento")
kb3 = bot.teclado_tipo_entrenamiento()
check("teclado tipo entrenamiento: 5 opciones + Otro",
      sum(len(f) for f in kb3.inline_keyboard), 6)

print("\n== taxonomía de intenciones ==")
check("13 intenciones declaradas", len(bot.INTENTS), 13)
check("las 5 que pidió el usuario están",
      {"registrar_partido", "registrar_entrenamiento", "consejo_tecnico",
       "consejo_tactico", "consejo_emocional"} <= set(bot.INTENTS), True)
check("registro mapea a tipo de sesión",
      bot.INTENTS_REGISTRO,
      {"registrar_partido": bot.TIPO_PARTIDO,
       "registrar_entrenamiento": bot.TIPO_ENTRENAMIENTO})
check("cada intención de consejo tiene categoría de conocimiento",
      sorted(c for c, _, _ in bot.CATEGORIAS_CONSEJO.values()),
      ["emocional", "táctica", "técnica"])
check("los consejos son intenciones válidas",
      set(bot.CATEGORIAS_CONSEJO) <= set(bot.INTENTS), True)
check("todo ejemplo del prompt apunta a una intención real",
      sorted({i for _, i in bot.EJEMPLOS_ROUTER} - set(bot.INTENTS)), [])
check("hay al menos un ejemplo por intención",
      sorted(set(bot.INTENTS) - {i for _, i in bot.EJEMPLOS_ROUTER}), [])

print("\n== no queda detección por texto ==")
for muerta in ("detectar_intent", "detectar_tipo_sesion", "intent_exacto",
               "FRASES_EXACTAS", "ENTRENAMIENTO_KW", "PARTIDO_KW", "RE_MARCADOR"):
    check("%s fue eliminada" % muerta, hasattr(bot, muerta), False)

print("\n== modelos ==")
check("todos los modelos por defecto son Haiku",
      {bot.MODELO_ROUTER, bot.MODELO_EXTRACCION, bot.MODELO_ANALISIS,
       bot.MODELO_CONSEJO, bot.MODELO_NIVEL},
      {"claude-haiku-4-5"})

print("\n== prompt del router ==")
p_sin = bot._prompt_router("ganamos 6-4")
p_con = bot._prompt_router("el saque fue 8", {"resultado": "6-4"}, bot.TIPO_PARTIDO)
check("sin borrador, avisa que corregir no aplica",
      '"corregir" no aplica' in p_sin, True)
check("con borrador, nombra los campos ya cargados",
      "resultado" in p_con and "registrando un partido" in p_con, True)
check("el mensaje del jugador va en el prompt", "ganamos 6-4" in p_sin, True)


class RespuestaFalsa:
    """Imita la forma de una respuesta de la Messages API."""
    def __init__(self, texto):
        self.content = [types.SimpleNamespace(text=texto)]


class ClaudeFalso:
    """Devuelve una respuesta por llamada; una excepción se relanza siempre."""
    def __init__(self, *respuestas, lanza=None):
        self.respuestas, self.lanza, self.llamadas = list(respuestas), lanza, 0
        self.modelos  = []
        self.messages = types.SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.llamadas += 1
        self.modelos.append(kw.get("model"))
        if self.lanza:
            raise self.lanza
        i = min(self.llamadas - 1, len(self.respuestas) - 1)
        return RespuestaFalsa(self.respuestas[i])


def con_claude(falso, *args, **kwargs):
    original = bot.claude
    bot.claude = falso
    try:
        return bot.clasificar_mensaje(*args, **kwargs)
    finally:
        bot.claude = original


print("\n== router: casos que rompían los keywords ==")
f = ClaudeFalso('{"intent": "registrar_partido"}')
r = con_claude(f, "hola, ganamos 6-4 6-2 contra los de 4ta")
check("saludo + reporte pegado -> registrar_partido",
      (r["intent"], r["via"], f.llamadas), ("registrar_partido", "claude:1", 1))
check("usa el modelo del router", f.modelos[0], bot.MODELO_ROUTER)

f = ClaudeFalso('```json\n{"intent": "consejo_tecnico"}\n```')
r = con_claude(f, "cómo le pego a la bandeja sin que se vaya larga")
check("JSON en fences de markdown se parsea", r["intent"], "consejo_tecnico")

f = ClaudeFalso('{"intent": "consulta_progreso"}')
r = con_claude(f, "he mejorado el saque estos meses")
check("pregunta sobre sus datos -> consulta_progreso", r["intent"], "consulta_progreso")

print("\n== router: reintento y fallo definitivo ==")
f = ClaudeFalso('{"intent": "no_existe"}', '{"intent": "consejo_emocional"}')
r = con_claude(f, "me pongo nervioso en los puntos importantes")
check("intent inválido -> reintenta y acierta",
      (r["intent"], r["via"], f.llamadas), ("consejo_emocional", "claude:2", 2))

f = ClaudeFalso(lanza=RuntimeError("503 upstream"))
r = con_claude(f, "ganamos 6-3")
check("excepción en ambos intentos -> intent None",
      (r["intent"], r["via"], f.llamadas), (None, "error", 2))

f = ClaudeFalso('no soy json', 'tampoco soy json')
r = con_claude(f, "cualquier cosa")
check("respuesta no-JSON dos veces -> intent None", r["intent"], None)

f = ClaudeFalso('{"intent": "chachacha"}', '{"intent": "otra_invencion"}')
r = con_claude(f, "cualquier cosa")
check("intent inválido dos veces -> intent None (sin adivinar)", r["intent"], None)

print("\n" + ("TODO OK" if not fallos else "FALLOS:\n" + "\n".join(fallos)))
sys.exit(1 if fallos else 0)
