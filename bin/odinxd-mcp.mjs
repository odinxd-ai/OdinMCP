#!/usr/bin/env node
/**
 * OdinxD Official MCP Bridge (Node.js Zero-Dependency STDIO Client)
 * =================================================================
 * Connects Claude Desktop, Claude Code, Cursor, Antigravity, and Windsurf to
 * OdinxD Cloud (https://odinxd.com) with automatic local PC file uploads
 * (.mp4, .mov, .jpg, .png, .webp) and direct HD MP4 downloads.
 *
 * Environment Variables / CLI Flags:
 *   ODINXD_API_KEY  or  --api-key <odx_live_...>   (Required for tool execution)
 *   ODINXD_API_URL  or  --url <https://odinxd.com> (Optional, defaults to https://odinxd.com)
 *
 * Docs: https://odinxd.com/docs
 */

import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import readline from "node:readline";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const SERVER_VERSION = "2.2.0";
const SUPPORTED_VERSIONS = new Set(["2024-11-05", "2025-03-26", "2025-06-18"]);
const MAX_LOCAL_UPLOAD_BYTES = 500 * 1024 * 1024;
const MAX_STDIO_BATCH = 20;
const JOB_ID_PATTERN = /^[a-zA-Z0-9_-]{4,64}$/;
const SENSITIVE_PATH_PATTERN = /(^|[\\/])(\.ssh|\.aws|\.gnupg|\.git|\.kube|\.docker)([\\/]|$)/i;
const SENSITIVE_FILE_PATTERN = /^(\.env(\..+)?|id_(rsa|dsa|ecdsa|ed25519)(\.pub)?|credentials(\.json)?|\.npmrc|\.pypirc|\.netrc)$/i;

function normalizeSafeApiUrl(rawUrl) {
    const cleaned = String(rawUrl || "https://odinxd.com").trim().replace(/\/+$/, "") || "https://odinxd.com";
    let parsed;
    try {
        parsed = new URL(cleaned);
    } catch {
        throw new Error(`Invalid ODINXD_API_URL: '${cleaned}'. Expected https://odinxd.com`);
    }
    const isLocalDev =
        parsed.protocol === "http:" && (parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1");
    if (parsed.protocol !== "https:" && !isLocalDev) {
        throw new Error("SECURITY_ERROR: ODINXD_API_URL must use https:// to protect your ODINXD_API_KEY.");
    }
    return `${parsed.origin}${parsed.pathname}`.replace(/\/+$/, "");
}

function parseCliArgs(argv) {
    let apiKey = (process.env.ODINXD_API_KEY || "").trim();
    let apiUrl = (process.env.ODINXD_API_URL || "https://odinxd.com").trim();
    let showHelp = false;

    for (let i = 2; i < argv.length; i++) {
        const arg = argv[i];
        if (arg === "--help" || arg === "-h") {
            showHelp = true;
        } else if ((arg === "--api-key" || arg === "-k") && argv[i + 1]) {
            apiKey = String(argv[++i]).trim();
        } else if (arg.startsWith("--api-key=")) {
            apiKey = arg.slice("--api-key=".length).trim();
        } else if ((arg === "--url" || arg === "-u") && argv[i + 1]) {
            apiUrl = String(argv[++i]).trim();
        } else if (arg.startsWith("--url=")) {
            apiUrl = arg.slice("--url=".length).trim();
        }
    }

    return {
        apiKey,
        apiUrl: normalizeSafeApiUrl(apiUrl),
        showHelp,
    };
}

const CLI_CONFIG = parseCliArgs(process.argv);

if (CLI_CONFIG.showHelp) {
    process.stderr.write(
        [
            `OdinxD Official MCP Bridge v${SERVER_VERSION}`,
            `Usage: node odinxd-mcp.mjs [--api-key odx_live_...] [--url https://odinxd.com]`,
            `Docs:  https://odinxd.com/docs`,
            "",
        ].join("\n")
    );
    process.exit(0);
}

const MIME_BY_EXT = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/m4a",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
};

const WAIT_TOOL_SCHEMA = {
    name: "wait_for_render",
    description:
        "Espera automáticamente a que termine un render en OdinxD consultando su avance y, si indicas 'save_to_path', descarga el archivo MP4 final en HD directamente en tu ordenador.",
    inputSchema: {
        type: "object",
        properties: {
            job_id: {
                type: "string",
                description: "ID del render devuelto al crear el video (ej. 'job_a1b2c3d4e5f6').",
            },
            save_to_path: {
                type: "string",
                description:
                    "Ruta local opcional en tu PC donde guardar el MP4 terminado (ej. 'C:/Users/TuUsuario/Desktop/reel_final.mp4' o '~/Desktop/reel.mp4').",
            },
            poll_interval_seconds: {
                type: "number",
                description: "Segundos entre consultas (5 a 30, default: 12).",
            },
            max_wait_seconds: {
                type: "number",
                description: "Tiempo máximo de espera en segundos (30 a 900, default: 420).",
            },
        },
        required: ["job_id"],
    },
};

