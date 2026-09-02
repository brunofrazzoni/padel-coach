# Coach Pádel Bot — Setup completo

## Stack
- **Telegram Bot** — interfaz conversacional
- **OpenAI Whisper** — transcripción de audios ($0.006/min)
- **Claude Sonnet** — extracción de datos + análisis
- **Supabase** — base de datos (plan gratuito)
- **Railway** — hosting del bot (~$5/mes o gratis con límites)

---

## Paso 1 — Crear el bot en Telegram

1. Abre Telegram → busca `@BotFather`
2. Envía `/newbot`
3. Elige nombre (ej. "Coach Pádel") y username (ej. `micoachpadel_bot`)
4. Guarda el token que te da (ej. `7123456789:AAF...`)

Para obtener tu Telegram user ID:
- Busca `@userinfobot` en Telegram y escríbele. Te responde con tu ID numérico.
- Haz lo mismo con tu pareja de juego.

---

## Paso 2 — Supabase

1. Entra a [supabase.com](https://supabase.com) → tu proyecto
2. Ve a **SQL Editor** → **New Query**
3. Pega el contenido de `supabase_schema.sql` → **Run**
4. Ve a **Settings → API** y copia:
   - `Project URL` → es tu `SUPABASE_URL`
   - `anon public` key → es tu `SUPABASE_KEY`

---

## Paso 3 — APIs

**OpenAI (para Whisper):**
- [platform.openai.com](https://platform.openai.com) → API Keys → Create new key
- Costo estimado: un audio de 3 min = ~$0.02

**Anthropic (Claude):**
- [console.anthropic.com](https://console.anthropic.com) → API Keys

---

## Paso 4 — Variables de entorno

Crea un archivo `.env` (copia `.env.example` y completa):

```
TELEGRAM_BOT_TOKEN=7123456789:AAF...
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_KEY=eyJ...
ALLOWED_USER_IDS=123456789,987654321
```

---

## Paso 5 — Deploy en Railway

1. Crea cuenta en [railway.app](https://railway.app)
2. **New Project → Deploy from GitHub repo** (sube este código a un repo privado)
   - O bien: **New Project → Empty project → Add service → GitHub**
3. En **Variables**, agrega todas las del `.env`
4. Railway detecta Python automáticamente. En **Settings → Start Command** pon:
   ```
   python bot.py
   ```
5. Deploy. El bot queda corriendo 24/7.

**Alternativa gratis:** Render.com → New Web Service → mismo proceso. El plan gratuito duerme tras 15 min de inactividad (no ideal para un bot).

---

## Flujo de uso

```
Tú en Telegram:
  → /nuevo  (reinicia sesión)
  → Mandas audio: "Ganamos 6-4 6-3, mi saque estuvo muy bien, 
    la red la tomamos en casi todos los puntos pero el revés 
    me costó mucho bajo presión, emocionalmente estuve tranquilo"

Bot:
  → Transcribe audio con Whisper
  → Claude extrae: resultado=6-4/6-3, saque=8, uso_red=8, etc.
  → Detecta campos faltantes
  → Muestra teclado: "Devolución de saque (0-10)" [0][1][2]...[10]
  → Tú tocas: 6
  → Siguiente campo faltante con teclado...
  → Cuando todo completo: resumen + botón "✅ Analizar partido"
  → Claude genera análisis completo
  → Guarda en Supabase
  → Te manda el análisis formateado
```

También funciona con entrenamientos:

```
  → "Entrené una hora de bandeja con el profe, salió mejor que la vez pasada"
  → El bot lo detecta como entrenamiento y pregunta foco e intensidad
    en vez de resultado y rivales
```

---

## Partidos vs entrenamientos

El bot distingue solo si le cuentas un **partido** o un **entrenamiento**, en dos pasos:

1. **Keywords obvias** (`detectar_tipo_sesion()` en `bot.py`) — un marcador, "ganamos",
   "rivales" o "torneo" marcan partido; "clase", "drills", "profe" o "canasta" marcan
   entrenamiento. Resuelve la mayoría de los casos sin costo.
2. **Claude como desempate** — si el texto es ambiguo o mezcla señales, la clasificación
   viaja dentro de la misma llamada de extracción (`extraer_datos_claude()`), que devuelve
   la clave `tipo_sesion`. No hay llamada extra a la API.

Tras la primera extracción el bot avisa qué detectó y ofrece un botón para corregirlo.

Diferencias por tipo:

| | Partido | Entrenamiento |
|---|---|---|
| Campos mínimos | resultado, nivel de rivales | tipo de sesión, foco |
| Campos propios | gestión del marcador, ansiedad pre-partido | intensidad, ejercicio difícil, aprendizaje |
| Score emocional | (10−ansiedad) + foco + errores + comunicación | foco + errores + comunicación |
| Sube/baja de nivel | sí | no — no es evidencia competitiva |
| Notifica a la pareja | sí | no |

Ambos tipos viven en la tabla `partidos`, separados por la columna `tipo_sesion`.
Las filas anteriores a este cambio quedan marcadas como `partido`.

Prueba de las funciones puras (sin red ni API keys):

```
python test_tipo_sesion.py
```

---

## Comandos disponibles

| Comando | Qué hace |
|---|---|
| `/start` | Bienvenida e instrucciones |
| `/nuevo` | Reinicia la sesión actual (acepta `/nuevo entrenamiento`) |
| `/resumen` | Muestra el último análisis guardado |
| `/historial` | Lista las últimas 5 sesiones con scores |
| `/borrar` | Borra la sesión actual sin guardar |

---

## Personalización

**Para agregar análisis de video/foto en el futuro:**
- En `handle_foto()`: descargar imagen → base64 → Claude Vision API
- En `handle_video()`: extraer frames → Claude Vision o descargar audio → Whisper

**Para agregar más jugadores:**
- Agrega sus IDs a `ALLOWED_USER_IDS` separados por coma

**Para ver datos en Supabase:**
- Dashboard → Table Editor → `partidos`
- O usa la vista `v_partidos_resumen` para un resumen limpio