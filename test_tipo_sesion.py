# -*- coding: utf-8 -*-
"""
Smoke test de la detección partido vs entrenamiento y del formato de salida.

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


print("\n== detectar_tipo_sesion ==")
casos = [
    ("Ganamos 6-4 6-2 contra rivales de 4ta",                 bot.TIPO_PARTIDO),
    ("Perdimos el partido, los rivales jugaban muy bien",      bot.TIPO_PARTIDO),
    ("Jugamos un americano el sábado",                         bot.TIPO_PARTIDO),
    ("Entrené una hora de bandeja con el profe",               bot.TIPO_ENTRENAMIENTO),
    ("Hicimos drills de salida de pared y canasta",            bot.TIPO_ENTRENAMIENTO),
    ("Clase con el entrenador, mucho ejercicio de volea",      bot.TIPO_ENTRENAMIENTO),
    ("Practicamos sparring toda la tarde",                     bot.TIPO_ENTRENAMIENTO),
    # Mixtos / ambiguos -> None, decide Claude
    ("Entrenamos y después jugamos un partido 6-3",            None),
    ("Estuvo todo bien menos el saque",                        None),
    ("Igual que siempre",                                      None),
]
for texto, esperado in casos:
    check(repr(texto)[:50], bot.detectar_tipo_sesion(texto), esperado)

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

print("\n== router: fast path por coincidencia exacta ==")
check("'Hola!' normaliza y matchea",     bot.intent_exacto("Hola!"),  ("saludo", None))
check("'  cómo voy  ' matchea",          bot.intent_exacto("  cómo voy  "), ("minivel", None))
check("'nuevo entrenamiento' trae tipo", bot.intent_exacto("nuevo entrenamiento"),
      ("nuevo", bot.TIPO_ENTRENAMIENTO))
check("'hola, ganamos 6-4' NO es exacto", bot.intent_exacto("hola, ganamos 6-4"), None)
check("'cómo voy con la bandeja' NO es exacto",
      bot.intent_exacto("cómo voy con la bandeja"), None)


class RespuestaFalsa:
    """Imita la forma de una respuesta de la Messages API."""
    def __init__(self, texto):
        self.content = [types.SimpleNamespace(text=texto)]


class ClaudeFalso:
    """Cuenta llamadas y devuelve (o lanza) lo que se le indique."""
    def __init__(self, devuelve=None, lanza=None):
        self.devuelve, self.lanza, self.llamadas = devuelve, lanza, 0
        self.messages = types.SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.llamadas += 1
        self.modelo = kw.get("model")
        if self.lanza:
            raise self.lanza
        return RespuestaFalsa(self.devuelve)


def con_claude(falso, *args, **kwargs):
    original = bot.claude
    bot.claude = falso
    try:
        return bot.clasificar_mensaje(*args, **kwargs)
    finally:
        bot.claude = original


print("\n== router: no gasta API en el fast path ==")
f = ClaudeFalso(devuelve='{"intent":"reporte","tipo_sesion":null}')
r = con_claude(f, "hola")
check("'hola' se resuelve sin llamar a la API", (r["intent"], r["via"], f.llamadas),
      ("saludo", "exacto", 0))

print("\n== router: los casos que rompían los keywords ==")
f = ClaudeFalso(devuelve='{"intent": "reporte", "tipo_sesion": "partido"}')
r = con_claude(f, "hola, ganamos 6-4 6-2 contra los de 4ta")
check("saludo + reporte pegado -> reporte",
      (r["intent"], r["tipo_sesion"], r["via"]), ("reporte", "partido", "claude"))
check("usa el modelo router", f.modelo, bot.MODELO_ROUTER)

f = ClaudeFalso(devuelve='```json\n{"intent": "consulta_tecnica", "tipo_sesion": null}\n```')
r = con_claude(f, "cómo voy con la bandeja, siento que no mejoro")
check("JSON envuelto en markdown se parsea",
      (r["intent"], r["tipo_sesion"]), ("consulta_tecnica", None))

print("\n== router: respaldo cuando el modelo falla ==")
f = ClaudeFalso(lanza=RuntimeError("503 upstream"))
r = con_claude(f, "ganamos 6-3 6-4, el saque muy bien")
check("excepción -> keywords, sin romper",
      (r["intent"], r["tipo_sesion"], r["via"]), ("reporte", "partido", "fallback"))

f = ClaudeFalso(devuelve='{"intent": "chachacha", "tipo_sesion": "partido"}')
r = con_claude(f, "entrené drills de volea con el profe")
check("intent inválido -> keywords",
      (r["intent"], r["tipo_sesion"], r["via"]), ("reporte", "entrenamiento", "fallback"))

f = ClaudeFalso(devuelve='no soy json')
r = con_claude(f, "hola qué tal todo bien")
check("respuesta no-JSON -> keywords", r["via"], "fallback")

f = ClaudeFalso(devuelve='{"intent": "reporte", "tipo_sesion": "basura"}')
r = con_claude(f, "jugamos ayer")
check("tipo_sesion inválido se descarta",
      (r["intent"], r["tipo_sesion"]), ("reporte", None))

print("\n== router: contexto de borrador en curso ==")
f = ClaudeFalso(devuelve='{"intent": "reporte", "tipo_sesion": null}')
r = con_claude(f, "el saque fue 8", {"resultado": "6-4"}, bot.TIPO_PARTIDO)
check("corrección con draft abierto -> reporte", r["intent"], "reporte")

print("\n" + ("TODO OK" if not fallos else "FALLOS:\n" + "\n".join(fallos)))
sys.exit(1 if fallos else 0)