const LOCAL_PREPROD_TOOLS = [
    {
        name: "local_preprod_doctor",
        description:
            "[100% LOCAL • 0 CRÉDITOS] Verifica el entorno local de preproducción de video (FFmpeg, Python/uv, faster-whisper, yt-dlp, OpenCV y PySceneDetect). Si pasas 'auto_install: true', aprovisiona automáticamente un entorno ligero aislado en ~/.odinxd/preprod_env.",
        inputSchema: {
            type: "object",
            properties: {
                auto_install: {
                    type: "boolean",
                    description: "Si es true, crea ~/.odinxd/preprod_env e instala automáticamente faster-whisper, yt-dlp, opencv-python-headless y scenedetect.",
                },
            },
        },
    },
    {
        name: "transcribe_local_media",
        description:
            "[100% LOCAL • 0 CRÉDITOS] Transcribe 1 o varios videos/audios en bruto con Whisper local (marcas de tiempo exactas por palabra) y detecta silencios acústicos con FFmpeg. Úsala SIEMPRE antes de clean_and_merge_aroll cuando el creador tenga errores hablados, trabas o múltiples tomas repetidas.",
        inputSchema: {
            type: "object",
            properties: {
                input_paths: {
                    type: "array",
                    items: { type: "string" },
                    description: "Lista de 1 o más rutas locales de video/audio en bruto (ej. ['C:/Videos/toma1.mp4', 'C:/Videos/toma2.mp4']).",
                },
                model: {
                    type: "string",
                    enum: ["tiny", "base", "small", "medium"],
                    description: "Modelo local faster-whisper (default: 'base').",
                },
                language: {
                    type: "string",
                    description: "Código de idioma ISO ('es', 'en') o 'auto' (default: 'auto').",
                },
                min_silence_sec: {
                    type: "number",
                    description: "Duración mínima en segundos para marcar un silencio (default: 0.65).",
                },
                auto_install: {
                    type: "boolean",
                    description: "Instala automáticamente faster-whisper en ~/.odinxd/preprod_env si aún no existe (default: true).",
                },
            },
            required: ["input_paths"],
        },
    },
    {
        name: "clean_and_merge_aroll",
        description:
            "[100% LOCAL • 0 CRÉDITOS] Limpia silencios muertos y errores/tomas falsas de 1 o varios videos en bruto, aplica micro-fundidos anticlick, normaliza audio (-16 LUFS) y reencuadra en vertical 9:16 (1080x1920 @ 30fps) generando UN ÚNICO archivo MP4 limpio listo para renderizar en OdinxD.",
        inputSchema: {
            type: "object",
            properties: {
                input_paths: {
                    type: "array",
                    items: { type: "string" },
                    description: "Rutas locales de los videos en bruto (para recorte automático de silencios cuando no se pasa 'segments').",
                },
                segments: {
                    type: "array",
                    description: "Lista curada de tramos limpios [{'file': '...', 'start': 2.4, 'end': 14.8}] tras revisar transcribe_local_media para eliminar errores hablados y tomas repetidas.",
                    items: {
                        type: "object",
                        properties: {
                            file: { type: "string" },
                            start: { type: "number" },
                            end: { type: "number" },
                        },
                        required: ["start", "end"],
                    },
                },
                output_path: {
                    type: "string",
                    description: "Ruta local opcional donde guardar el MP4 limpio (por defecto en ~/.odinxd/preprod_exports/).",
                },
                min_silence_sec: {
                    type: "number",
                    description: "Silencio mínimo a recortar en modo automático (default: 0.65).",
                },
                silence_db: {
                    type: "number",
                    description: "Umbral en dB para detección de silencio (default: -35).",
                },
                smart_reframe: {
                    type: "boolean",
                    description: "Centra automáticamente el rostro en videos horizontales 16:9 al pasarlos a 9:16 (default: true).",
                },
                auto_install: {
                    type: "boolean",
                    description: "Aprovisiona OpenCV si falta para el centrado facial (default: true).",
                },
            },
        },
    },
    {
        name: "extract_podcast_clips",
        description:
            "[100% LOCAL • 0 CRÉDITOS] Automatiza la extracción de Reels verticales 9:16 desde podcasts largos o videos públicos (yt-dlp + Whisper + auto-reframe facial OpenCV). Usa action='analyze' para obtener el guion con tiempos y action='extract' para generar los clips 9:16 listos para OdinxD.",
        inputSchema: {
            type: "object",
            properties: {
                action: {
                    type: "string",
                    enum: ["analyze", "extract"],
                    description: "'analyze' transcribe el episodio completo en bloques; 'extract' recorta y reencuadra en 9:16 los momentos elegidos.",
                },
                source: {
                    type: "string",
                    description: "Ruta local del podcast (.mp4/.mov) o URL pública del video (soportada por yt-dlp).",
                },
                clips: {
                    type: "array",
                    description: "Requerido en action='extract': lista de clips [{'start': 120.5, 'end': 165.2, 'title': 'gancho_1'}].",
                    items: {
                        type: "object",
                        properties: {
                            start: { type: "number" },
                            end: { type: "number" },
                            title: { type: "string" },
                        },
                        required: ["start", "end"],
                    },
                },
                output_dir: {
                    type: "string",
                    description: "Carpeta local opcional donde guardar los clips 9:16 extraídos.",
                },
                model: {
                    type: "string",
                    enum: ["tiny", "base", "small", "medium"],
                    description: "Modelo Whisper local para action='analyze' (default: 'base').",
                },
                language: {
                    type: "string",
                    description: "Idioma ('es', 'en' o 'auto').",
                },
                auto_install: {
                    type: "boolean",
                    description: "Instala automáticamente yt-dlp/faster-whisper/OpenCV en ~/.odinxd/preprod_env si faltan (default: true).",
                },
            },
            required: ["action", "source"],
        },
    },
    {
        name: "manage_local_stock_bank",
        description:
            "[100% LOCAL • 0 CRÉDITOS] Crea, etiqueta y busca en el Banco de Stock Local personal del usuario (~/.odinxd/stock_bank). Corta videos largos en clips verticales 9:16 de 3-5s con miniaturas JPG (PySceneDetect) y devuelve 'customStockParam' listo para 'custom_stock' en OdinxD.",
        inputSchema: {
            type: "object",
            properties: {
                action: {
                    type: "string",
                    enum: ["ingest", "search", "list", "tag", "remove"],
                    description: "'ingest' importa videos/carpeta; 'search' devuelve hasta 6 clips listos para custom_stock; 'tag' añade etiquetas; 'list' lista el banco; 'remove' borra un clip.",
                },
                source: {
                    type: "string",
                    description: "Ruta local de un video o carpeta con grabaciones del usuario (para action='ingest').",
                },
                query: {
                    type: "string",
                    description: "Palabras clave de búsqueda (ej. 'cocina marmol', 'gimnasio pesas', 'playa dron') para action='search'.",
                },
                category: {
                    type: "string",
                    description: "Categoría opcional (ej. 'real_estate', 'lifestyle', 'gym', 'product', 'tech').",
                },
                tags: {
                    type: "string",
                    description: "Etiquetas separadas por coma (para 'ingest' o 'tag').",
                },
                description: {
                    type: "string",
                    description: "Descripción visual del clip (para 'ingest' o 'tag').",
                },
                clip_id: {
                    type: "string",
                    description: "ID del clip en el banco (ej. 'stk_a1b2c3d4e5') para 'tag' o 'remove'.",
                },
                clip_duration: {
                    type: "number",
                    description: "Duración objetivo en segundos de cada clip de stock al importar (2.5 a 6.0, default: 4.0).",
                },
                max_clips_per_video: {
                    type: "number",
                    description: "Máximo de escenas a extraer por cada video fuente (default: 8).",
                },
                limit: {
                    type: "number",
                    description: "Máximo de clips a devolver en 'search' (1 a 6, default: 6).",
                },
                auto_install: {
                    type: "boolean",
                    description: "Instala PySceneDetect automáticamente si falta (default: true).",
                },
            },
            required: ["action"],
        },
    },
    {
        name: "generate_local_voiceover",
        description:
            "[100% LOCAL • 0 CRÉDITOS] Sintetiza gratis en el PC del usuario una locución neural en MP3 + archivo de subtítulos .srt sincronizado usando edge-tts (sin consumir servidor ni créditos de OdinxD). Ideal para narrar comerciales Faceless cinematográficos o mini-documentales.",
        inputSchema: {
            type: "object",
            properties: {
                text: {
                    type: "string",
                    description: "Guion completo de la narración (redactado por tu agente).",
                },
                voice: {
                    type: "string",
                    description:
                        "Preset de voz ('es_mx_male', 'es_mx_female', 'es_es_male', 'es_es_female', 'es_co_female', 'es_ar_male', 'en_male_cinema', 'en_male_commercial', 'en_female_ugc', 'en_female_luxury') o nombre neural de Edge (ej. 'es-MX-JorgeNeural').",
                },
                rate: {
                    type: "string",
                    description: "Velocidad opcional (ej. '+5%', '+0%', '-5%'). Default: '+0%'.",
                },
                output_path: {
                    type: "string",
                    description: "Ruta local opcional .mp3 donde guardar la locución.",
                },
                auto_install: {
                    type: "boolean",
                    description: "Instala automáticamente edge-tts en ~/.odinxd/preprod_env si falta (default: true).",
                },
            },
            required: ["text"],
        },
    },
    {
        name: "assemble_local_timeline",
        description:
            "[100% LOCAL • 0 CRÉDITOS • $0 COSTE SERVIDOR] Ensambla en el ordenador del usuario secuencias de clips generados con IA (anuncios UGC largos de 30s-60s+, comerciales Faceless cinematográficos o episodios completos de Microdrama) en un master final 1080x1920 (o 1920x1080) @ 30fps con normalización a -16 LUFS, mezcla de locución/SFX/música y quemado opcional de subtítulos locales.",
        inputSchema: {
            type: "object",
            properties: {
                clip_paths: {
                    type: "array",
                    items: { type: "string" },
                    description: "Lista ordenada de rutas locales .mp4 de las tomas/escenas a unir.",
                },
                output_path: {
                    type: "string",
                    description: "Ruta local .mp4 donde guardar el master final (ej. '~/Desktop/anuncio_final.mp4').",
                },
                aspect_ratio: {
                    type: "string",
                    enum: ["9:16", "16:9"],
                    description: "Relación de aspecto del master ('9:16' -> 1080x1920, '16:9' -> 1920x1080). Default: '9:16'.",
                },
                audio_mode: {
                    type: "string",
                    enum: ["keep_native", "voiceover_master"],
                    description:
                        "'keep_native': conserva el diálogo Lip-Sync y ambiente nativo de los clips (ideal para UGC y Microdramas). 'voiceover_master': usa 'voiceover_path' como voz principal y atenúa suavemente los SFX nativos de los clips (ideal para Comerciales Faceless).",
                },
                voiceover_path: {
                    type: "string",
                    description: "Ruta local del MP3/WAV de locución (obligatorio si audio_mode='voiceover_master').",
                },
                bg_music_path: {
                    type: "string",
                    description: "Opcional: ruta local de música de fondo MP3/WAV.",
                },
                sfx_volume: {
                    type: "number",
                    description: "Volumen relativo de los SFX nativos cuando hay voiceover_master (0.0 a 1.0, default: 0.16).",
                },
                music_volume: {
                    type: "number",
                    description: "Volumen relativo de la música de fondo (0.0 a 0.8, default: 0.10).",
                },
                transition: {
                    type: "string",
                    enum: ["cut", "crossfade"],
                    description: "'cut' (corte directo limpio con micro-fade anticlick, default) o 'crossfade' (fundido suave de 0.25s).",
                },
                subtitles: {
                    type: "string",
                    enum: ["none", "auto_whisper", "srt"],
                    description:
                        "'none' (sin subtítulos, ideal cine/microdrama limpio), 'auto_whisper' (transcribe localmente con faster-whisper y quema subtítulos de 3-4 palabras) o 'srt' (usa 'srt_path').",
                },
                srt_path: {
                    type: "string",
                    description: "Ruta local .srt (ej. devuelta por generate_local_voiceover) cuando subtitles='srt'.",
                },
                subtitle_preset: {
                    type: "string",
                    enum: ["ugc_clean", "cinema_yellow", "boxed_impact", "minimal_luxury"],
                    description: "Estilo visual de subtítulos locales (default: 'ugc_clean').",
                },
                language: {
                    type: "string",
                    description: "Idioma ('es', 'en' o 'auto') para auto_whisper.",
                },
                auto_install: {
                    type: "boolean",
                    description: "Aprovisiona faster-whisper si se pide auto_whisper y aún no está instalado (default: true).",
                },
            },
            required: ["clip_paths"],
        },
    },
];

