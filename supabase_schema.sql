-- ═══════════════════════════════════════════════════════════
-- Coach Pádel Bot — Schema Supabase
-- Ejecuta esto en SQL Editor → New Query → Run
-- ═══════════════════════════════════════════════════════════

-- ── TABLA 1: Perfiles de jugadores ───────────────────────
-- Se crea una vez en el primer /start con la evaluación inicial
CREATE TABLE IF NOT EXISTS jugadores (
    id               BIGSERIAL PRIMARY KEY,
    user_id          TEXT UNIQUE NOT NULL,   -- Telegram user ID
    username         TEXT,
    nivel_inicial    TEXT,       -- categoría asignada en la evaluación inicial
    nivel_actual     TEXT,       -- categoría actualizada tras cada partido
    eval_inicial     JSONB,      -- respuestas del cuestionario Conecta (scores 0-5 por dimensión)
    fecha_eval       TIMESTAMPTZ DEFAULT NOW(),
    partidos_total   INT DEFAULT 0
);

-- ── TABLA 2: Partidos registrados ────────────────────────
CREATE TABLE IF NOT EXISTS partidos (
    id               BIGSERIAL PRIMARY KEY,
    user_id          TEXT NOT NULL REFERENCES jugadores(user_id),
    username         TEXT,
    fecha            TIMESTAMPTZ DEFAULT NOW(),
    nivel_inferido   TEXT,        -- categoría asignada por el bot en este partido
    resultado        TEXT,
    nivel_rivales    TEXT,
    score_tecnica    NUMERIC(4,1),
    score_tactica    NUMERIC(4,1),
    score_emocional  NUMERIC(4,1),
    datos_raw        JSONB,       -- todos los campos del formulario del partido
    analisis_raw     JSONB        -- respuesta completa de Claude
);

-- ── ÍNDICES ───────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_jugadores_user_id ON jugadores(user_id);
CREATE INDEX IF NOT EXISTS idx_partidos_user_id  ON partidos(user_id);
CREATE INDEX IF NOT EXISTS idx_partidos_fecha    ON partidos(fecha DESC);

-- ── VISTA: Resumen de partidos con nivel ─────────────────
CREATE OR REPLACE VIEW v_partidos_resumen AS
SELECT
    p.id,
    j.username,
    p.fecha::DATE                                           AS fecha,
    j.nivel_inicial,
    p.nivel_inferido                                        AS nivel_partido,
    j.nivel_actual,
    p.resultado,
    p.nivel_rivales,
    p.score_tecnica,
    p.score_tactica,
    p.score_emocional,
    ROUND((p.score_tecnica + p.score_tactica + p.score_emocional) / 3, 1) AS score_global,
    p.analisis_raw->>'prioridad_semana'                     AS prioridad_semana,
    p.analisis_raw->>'mensaje_nivel'                        AS mensaje_nivel
FROM partidos p
LEFT JOIN jugadores j ON j.user_id = p.user_id
ORDER BY p.fecha DESC;

-- ── VISTA: Evaluación inicial desglosada ─────────────────
CREATE OR REPLACE VIEW v_evaluaciones AS
SELECT
    user_id,
    username,
    nivel_inicial,
    nivel_actual,
    partidos_total,
    fecha_eval::DATE                                        AS fecha,
    (eval_inicial->>'derecha')::INT                         AS score_derecha,
    (eval_inicial->>'reves')::INT                           AS score_reves,
    (eval_inicial->>'servicio')::INT                        AS score_servicio,
    (eval_inicial->>'volea')::INT                           AS score_volea,
    (eval_inicial->>'rebotes')::INT                         AS score_rebotes,
    (eval_inicial->>'globos')::INT                          AS score_globos,
    (eval_inicial->>'bolas_altas')::INT                     AS score_bolas_altas,
    (eval_inicial->>'estilo_juego')::INT                    AS score_estilo
FROM jugadores;

-- ── TABLA 3: Usuarios autorizados (sistema de invitación) ────────────────
CREATE TABLE IF NOT EXISTS usuarios_autorizados (
    id         BIGSERIAL PRIMARY KEY,
    user_id    TEXT UNIQUE NOT NULL,
    username   TEXT,
    fecha_alta TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_auth_user_id ON usuarios_autorizados(user_id);

-- ── EXTENSIÓN VECTOR (para búsqueda semántica futura) ────────────────────
-- Ejecuta esto primero si no lo has hecho:
-- CREATE EXTENSION IF NOT EXISTS vector;

-- ── TABLA 4: Base de conocimiento de pádel ───────────────────────────────
CREATE TABLE IF NOT EXISTS conocimiento_padel (
    id              BIGSERIAL PRIMARY KEY,
    notion_id       TEXT UNIQUE NOT NULL,   -- ID del bloque en Notion
    titulo          TEXT NOT NULL,
    categoria       TEXT,                   -- técnica / táctica / emocional
    nivel_objetivo  TEXT,                   -- principiante / intermedio / avanzado / todos
    golpe           TEXT,                   -- bandeja / volea / saque / etc.
    contenido       TEXT,                   -- descripción completa
    frase_coach     TEXT,                   -- frase corta memorable
    media_url       TEXT,                   -- link YouTube
    activo          BOOLEAN DEFAULT TRUE,
    ultima_sync     TIMESTAMPTZ DEFAULT NOW(),
    -- Búsqueda full-text en español
    contenido_fts   TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('spanish',
            coalesce(titulo,'') || ' ' ||
            coalesce(categoria,'') || ' ' ||
            coalesce(golpe,'') || ' ' ||
            coalesce(contenido,'') || ' ' ||
            coalesce(frase_coach,'')
        )
    ) STORED
);

CREATE INDEX IF NOT EXISTS idx_conocimiento_fts    ON conocimiento_padel USING GIN(contenido_fts);
CREATE INDEX IF NOT EXISTS idx_conocimiento_nivel  ON conocimiento_padel(nivel_objetivo);
CREATE INDEX IF NOT EXISTS idx_conocimiento_cat    ON conocimiento_padel(categoria);
CREATE INDEX IF NOT EXISTS idx_conocimiento_golpe  ON conocimiento_padel(golpe);
CREATE INDEX IF NOT EXISTS idx_conocimiento_activo ON conocimiento_padel(activo);

-- ── FUNCIÓN: búsqueda full-text en conocimiento_padel ────────────────────
CREATE OR REPLACE FUNCTION buscar_conocimiento_padel(
    query_text TEXT,
    nivel_fil  TEXT DEFAULT 'todos',
    lim        INT  DEFAULT 5
)
RETURNS TABLE (
    titulo       TEXT,
    categoria    TEXT,
    nivel_objetivo TEXT,
    golpe        TEXT,
    contenido    TEXT,
    frase_coach  TEXT,
    media_url    TEXT,
    rank         REAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        k.titulo, k.categoria, k.nivel_objetivo,
        k.golpe, k.contenido, k.frase_coach, k.media_url,
        ts_rank(k.contenido_fts, plainto_tsquery('spanish', query_text)) AS rank
    FROM conocimiento_padel k
    WHERE
        k.activo = TRUE
        AND k.contenido_fts @@ plainto_tsquery('spanish', query_text)
        AND (k.nivel_objetivo = nivel_fil OR k.nivel_objetivo = 'todos')
    ORDER BY rank DESC
    LIMIT lim;
END;
$$ LANGUAGE plpgsql;