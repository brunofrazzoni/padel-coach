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

## Cómo entiende el bot lo que le escribes

**No queda ninguna detección por texto.** Ni keywords, ni prefijos, ni expresiones
regulares. El jugador escribe o dicta como le sale y `clasificar_mensaje()` decide
qué quiere, en una sola llamada al modelo.

Los keywords se sacaron porque matcheaban por prefijo y substring, y fallaban **9 de
16** frases realistas. Los dos patrones que más dolían:

- **Saludo con reporte pegado.** "hola, ganamos 6-4" empezaba con `"hola, "`, así que
  se clasificaba como saludo y **el reporte se perdía entero**.
- **Audio sin signos de pregunta.** Whisper rara vez escribe "?", y la regla de
  consultas técnicas lo exigía. Toda pregunta dictada caía a reporte.

### Las 13 intenciones

Están en el diccionario `INTENTS` de `bot.py`, con su descripción. Esa descripción y
los pares de `EJEMPLOS_ROUTER` **son el entrenamiento del router**: si el bot confunde
dos intenciones, se corrige agregando un ejemplo que las separe, no tocando código.

| Grupo | Intenciones |
|---|---|
| Registrar | `registrar_partido`, `registrar_entrenamiento`, `corregir` |
| Consejos | `consejo_tecnico`, `consejo_tactico`, `consejo_emocional` |
| Sus datos | `consulta_progreso`, `ver_historial`, `ver_nivel`, `ver_ultimo_analisis` |
| Conversación | `saludo`, `ayuda`, `fuera_de_alcance` |

Las tres de consejo mapean a la columna `categoria` de `conocimiento_padel`
(técnica / táctica / emocional), así que la búsqueda se filtra por dimensión: una
pregunta sobre nervios ya no se responde con la empuñadura de la bandeja. El consejo
emocional además inyecta los promedios del propio jugador en ansiedad, foco, gestión
de errores y comunicación, para que no salga genérico.

`consulta_progreso` es distinta de `ver_historial`: la segunda lista sesiones, la
primera lee el historial completo y **saca una conclusión** ("¿mejoré el saque?",
"¿me va mejor contra 4ta?"). El prompt le exige decir que no sabe cuando los datos no
alcanzan, en vez de inventar una tendencia.

### Sin respaldo por keywords

El router reintenta una vez. Si tampoco así obtiene una intención válida, devuelve
`intent=None` y el bot le pide al jugador que repita.

**Esto es un cambio de comportamiento a tener presente:** antes un fallo del
clasificador caía a keywords y el bot seguía funcionando peor pero funcionando. Ahora
una caída del modelo deja el ruteo inoperante. Es el precio de no tener dos caminos
que mantener en paralelo — y de que el respaldo por keywords, en la práctica, acertaba
menos de la mitad de las veces.

### Modelos

Todas las llamadas corren en `claude-haiku-4-5`. Cada una tiene su constante y se
puede sobreescribir por variable de entorno, sin redeployar:

| Constante | Para qué | Variable de entorno |
|---|---|---|
| `MODELO_ROUTER` | clasificar la intención | `MODELO_ROUTER` |
| `MODELO_EXTRACCION` | sacar campos del relato | `MODELO_EXTRACCION` |
| `MODELO_ANALISIS` | el análisis del coach | `MODELO_ANALISIS` |
| `MODELO_CONSEJO` | responder consultas | `MODELO_CONSEJO` |
| `MODELO_NIVEL` | inferir la categoría | `MODELO_NIVEL` |

> ⚠️ **`MODELO_ANALISIS` es el más sensible.** El análisis del coach es el producto:
> detectar patrones entre sesiones, celebrar progresos con evidencia y dar una
> prioridad que no suene de manual. Es donde un modelo más grande se nota. Si el
> análisis empieza a salir genérico, la primera palanca es
> `MODELO_ANALISIS=claude-sonnet-4-6` en el entorno — la diferencia de costo es de
> unos pocos dólares al mes.

## Partidos vs entrenamientos

El tipo queda decidido por la intención: `registrar_partido` o
`registrar_entrenamiento`. `extraer_datos_claude()` ya no clasifica nada — recibe el
tipo resuelto y sólo saca los campos, así que tiene un único camino.

Tras la primera extracción el bot avisa qué detectó y ofrece un botón para corregirlo.
Si el jugador lo corrige, los campos que no aplican al otro tipo se descartan.

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