const LOCAL_PREPROD_TOOL_NAMES = new Set(LOCAL_PREPROD_TOOLS.map((t) => t.name));

const OFFLINE_FALLBACK_TOOLS = [
    {
        name: "get_account_quota",
        description: "Consulta el plan actual, renders disponibles y créditos de IA restantes en OdinxD.",
        inputSchema: { type: "object", properties: {} },
    },
    {
        name: "get_odinxd_catalog",
        description: "Devuelve el catálogo completo de OdinxD (voces Omni 1.2 Flash, 20 estilos IA, estancias inmobiliarias, fuentes, subtítulos, voces TTS y música).",
        inputSchema: {
            type: "object",
            properties: {
                section: {
                    type: "string",
                    enum: ["all", "omni_voices", "ai_styles", "inmo_rooms", "fonts", "subtitles", "motion_components", "voices", "music"],
                },
            },
        },
    },
    {
        name: "generate_ai_image",
        description:
            "Genera o compone de 1 a 4 imágenes IA con 'gemini-2.5-flash-image' (avatares UGC sosteniendo producto en las 4 combinaciones posibles, retratos de casting de microdramas o keyframes cinematográficos). Coste: 1 Crédito IA/imagen, 0 renders descontados.",
        inputSchema: {
            type: "object",
            properties: {
                prompt: { type: "string" },
                purpose: { type: "string", enum: ["ugc_avatar_with_product", "character_casting", "cinematic_keyframe", "custom"] },
                aspect_ratio: { type: "string", enum: ["9:16", "16:9", "1:1"] },
                aesthetic: { type: "string", enum: ["ugc_smartphone", "cinema_35mm", "noir_thriller", "anime_modern", "editorial_luxury"] },
                count: { type: "number" },
                avatar_image: { type: "string" },
                product_images: { type: "array", items: { type: "string" } },
                reference_images: { type: "array", items: { type: "string" } },
                wait: { type: "boolean" },
                save_to_dir: { type: "string" },
            },
            required: ["prompt"],
        },
    },
    {
        name: "generate_ai_video_clip",
        description:
            "Genera un clip de video nativo (3s a 15s) con voz hablada Lip-Sync o SFX usando 'gemini-omni-1.2-flash' (1 Crédito IA/s sin referencias, 2 Créditos IA/s con referencias, 0 renders descontados).",
        inputSchema: {
            type: "object",
            properties: {
                prompt: { type: "string" },
                duration: { type: "number" },
                clip_mode: { type: "string", enum: ["ugc_talking", "microdrama_scene", "cinematic_faceless", "odin_style", "custom"] },
                reference_mode: { type: "string", enum: ["animate_photo", "ingredient"] },
                dialogue_script: { type: "string" },
                language: { type: "string", enum: ["en", "es"] },
                voice_preset: { type: "string" },
                voice_anchor: { type: "string" },
                style_id: { type: "string" },
                aspect_ratio: { type: "string", enum: ["9:16", "16:9"] },
                first_frame_image: { type: "string" },
                avatar_image: { type: "string" },
                product_images: { type: "array", items: { type: "string" } },
                reference_images: { type: "array", items: { type: "string" } },
                wait: { type: "boolean" },
                save_to_path: { type: "string" },
            },
            required: ["prompt"],
        },
    },
    {
        name: "generate_ai_video_batch",
        description:
            "Genera en paralelo un lote de 1 a 10 clips de video IA (3s a 15s cada uno) con 'gemini-omni-1.2-flash' (ideal para 10x15s UGC, videos UGC largos de 30s-60s+ con la misma voz, Comerciales Faceless o Microdramas).",
        inputSchema: {
            type: "object",
            properties: {
                clips: { type: "array", items: { type: "object" } },
                language: { type: "string", enum: ["en", "es"] },
                voice_preset: { type: "string" },
                voice_anchor: { type: "string" },
                aspect_ratio: { type: "string", enum: ["9:16", "16:9"] },
                avatar_image: { type: "string" },
                product_images: { type: "array", items: { type: "string" } },
                wait: { type: "boolean" },
                save_to_dir: { type: "string" },
            },
            required: ["clips"],
        },
    },
    {
        name: "create_faceless_ad",
        description: "Crea un anuncio vertical 9:16 Faceless AI Ads completo desde texto (guion + locución TTS + escenas IA + render).",
        inputSchema: {
            type: "object",
            properties: {
                product_name: { type: "string" },
                description: { type: "string" },
                faceless_mode: { type: "string", enum: ["commercial_narrated", "asmr", "dynamic_beat", "historical_doc"] },
                target_duration: { type: "number" },
                lang: { type: "string", enum: ["es", "en"] },
                voice_id: { type: "string" },
                script_text: { type: "string" },
                subtitle_style: { type: "string" },
                typography: { type: "string" },
                bg_music: { type: "string" },
                product_images: { type: "array", items: { type: "string" } },
                avatar_image: { type: "string" },
            },
            required: ["product_name", "description"],
        },
    },
    {
        name: "render_hybrid_reel",
        description:
            "Edita UN ÚNICO video base A-Roll limpio (sin silencios ni tomas falsas) en Modo Híbrido con 20 estilos de B-Roll IA (incluye Inmobiliario y UGC). " +
            "REGLA 1: OdinxD NO corta silencios/errores ni une múltiples videos base (usa FFmpeg local primero si es bruto). " +
            "REGLA 2: 'avatar_stock', 'ugc_stock' e 'inmo_avatar_stock' SOLO aceptan rostros de creadores/clientes privados; PROHIBIDO celebridades/figuras públicas (en podcasts de famosos usa 'stock_hyperreal', 'cinematic_macro' o 'scrapbook_polaroid').",
        inputSchema: {
            type: "object",
            properties: {
                video_url: {
                    type: "string",
                    description: "UN ÚNICO archivo de video A-Roll limpio (ruta local C:/Videos/reel.mp4 o URL https://).",
                },
                ai_styles: { type: "array", items: { type: "string" } },
                clips_count: { type: "number" },
                clip_duration: { type: "number" },
                subtitle_style: { type: "string", description: "Default: 'kinetic_dinamic' (o 'kinetic_blur' para lujo/podcast)." },
                typography: { type: "string", description: "Default: 'Montserrat' (o 'Playfair Display' en inmobiliaria, 'Space Grotesk' en tech)." },
                highlight_color: { type: "string" },
                avatar_image: { type: "string", description: "Foto del rostro privado (PROHIBIDO figuras públicas/celebridades)." },
                saas_image: { type: "string" },
                product_images: { type: "array", items: { type: "string" } },
                inmo_photos: {
                    type: "array",
                    items: {
                        type: "object",
                        properties: { url: { type: "string" }, room: { type: "string" }, label: { type: "string" } },
                        required: ["url", "room"],
                    },
                },
                custom_stock: { type: "string" },
                bg_music: { type: "string" },
                script: { type: "string" },
            },
            required: ["video_url"],
        },
    },
    {
        name: "render_viral_beat",
        description: "Edita UN ÚNICO video base A-Roll limpio (sin silencios ni errores; ruta local o URL https://) en Modo ViralBeat 2.0 con zoom punch, split-screens y B-Roll IA.",
        inputSchema: {
            type: "object",
            properties: {
                video_url: { type: "string", description: "UN ÚNICO archivo de video A-Roll limpio (ruta local o URL https://)." },
                ai_clips_count: { type: "number" },
                ai_clip_duration: { type: "number" },
                ai_styles: { type: "array", items: { type: "string" } },
                creative_prompt: { type: "string" },
                typography: { type: "string" },
                base_subtitle_style: { type: "string" },
                stock_subtitle_style: { type: "string" },
                avatar_image: { type: "string" },
                product_images: { type: "array", items: { type: "string" } },
                inmo_photos: { type: "array", items: { type: "object" } },
                custom_stock: { type: "string" },
                bg_music: { type: "string" },
                script: { type: "string" },
            },
            required: ["video_url"],
        },
    },
    {
        name: "render_motion_stock",
        description: "Edita UN ÚNICO video A-Roll limpio (sin silencios ni tomas falsas) con Motion Graphics de Remotion (0 créditos de IA; consume 1 render).",
        inputSchema: {
            type: "object",
            properties: {
                video_url: { type: "string", description: "UN ÚNICO archivo de video A-Roll limpio (ruta local o URL https://)." },
                components: { type: "array", items: { type: "string" } },
                typography: { type: "string" },
                highlight_color: { type: "string" },
                subtitle_style: { type: "string" },
            },
            required: ["video_url"],
        },
    },
    {
        name: "render_maxy_overlay",
        description: "Edita UN ÚNICO video A-Roll limpio (sin silencios ni tomas falsas) en Modo Maxy Overlay con tipografía 3D y overlays animados (0 créditos de IA).",
        inputSchema: {
            type: "object",
            properties: {
                video_url: { type: "string", description: "UN ÚNICO archivo de video A-Roll limpio (ruta local o URL https://)." },
                typography: { type: "string" },
                highlight_color: { type: "string" },
            },
            required: ["video_url"],
        },
    },
    {
        name: "render_fitness_talking_head",
        description: "Edita UN ÚNICO video A-Roll limpio (sin silencios ni tomas falsas) directo a cámara con subtítulos de máxima retención (0 créditos de IA).",
        inputSchema: {
            type: "object",
            properties: {
                video_url: { type: "string", description: "UN ÚNICO archivo de video A-Roll limpio (ruta local o URL https://)." },
                typography: { type: "string" },
                subtitle_style: { type: "string" },
                highlight_color: { type: "string" },
            },
            required: ["video_url"],
        },
    },
    {
        name: "get_render_status",
        description: "Consulta el estado, porcentaje y enlace MP4 de un render en OdinxD.",
        inputSchema: {
            type: "object",
            properties: { job_id: { type: "string" } },
            required: ["job_id"],
        },
    },
    WAIT_TOOL_SCHEMA,
    ...LOCAL_PREPROD_TOOLS,
];

function expandHome(filePath) {
    const trimmed = String(filePath || "").trim();
    if (trimmed.startsWith("~/") || trimmed.startsWith("~\\")) {
        return path.join(os.homedir(), trimmed.slice(2));
    }
    if (trimmed.toLowerCase().startsWith("file://")) {
        try {
            return new URL(trimmed).pathname.replace(/^\/([a-zA-Z]:)/, "$1");
        } catch {
            return trimmed;
        }
    }
    return trimmed;
}

function inferInmoRoomFromFilename(filename) {
    const stem = path.parse(String(filename || "")).name.toLowerCase();
    const clean = ` ${stem
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/[^a-z0-9]+/g, " ")
        .trim()} `;
    if (!clean.trim()) return "sala";
    if (/(habitacion principal|recamara principal|dormitorio principal|master|suite)/.test(clean)) return "habitacion_principal";
    if (/(vestidor|closet|walk in)/.test(clean)) return "vestidor";
    if (/(piscina|alberca|jardin|pool|patio|asador|bbq)/.test(clean)) return "jardin_piscina";
    if (/(terraza|balcon|rooftop|roof|mirador|terrace)/.test(clean)) return "terraza";
    if (/(cocina|isla|kitchen|alacena)/.test(clean)) return "cocina";
    if (/(comedor|dining)/.test(clean)) return "comedor";
    if (/(bano|ducha|regadera|jacuzzi|tina|bath|tocador)/.test(clean)) return "bano";
    if (/(estudio|oficina|despacho|office|tv|family)/.test(clean)) return "estudio_oficina";
    if (/(fachada|exterior|frente|entrada|cochera|garage)/.test(clean)) return "fachada_exterior";
    if (/(lobby|amenidad|recepcion|gimnasio|gym|club)/.test(clean)) return "lobby_amenidades";
    if (/(sala|salon|living|sofa)/.test(clean)) return "sala";
    if (/(habitacion|recamara|dormitorio|cuarto|alcoba|bedroom)/.test(clean)) return "habitacion_secundaria";
    return "sala";
}

function requireApiKey() {
    if (!CLI_CONFIG.apiKey) {
        throw new Error(
            "Falta tu API Key de OdinxD (ODINXD_API_KEY). Genera tu clave 'odx_live_...' en https://odinxd.com/dashboard y agrégala en la sección 'env' de tu configuración MCP."
        );
    }
    return CLI_CONFIG.apiKey;
}

function assertSafeLocalMediaCandidate(candidatePath) {
    const resolved = path.resolve(candidatePath);
    const base = path.basename(resolved);
    if (SENSITIVE_PATH_PATTERN.test(resolved) || SENSITIVE_FILE_PATTERN.test(base)) {
        throw new Error(
            `LOCAL_SECURITY_BLOCKED: Refusing to access sensitive file or directory '${base}'. Only video, audio, and image files are allowed.`
        );
    }
    return resolved;
}

async function uploadLocalFileIfPresent(rawRef, fieldName = "file") {
    if (!rawRef || typeof rawRef !== "string") return rawRef;
    const trimmed = rawRef.trim();
    // Preserve remote https:// URLs AND server-side OdinxD '/api/media/...' chained assetRefs untouched!
    if (!trimmed || /^https?:\/\//i.test(trimmed) || trimmed.startsWith("/api/media/")) return trimmed;

    const candidate = expandHome(trimmed);
    const looksLikeLocalPath =
        /^[a-zA-Z]:[\\/]/.test(candidate) ||
        candidate.startsWith("/") ||
        candidate.startsWith(".\\") ||
        candidate.startsWith("./") ||
        trimmed.startsWith("~/") ||
        trimmed.startsWith("~\\") ||
        trimmed.toLowerCase().startsWith("file://");

    if (looksLikeLocalPath) {
        assertSafeLocalMediaCandidate(candidate);
    }

    let lstat = null;
    try {
        lstat = fs.lstatSync(candidate);
    } catch {
        lstat = null;
    }

    if (!lstat) {
        if (looksLikeLocalPath) {
            throw new Error(`LOCAL_FILE_NOT_FOUND: No se encontró el archivo local '${trimmed}'. Verifica la ruta exacta.`);
        }
        return trimmed;
    }

    if (lstat.isSymbolicLink()) {
        throw new Error(
            `LOCAL_SYMLINK_BLOCKED: Por seguridad, el puente MCP no sube enlaces simbólicos ('${path.basename(candidate)}'). Pasa la ruta directa al archivo multimedia real.`
        );
    }

    if (!lstat.isFile()) {
        return trimmed;
    }

    assertSafeLocalMediaCandidate(candidate);

    const ext = path.extname(candidate).toLowerCase();
    if (!Object.prototype.hasOwnProperty.call(MIME_BY_EXT, ext)) {
        throw new Error(
            `UNSUPPORTED_LOCAL_MEDIA_EXTENSION: La extensión '${ext || "(sin extensión)"}' no está permitida. Usa archivos multimedia válidos (${Object.keys(MIME_BY_EXT).join(", ")}).`
        );
    }

    if (lstat.size <= 0) {
        throw new Error(`EMPTY_LOCAL_FILE: El archivo '${path.basename(candidate)}' está vacío (0 bytes).`);
    }
    if (lstat.size > MAX_LOCAL_UPLOAD_BYTES) {
        throw new Error(`LOCAL_FILE_TOO_LARGE: El archivo '${path.basename(candidate)}' supera el límite máximo de 500 MB.`);
    }

    const apiKey = requireApiKey();
    const mimeType = MIME_BY_EXT[ext];
    const fileName = path.basename(candidate);

    let blob;
    if (typeof fs.openAsBlob === "function") {
        blob = await fs.openAsBlob(candidate, { type: mimeType });
    } else {
        const buf = await fs.promises.readFile(candidate);
        blob = new Blob([buf], { type: mimeType });
    }

    const form = new FormData();
    form.append(fieldName, blob, fileName);

    const res = await fetch(`${CLI_CONFIG.apiUrl}/api/v1/upload`, {
        method: "POST",
        headers: {
            Authorization: `Bearer ${apiKey}`,
            Accept: "application/json",
        },
        body: form,
    });

    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
        throw new Error(`Error subiendo '${fileName}' a OdinxD (${res.status}): ${data.error || res.statusText}`);
    }

    const uploaded = Array.isArray(data.files) ? data.files : [];
    if (!uploaded.length || !uploaded[0].path) {
        throw new Error(`OdinxD no devolvió ruta interna tras subir '${fileName}'.`);
    }
    return uploaded[0].path;
}

function assertSingleBaseVideoRef(val) {
    if (Array.isArray(val)) {
        throw new Error(
            "MULTIPLE_BASE_VIDEOS_NOT_SUPPORTED: OdinxD solo admite UN ÚNICO video base A-Roll limpio por composición y NO concatena varios videos base. " +
                "Usa primero tus herramientas locales del agente (ej. FFmpeg) para eliminar silencios/errores y unir las tomas en un único .mp4 limpio antes de enviarlo."
        );
    }
    if (typeof val === "string") {
        const trimmed = val.trim();
        const urlMatches = trimmed.match(/https?:\/\/[^\s,;|]+/gi) || [];
        const parts = trimmed
            .split(/[,;|\n]+/)
            .map((p) => p.trim())
            .filter(Boolean);
        const videoParts = parts.filter((p) => /\.(mp4|mov|webm|mkv|m4v)(\?|#|$)/i.test(p));
        if (urlMatches.length > 1 || videoParts.length > 1) {
            throw new Error(
                "MULTIPLE_BASE_VIDEOS_NOT_SUPPORTED: Se detectaron múltiples videos en 'video_url'. OdinxD trabaja exclusivamente con UN ÚNICO video A-Roll limpio (sin silencios ni errores). " +
                    "Limpia silencios/tomas falsas y une los clips localmente con FFmpeg en un solo .mp4 antes de llamar a OdinxD."
            );
        }
    }
}

async function resolveToolFileArguments(rawArgs) {
    if (!rawArgs || typeof rawArgs !== "object") return {};
    const args = { ...rawArgs };

    for (const vKey of ["video_url", "video_path", "videoUrl"]) {
        if (args[vKey] !== undefined && args[vKey] !== null) {
            assertSingleBaseVideoRef(args[vKey]);
        }
    }

    const singleFields = [
        ["video_url", "video"],
        ["video_path", "video"],
        ["videoUrl", "video"],
        ["avatar_image", "avatarImage"],
        ["avatar_image_path", "avatarImage"],
        ["avatarImage", "avatarImage"],
        ["first_frame_image", "avatarImage"],
        ["firstFrameImage", "avatarImage"],
        ["saas_image", "saasImage"],
        ["saas_image_path", "saasImage"],
        ["saasImage", "saasImage"],
        ["bg_music", "bgMusic"],
    ];

    for (const [key, fieldName] of singleFields) {
        if (typeof args[key] === "string" && args[key].trim()) {
            args[key] = await uploadLocalFileIfPresent(args[key], fieldName);
        }
    }

    for (const arrKey of ["product_images", "productImages"]) {
        if (Array.isArray(args[arrKey])) {
            const resolved = [];
            for (const item of args[arrKey].slice(0, 3)) {
                if (typeof item === "string" && item.trim()) {
                    resolved.push(await uploadLocalFileIfPresent(item, "productImages"));
                }
            }
            args[arrKey] = resolved;
        }
    }

    for (const refKey of ["reference_images", "referenceImages"]) {
        if (Array.isArray(args[refKey])) {
            const resolvedRefs = [];
            for (const item of args[refKey].slice(0, 4)) {
                if (typeof item === "string" && item.trim()) {
                    resolvedRefs.push(await uploadLocalFileIfPresent(item, "productImages"));
                }
            }
            args[refKey] = resolvedRefs;
        }
    }

    if (Array.isArray(args.clips)) {
        const resolvedClips = [];
        for (const clip of args.clips.slice(0, 10)) {
            if (!clip || typeof clip !== "object") continue;
            const cCopy = { ...clip };
            for (const cSingle of ["first_frame_image", "firstFrameImage", "avatar_image", "avatarImage"]) {
                if (typeof cCopy[cSingle] === "string" && cCopy[cSingle].trim()) {
                    cCopy[cSingle] = await uploadLocalFileIfPresent(cCopy[cSingle], "avatarImage");
                }
            }
            for (const cArr of ["product_images", "productImages"]) {
                if (Array.isArray(cCopy[cArr])) {
                    const upArr = [];
                    for (const p of cCopy[cArr].slice(0, 3)) {
                        if (typeof p === "string" && p.trim()) {
                            upArr.push(await uploadLocalFileIfPresent(p, "productImages"));
                        }
                    }
                    cCopy[cArr] = upArr;
                }
            }
            for (const cRefArr of ["reference_images", "referenceImages"]) {
                if (Array.isArray(cCopy[cRefArr])) {
                    const upRefs = [];
                    for (const r of cCopy[cRefArr].slice(0, 4)) {
                        if (typeof r === "string" && r.trim()) {
                            upRefs.push(await uploadLocalFileIfPresent(r, "productImages"));
                        }
                    }
                    cCopy[cRefArr] = upRefs;
                }
            }
            resolvedClips.push(cCopy);
        }
        args.clips = resolvedClips;
    }

    if (typeof args.custom_stock === "string" && args.custom_stock.trim()) {
        const parts = args.custom_stock
            .split(",")
            .map((p) => p.trim())
            .filter(Boolean);
        const uploadedParts = [];
        for (const p of parts.slice(0, 6)) {
            uploadedParts.push(await uploadLocalFileIfPresent(p, "customStock"));
        }
        args.custom_stock = uploadedParts.join(",");
    }

    for (const inmoKey of ["inmo_photos", "inmoPhotos"]) {
        if (Array.isArray(args[inmoKey])) {
            const resolvedInmo = [];
            for (const entry of args[inmoKey].slice(0, 8)) {
                if (typeof entry === "string" && entry.trim()) {
                    const upPath = await uploadLocalFileIfPresent(entry, "inmoPhotos");
                    resolvedInmo.push({
                        url: upPath,
                        room: inferInmoRoomFromFilename(entry),
                        label: "",
                    });
                } else if (entry && typeof entry === "object") {
                    const src = String(entry.url || entry.path || entry.source || "").trim();
                    if (!src) continue;
                    const upPath = await uploadLocalFileIfPresent(src, "inmoPhotos");
                    resolvedInmo.push({
                        url: upPath,
                        room: String(entry.room || inferInmoRoomFromFilename(src)).trim(),
                        label: String(entry.label || "").trim(),
                    });
                }
            }
            args[inmoKey] = resolvedInmo;
        }
    }

    return args;
}

function resolveSafeMp4Output(rawSavePath, jobId) {
    let targetFile = path.resolve(expandHome(String(rawSavePath)));
    if (SENSITIVE_PATH_PATTERN.test(targetFile)) {
        throw new Error("LOCAL_SECURITY_BLOCKED: Refusing to write inside a sensitive system/credentials directory.");
    }
    try {
        if (fs.existsSync(targetFile)) {
            const st = fs.lstatSync(targetFile);
            if (st.isSymbolicLink()) {
                throw new Error("LOCAL_SYMLINK_BLOCKED: Refusing to overwrite a symbolic link in save_to_path.");
            }
            if (st.isDirectory()) {
                targetFile = path.join(targetFile, `${jobId}.mp4`);
            }
        }
    } catch (e) {
        if (e instanceof Error && e.message.startsWith("LOCAL_")) throw e;
    }
    if (path.extname(targetFile).toLowerCase() !== ".mp4") {
        throw new Error("INVALID_SAVE_PATH_EXTENSION: 'save_to_path' debe terminar en '.mp4' (o apuntar a una carpeta existente).");
    }
    return targetFile;
}

function assertSafeDownloadUrl(downloadUrl) {
    let parsed;
    try {
        parsed = new URL(String(downloadUrl));
    } catch {
        throw new Error(`Invalid downloadUrl returned by server: '${downloadUrl}'`);
    }
    const isLocalDev =
        parsed.protocol === "http:" && (parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1");
    if (parsed.protocol !== "https:" && !isLocalDev) {
        throw new Error("SECURITY_ERROR: Refusing to download render over non-HTTPS connection.");
    }
    return parsed.toString();
}

async function downloadAuthorizedFileToDisk(downloadUrl, targetFile, apiKey) {
    const safeDownloadUrl = assertSafeDownloadUrl(downloadUrl);
    const parsedTarget = new URL(safeDownloadUrl);
    const parsedApi = new URL(CLI_CONFIG.apiUrl);
    const headers = {};
    if (parsedTarget.origin === parsedApi.origin && apiKey) {
        headers.Authorization = `Bearer ${apiKey}`;
    }
    await fs.promises.mkdir(path.dirname(targetFile), { recursive: true });
    const dlRes = await fetch(safeDownloadUrl, { headers });
    if (!dlRes.ok || !dlRes.body) {
        throw new Error(`Falló la descarga del activo multimedia (HTTP ${dlRes.status}). URL: ${safeDownloadUrl}`);
    }
    const fileStream = fs.createWriteStream(targetFile);
    await pipeline(Readable.fromWeb(dlRes.body), fileStream);
    return targetFile;
}

async function handleWaitForRender(args) {
    const apiKey = requireApiKey();
    const jobId = String(args?.job_id || args?.jobId || "").trim();
    if (!jobId || !JOB_ID_PATTERN.test(jobId)) {
        throw new Error("INVALID_JOB_ID: El parámetro 'job_id' es obligatorio y solo admite caracteres alfanuméricos, guiones y guion bajo.");
    }

    const intervalMs = Math.max(2, Math.min(30, Number(args?.poll_interval_seconds ?? 8))) * 1000;
    const maxWaitMs = Math.max(30, Math.min(900, Number(args?.max_wait_seconds ?? 480))) * 1000;
    const deadline = Date.now() + maxWaitMs;
    let latest = null;

    while (Date.now() < deadline) {
        const res = await fetch(`${CLI_CONFIG.apiUrl}/api/v1/jobs/${encodeURIComponent(jobId)}`, {
            method: "GET",
            headers: {
                Authorization: `Bearer ${apiKey}`,
                Accept: "application/json",
            },
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            throw new Error(data.error || `Error consultando estado de ${jobId} (HTTP ${res.status})`);
        }
        latest = data;

        if (data.status === "done") {
            if (data.pipelineMode === "ai_media_generation" && Array.isArray(data.items)) {
                const defaultOutDir = args?.save_to_dir
                    ? assertSafeLocalMediaCandidate(expandHome(String(args.save_to_dir)))
                    : path.join(getOdinLocalHome(), "ai_outputs", jobId);
                await fs.promises.mkdir(defaultOutDir, { recursive: true });

                const localPaths = [];
                for (let i = 0; i < data.items.length; i++) {
                    const it = data.items[i];
                    if (it.status !== "done" || !it.downloadUrl) continue;
                    let destFile;
                    if (args?.save_to_path && data.items.length === 1) {
                        destFile = assertSafeLocalMediaCandidate(expandHome(String(args.save_to_path)));
                    } else {
                        const cleanName = String(it.filename || `item_${i + 1}.mp4`).replace(/[^a-zA-Z0-9._-]/g, "_");
                        destFile = path.join(defaultOutDir, cleanName);
                    }
                    await downloadAuthorizedFileToDisk(it.downloadUrl, destFile, apiKey);
                    it.localPath = destFile;
                    localPaths.push(destFile);
                }
                data.localOutputDir = defaultOutDir;
                data.localPaths = localPaths;
                if (localPaths.length === 1) {
                    data.savedToLocalFile = localPaths[0];
                }
            } else if (args?.save_to_path && data.downloadUrl) {
                const targetFile = resolveSafeMp4Output(args.save_to_path, jobId);
                await downloadAuthorizedFileToDisk(data.downloadUrl, targetFile, apiKey);
                data.savedToLocalFile = targetFile;
            }
            return data;
        }

        if (data.status === "failed") {
            return data;
        }

        await new Promise((r) => setTimeout(r, intervalMs));
    }

    return {
        ...(latest || { jobId }),
        timedOutWaiting: true,
        note: "El trabajo sigue procesándose en la nube de OdinxD. Vuelve a ejecutar get_render_status o wait_for_render en unos segundos.",
    };
}

function getOdinLocalHome() {
    const custom = (process.env.ODINXD_HOME || "").trim();
    const dir = custom ? expandHome(custom) : path.join(os.homedir(), ".odinxd");
    fs.mkdirSync(dir, { recursive: true });
    return dir;
}

async function resolvePreprodEngineScript() {
    const bundled = path.resolve(__dirname, "..", "scripts", "odin_preprod.py");
    if (fs.existsSync(bundled)) {
        return bundled;
    }
    const sibling = path.resolve(__dirname, "odin_preprod.py");
    if (fs.existsSync(sibling)) {
        return sibling;
    }

    // Fallback when user downloaded standalone odinxd-mcp.mjs directly: fetch & cache official script over HTTPS
    const cacheBinDir = path.join(getOdinLocalHome(), "bin");
    await fs.promises.mkdir(cacheBinDir, { recursive: true });
    const cachedScript = path.join(cacheBinDir, "odin_preprod.py");
    if (!fs.existsSync(cachedScript)) {
        const dlUrl = `${CLI_CONFIG.apiUrl}/mcp/odin_preprod.py`;
        const res = await fetch(dlUrl);
        if (!res.ok) {
            throw new Error(`No se encontró 'odin_preprod.py' localmente ni pudo descargarse desde ${dlUrl} (HTTP ${res.status}).`);
        }
        const scriptText = await res.text();
        await fs.promises.writeFile(cachedScript, scriptText, "utf-8");
    }
    return cachedScript;
}

function findPythonInterpreter() {
    const homeDir = getOdinLocalHome();
    const managedWin = path.join(homeDir, "preprod_env", "Scripts", "python.exe");
    const managedPosix = path.join(homeDir, "preprod_env", "bin", "python");
    if (process.platform === "win32" && fs.existsSync(managedWin)) {
        return { cmd: managedWin, prefixArgs: [] };
    }
    if (process.platform !== "win32" && fs.existsSync(managedPosix)) {
        return { cmd: managedPosix, prefixArgs: [] };
    }
    if (process.platform === "win32") {
        return { cmd: "python", prefixArgs: [] };
    }
    return { cmd: "python3", prefixArgs: [] };
}

function spawnPythonPreprod(scriptPath, cliArgs, timeoutMs = 900000) {
    const candidates =
        process.platform === "win32"
            ? [findPythonInterpreter(), { cmd: "py", prefixArgs: ["-3"] }, { cmd: "python3", prefixArgs: [] }]
            : [findPythonInterpreter(), { cmd: "python", prefixArgs: [] }];

    return new Promise((resolve, reject) => {
        let attemptIdx = 0;

        const tryNext = () => {
            if (attemptIdx >= candidates.length) {
                reject(
                    new Error(
                        "PYTHON_NOT_FOUND: Python 3 es necesario para ejecutar la suite de preproducción local (Whisper / yt-dlp / OpenCV). Instálalo desde https://python.org o mediante 'winget install Python.Python.3.12' / 'brew install python'."
                    )
                );
                return;
            }

            const { cmd, prefixArgs } = candidates[attemptIdx++];
            const child = spawn(cmd, [...prefixArgs, scriptPath, ...cliArgs], {
                stdio: ["ignore", "pipe", "pipe"],
                windowsHide: true,
            });

            let stdout = "";
            let stderr = "";
            let settled = false;

            const timer = setTimeout(() => {
                if (!settled) {
                    settled = true;
                    child.kill("SIGKILL");
                    reject(new Error(`LOCAL_PREPROD_TIMEOUT: La operación local superó el límite de ${Math.round(timeoutMs / 1000)}s.`));
                }
            }, timeoutMs);

            child.stdout.on("data", (chunk) => {
                stdout += chunk.toString("utf-8");
            });
            child.stderr.on("data", (chunk) => {
                stderr += chunk.toString("utf-8");
            });

            child.on("error", (err) => {
                clearTimeout(timer);
                if (settled) return;
                if (err && err.code === "ENOENT") {
                    tryNext();
                    return;
                }
                settled = true;
                reject(err);
            });

            child.on("close", (code) => {
                clearTimeout(timer);
                if (settled) return;
                settled = true;
                const trimmed = stdout.trim();
                let parsed = null;
                try {
                    parsed = trimmed ? JSON.parse(trimmed) : null;
                } catch {
                    parsed = null;
                }
                if (code === 0 && parsed) {
                    resolve({ isError: false, data: parsed });
                } else if (parsed && parsed.error) {
                    resolve({ isError: true, data: parsed });
                } else {
                    resolve({
                        isError: true,
                        data: {
                            error: stderr.trim() || trimmed || `odin_preprod.py exited with code ${code}`,
                        },
                    });
                }
            });
        };

        tryNext();
    });
}

async function handleLocalPreprodTool(toolName, rawArgs) {
    const scriptPath = await resolvePreprodEngineScript();
    const args = rawArgs && typeof rawArgs === "object" ? rawArgs : {};
    const autoInstall = args.auto_install !== undefined ? Boolean(args.auto_install) : toolName !== "local_preprod_doctor";

    if (toolName === "local_preprod_doctor") {
        const cli = ["doctor"];
        if (args.auto_install) cli.push("--install");
        return spawnPythonPreprod(scriptPath, cli, 600000);
    }

    if (toolName === "transcribe_local_media") {
        const inputs = Array.isArray(args.input_paths) ? args.input_paths.map((p) => expandHome(String(p))).filter(Boolean) : [];
        if (inputs.length === 0) {
            throw new Error("MISSING_INPUT_PATHS: Pasa al menos un archivo en 'input_paths'.");
        }
        for (const p of inputs) assertSafeLocalMediaCandidate(p);
        const cli = ["transcribe", "--inputs", ...inputs];
        if (args.model) cli.push("--model", String(args.model));
        if (args.language) cli.push("--language", String(args.language));
        if (args.min_silence_sec !== undefined) cli.push("--min-silence", String(Number(args.min_silence_sec)));
        if (autoInstall) cli.push("--auto-install");
        return spawnPythonPreprod(scriptPath, cli, 900000);
    }

    if (toolName === "clean_and_merge_aroll") {
        const cli = ["clean-aroll"];
        const inputs = Array.isArray(args.input_paths) ? args.input_paths.map((p) => expandHome(String(p))).filter(Boolean) : [];
        for (const p of inputs) assertSafeLocalMediaCandidate(p);
        if (inputs.length > 0) {
            cli.push("--inputs", ...inputs);
        }
        if (Array.isArray(args.segments) && args.segments.length > 0) {
            const normSegs = args.segments.map((s) => {
                const fileRef = s.file ? expandHome(String(s.file)) : inputs[0] || "";
                if (fileRef) assertSafeLocalMediaCandidate(fileRef);
                return {
                    file: fileRef,
                    start: Number(s.start),
                    end: Number(s.end),
                };
            });
            cli.push("--segments-json", JSON.stringify(normSegs));
        }
        if (args.output_path) {
            const outResolved = expandHome(String(args.output_path));
            assertSafeLocalMediaCandidate(outResolved);
            cli.push("--output", outResolved);
        }
        if (args.min_silence_sec !== undefined) cli.push("--min-silence", String(Number(args.min_silence_sec)));
        if (args.silence_db !== undefined) cli.push("--silence-db", String(Number(args.silence_db)));
        if (args.smart_reframe === false) cli.push("--no-smart-reframe");
        if (autoInstall) cli.push("--auto-install");
        return spawnPythonPreprod(scriptPath, cli, 900000);
    }

    if (toolName === "extract_podcast_clips") {
        const action = String(args.action || "").trim();
        const rawSource = String(args.source || "").trim();
        if (!rawSource) throw new Error("MISSING_SOURCE: El parámetro 'source' es obligatorio.");
        const resolvedSource = /^https?:\/\//i.test(rawSource) ? rawSource : expandHome(rawSource);
        if (!/^https?:\/\//i.test(resolvedSource)) {
            assertSafeLocalMediaCandidate(resolvedSource);
        }
        const cli = ["podcast", "--action", action, "--source", resolvedSource];
        if (Array.isArray(args.clips) && args.clips.length > 0) {
            cli.push("--clips-json", JSON.stringify(args.clips));
        }
        if (args.output_dir) {
            const outDir = expandHome(String(args.output_dir));
            assertSafeLocalMediaCandidate(outDir);
            cli.push("--output-dir", outDir);
        }
        if (args.model) cli.push("--model", String(args.model));
        if (args.language) cli.push("--language", String(args.language));
        if (autoInstall) cli.push("--auto-install");
        return spawnPythonPreprod(scriptPath, cli, 1200000);
    }

    if (toolName === "manage_local_stock_bank") {
        const action = String(args.action || "").trim();
        const cli = ["stock-bank", "--action", action];
        if (args.source) {
            const src = expandHome(String(args.source));
            assertSafeLocalMediaCandidate(src);
            cli.push("--source", src);
        }
        if (args.query) cli.push("--query", String(args.query));
        if (args.category) cli.push("--category", String(args.category));
        if (args.tags) cli.push("--tags", String(args.tags));
        if (args.description) cli.push("--description", String(args.description));
        if (args.clip_id) cli.push("--clip-id", String(args.clip_id));
        if (args.clip_duration !== undefined) cli.push("--clip-duration", String(Number(args.clip_duration)));
        if (args.max_clips_per_video !== undefined) cli.push("--max-clips-per-video", String(Number(args.max_clips_per_video)));
        if (args.limit !== undefined) cli.push("--limit", String(Number(args.limit)));
        if (autoInstall) cli.push("--auto-install");
        return spawnPythonPreprod(scriptPath, cli, 900000);
    }

    if (toolName === "generate_local_voiceover") {
        const text = String(args.text || "").trim();
        if (!text) throw new Error("MISSING_TEXT: El parámetro 'text' es obligatorio.");
        const cli = ["voiceover", "--text", text];
        if (args.voice) cli.push("--voice", String(args.voice));
        if (args.rate) cli.push("--rate", String(args.rate));
        if (args.output_path) {
            const outMp3 = expandHome(String(args.output_path));
            assertSafeLocalMediaCandidate(outMp3);
            cli.push("--output", outMp3);
        }
        if (autoInstall) cli.push("--auto-install");
        return spawnPythonPreprod(scriptPath, cli, 300000);
    }

    if (toolName === "assemble_local_timeline") {
        const rawClips = Array.isArray(args.clip_paths) ? args.clip_paths : [];
        const clips = rawClips.map((p) => expandHome(String(p))).filter(Boolean);
        if (clips.length === 0) {
            throw new Error("MISSING_CLIP_PATHS: Pasa al menos un clip MP4 en 'clip_paths'.");
        }
        for (const p of clips) assertSafeLocalMediaCandidate(p);
        const cli = ["assemble", "--clips", ...clips];
        if (args.output_path) {
            const outMp4 = expandHome(String(args.output_path));
            assertSafeLocalMediaCandidate(outMp4);
            cli.push("--output", outMp4);
        }
        if (args.aspect_ratio) cli.push("--aspect-ratio", String(args.aspect_ratio));
        if (args.audio_mode) cli.push("--audio-mode", String(args.audio_mode));
        if (args.voiceover_path) {
            const vo = expandHome(String(args.voiceover_path));
            assertSafeLocalMediaCandidate(vo);
            cli.push("--voiceover", vo);
        }
        if (args.bg_music_path) {
            const bgm = expandHome(String(args.bg_music_path));
            assertSafeLocalMediaCandidate(bgm);
            cli.push("--bg-music", bgm);
        }
        if (args.sfx_volume !== undefined) cli.push("--sfx-volume", String(Number(args.sfx_volume)));
        if (args.music_volume !== undefined) cli.push("--music-volume", String(Number(args.music_volume)));
        if (args.transition) cli.push("--transition", String(args.transition));
        if (args.subtitles) cli.push("--subtitles", String(args.subtitles));
        if (args.srt_path) {
            const srt = expandHome(String(args.srt_path));
            assertSafeLocalMediaCandidate(srt);
            cli.push("--srt-file", srt);
        }
        if (args.subtitle_preset) cli.push("--subtitle-preset", String(args.subtitle_preset));
        if (args.language) cli.push("--language", String(args.language));
        if (autoInstall) cli.push("--auto-install");
        return spawnPythonPreprod(scriptPath, cli, 900000);
    }

    throw new Error(`Unknown local pre-production tool: ${toolName}`);
}

async function forwardRemoteRpc(method, params, id = 1) {
    const apiKey = requireApiKey();
    const res = await fetch(`${CLI_CONFIG.apiUrl}/api/mcp`, {
        method: "POST",
        headers: {
            Authorization: `Bearer ${apiKey}`,
            "Content-Type": "application/json",
            Accept: "application/json",
        },
        body: JSON.stringify({
            jsonrpc: "2.0",
            id,
            method,
            params: params || {},
        }),
    });

    const data = await res.json().catch(() => null);
    if (!res.ok) {
        const msg = data?.error?.message || data?.error || `HTTP ${res.status} al conectar con ${CLI_CONFIG.apiUrl}/api/mcp`;
        throw new Error(msg);
    }
    if (data?.error) {
        throw new Error(data.error.message || JSON.stringify(data.error));
    }
    return data?.result;
}

async function handleRpcMessage(msg) {
    if (!msg || typeof msg !== "object" || msg.jsonrpc !== "2.0") {
        return {
            jsonrpc: "2.0",
            id: msg?.id ?? null,
            error: { code: -32600, message: "Invalid JSON-RPC 2.0 Request" },
        };
    }

    if (msg.id === undefined) {
        // JSON-RPC notification (e.g. notifications/initialized) -> no output
        return null;
    }

    const { id, method, params = {} } = msg;

    try {
        switch (method) {
            case "initialize": {
                const requested = String(params.protocolVersion || "");
                const negotiated = SUPPORTED_VERSIONS.has(requested) ? requested : "2025-03-26";
                return {
                    jsonrpc: "2.0",
                    id,
                    result: {
                        protocolVersion: negotiated,
                        capabilities: {
                            tools: { listChanged: false },
                            resources: { subscribe: false, listChanged: false },
                            prompts: { listChanged: false },
                        },
                        serverInfo: {
                            name: "odinxd-mcp",
                            version: SERVER_VERSION,
                        },
                        instructions:
                            "Puente MCP Oficial + Estudio Creativo y Preproducción Local de OdinxD v2.2 (https://odinxd.com/docs). " +
                            "APIS GENERATIVAS IA ATÓMICAS (SOLO CRÉDITOS IA, 0 RENDERS DESCONTADOS, 0 LLMs DE ODINXD): 'generate_ai_image' (1 crédito/img con gemini-2.5-flash-image: compone las 4 combinaciones UGC de avatar+producto o retratos de casting) y 'generate_ai_video_clip' / 'generate_ai_video_batch' (3s-15s con gemini-omni-1.2-flash: 1 crédito/s sin referencias, 2 créditos/s con referencias, con voces consistentes en inglés 'Aoede'/'Zephyr'/'Kore'/'Puck'/'Charon' y huellas acústicas en español). " +
                            "MOTOR DE MONTAJE Y PREPRODUCCIÓN LOCAL (0 CRÉDITOS, $0 COSTE SERVIDOR): 'generate_local_voiceover', 'assemble_local_timeline', 'transcribe_local_media', 'clean_and_merge_aroll', 'extract_podcast_clips' y 'manage_local_stock_bank'. Permite producir anuncios UGC largos (30s-60s+), Comerciales Faceless Cinematográficos y Microdramas uniendo las escenas gratis en el PC del usuario, o limpiar A-Rolls antes de los 6 modos de render en la nube de OdinxD. " +
                            "PROHIBIDO usar rostros de figuras públicas o celebridades; usa siempre creadores privados o genera avatares sintéticos originales con 'generate_ai_image'.",
                    },
                };
            }

            case "ping":
                return { jsonrpc: "2.0", id, result: {} };

            case "tools/list": {
                if (!CLI_CONFIG.apiKey) {
                    return { jsonrpc: "2.0", id, result: { tools: OFFLINE_FALLBACK_TOOLS } };
                }
                try {
                    const remoteResult = await forwardRemoteRpc("tools/list", {}, id);
                    const remoteTools = Array.isArray(remoteResult?.tools) ? remoteResult.tools : OFFLINE_FALLBACK_TOOLS;
                    const hasWait = remoteTools.some((t) => t.name === "wait_for_render");
                    const enhancedTools = remoteTools.map((t) => ({
                        ...t,
                        description: `${t.description} (Soporta rutas locales de tu PC además de URLs https://)`,
                    }));
                    if (!hasWait) enhancedTools.push(WAIT_TOOL_SCHEMA);
                    for (const lt of LOCAL_PREPROD_TOOLS) {
                        if (!enhancedTools.some((t) => t.name === lt.name)) {
                            enhancedTools.push(lt);
                        }
                    }
                    return { jsonrpc: "2.0", id, result: { tools: enhancedTools } };
                } catch {
                    return { jsonrpc: "2.0", id, result: { tools: OFFLINE_FALLBACK_TOOLS } };
                }
            }

            case "tools/call": {
                const toolName = String(params.name || "");
                const rawArgs = params.arguments || {};

                if (toolName === "wait_for_render") {
                    const waitData = await handleWaitForRender(rawArgs);
                    return {
                        jsonrpc: "2.0",
                        id,
                        result: {
                            isError: waitData.status === "failed",
                            content: [{ type: "text", text: JSON.stringify(waitData, null, 2) }],
                        },
                    };
                }

                if (LOCAL_PREPROD_TOOL_NAMES.has(toolName)) {
                    const localRes = await handleLocalPreprodTool(toolName, rawArgs);
                    return {
                        jsonrpc: "2.0",
                        id,
                        result: {
                            isError: Boolean(localRes.isError),
                            content: [{ type: "text", text: JSON.stringify(localRes.data, null, 2) }],
                        },
                    };
                }

                const resolvedArgs = await resolveToolFileArguments(rawArgs);
                const remoteCallResult = await forwardRemoteRpc(
                    "tools/call",
                    { name: toolName, arguments: resolvedArgs },
                    id
                );

                const isAtomicAiTool =
                    toolName === "generate_ai_image" ||
                    toolName === "generate_ai_video_clip" ||
                    toolName === "generate_ai_video_batch";

                if (isAtomicAiTool && !remoteCallResult?.isError && rawArgs.wait !== false) {
                    let parsedQueued = null;
                    try {
                        const firstText = remoteCallResult?.content?.[0]?.text;
                        parsedQueued = firstText ? JSON.parse(firstText) : null;
                    } catch {
                        parsedQueued = null;
                    }
                    if (parsedQueued?.jobId) {
                        const pollSec = toolName === "generate_ai_image" ? 3 : 6;
                        const completedData = await handleWaitForRender({
                            job_id: parsedQueued.jobId,
                            poll_interval_seconds: pollSec,
                            max_wait_seconds: 540,
                            save_to_path: rawArgs.save_to_path,
                            save_to_dir: rawArgs.save_to_dir,
                        });
                        return {
                            jsonrpc: "2.0",
                            id,
                            result: {
                                isError: completedData.status === "failed",
                                content: [{ type: "text", text: JSON.stringify(completedData, null, 2) }],
                            },
                        };
                    }
                }

                return {
                    jsonrpc: "2.0",
                    id,
                    result: remoteCallResult,
                };
            }

            case "resources/list":
            case "resources/read":
            case "prompts/list":
            case "prompts/get": {
                if (!CLI_CONFIG.apiKey) {
                    if (method.endsWith("/list")) {
                        const key = method.startsWith("resources") ? "resources" : "prompts";
                        return { jsonrpc: "2.0", id, result: { [key]: [] } };
                    }
                }
                const remoteRes = await forwardRemoteRpc(method, params, id);
                return { jsonrpc: "2.0", id, result: remoteRes };
            }

            default:
                return {
                    jsonrpc: "2.0",
                    id,
                    error: { code: -32601, message: `Method not found: ${method}` },
                };
        }
    } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        if (method === "tools/call") {
            return {
                jsonrpc: "2.0",
                id,
                result: {
                    isError: true,
                    content: [{ type: "text", text: JSON.stringify({ error: message }, null, 2) }],
                },
            };
        }
        return {
            jsonrpc: "2.0",
            id,
            error: { code: -32603, message },
        };
    }
}

function sendStdout(payload) {
    if (!payload) return;
    process.stdout.write(`${JSON.stringify(payload)}\n`);
}

const rl = readline.createInterface({
    input: process.stdin,
    crlfDelay: Infinity,
    terminal: false,
});

async function processSingleLine(line) {
    const trimmed = line.trim();
    if (!trimmed) return;

    let parsed;
    try {
        parsed = JSON.parse(trimmed);
    } catch {
        sendStdout({
            jsonrpc: "2.0",
            id: null,
            error: { code: -32700, message: "Parse error: invalid JSON" },
        });
        return;
    }

    if (Array.isArray(parsed)) {
        if (parsed.length === 0 || parsed.length > MAX_STDIO_BATCH) {
            sendStdout({
                jsonrpc: "2.0",
                id: null,
                error: { code: -32600, message: `Invalid JSON-RPC batch size (1-${MAX_STDIO_BATCH} allowed)` },
            });
            return;
        }
        const responses = [];
        for (const item of parsed) {
            const r = await handleRpcMessage(item);
            if (r) responses.push(r);
        }
        if (responses.length > 0) sendStdout(responses);
    } else {
        const res = await handleRpcMessage(parsed);
        if (res) sendStdout(res);
    }
}

let rpcQueue = Promise.resolve();

rl.on("line", (line) => {
    rpcQueue = rpcQueue.then(() => processSingleLine(line)).catch((err) => {
        process.stderr.write(`[odinxd-mcp] Unexpected queue error: ${err?.message || err}\n`);
    });
});
