---
name: odin-video-preproduction
description: Local AI video pre-production & assembly studio for OdinxD (https://odinxd.com). Use when the user has raw video takes with silences or spoken mistakes/retakes, wants to extract vertical 9:16 viral clips from a long podcast or YouTube video, wants to build/search a personal local B-Roll stock bank (~/.odinxd/stock_bank), or wants to assemble voiceovers/AI clips locally before or instead of rendering in OdinxD Cloud.
---

# OdinMCP Local Video Pre-Production, Assembler & Cloud Render Skill (`v2.2`)

You have **three complementary superpowers** when producing videos with **OdinMCP (`v2.2`)**:
1. **100% Local Pre-Production & Timeline Mastering (`0` cloud credits, runs on the user's machine):** Cut dead air, remove spoken mistakes/false starts across multiple raw takes, reframe `16:9` podcasts into face-centered `9:16` clips, build a reusable local B-Roll stock bank (`~/.odinxd/stock_bank`), generate free neural voiceovers (`generate_local_voiceover`), and master multi-clip timelines (`assemble_local_timeline`).
2. **OdinxD Atomic Generative Media APIs (`ai_credits` only, `0` cloud renders consumed):** Generate or composite avatars, products, casting sheets, and `3s–15s` Lip-Sync / cinematic clips via `generate_ai_image`, `generate_ai_video_clip`, and `generate_ai_video_batch` *(see sibling skills: **`odin-ugc-factory`**, **`odin-cinematic-faceless`**, and **`odin-microdrama-director`**)*.
3. **OdinxD Cloud Studio Rendering (`https://odinxd.com`):** Turn clean `9:16` A-Roll MP4s into finished studio reels using **ViralBeat 2.0**, **Hybrid AI B-Roll (20 styles)**, **Faceless AI Ads**, **Motion Stock**, **Maxy Overlay**, or **Fitness Talking-Head**.

---

## 0. First-Time Local Environment Check

Before running Whisper transcription, podcast downloads, scene detection, or local neural voiceovers for the first time on a machine, call:
- **MCP Tool:** `local_preprod_doctor` with `{"auto_install": true}`
- *(Or CLI fallback if running scripts directly)*: `python "<path-to-OdinMCP>/scripts/odin_preprod.py" doctor --install`

This provisions an isolated, lightweight environment in `~/.odinxd/preprod_env` (`faster-whisper` int8, `yt-dlp`, `opencv-python-headless`, `scenedetect`, `edge-tts`) without touching global Python packages, and verifies `ffmpeg` + `ffprobe`.

---

## Workflow 1 — Clean Raw A-Roll (Silences + Spoken Mistakes + Multi-Take Merge)

> **Golden Rule:** OdinxD Cloud (`render_hybrid_reel`, `render_viral_beat`, `render_motion_stock`, etc.) **NEVER** cuts silences/mistakes and **NEVER** merges multiple base videos. Always produce **ONE clean `.mp4`** locally first!

### Mode A: Smart Mistake & Retake Removal (Recommended whenever the speaker stumbles or repeats takes)
1. Call **`transcribe_local_media`** passing `input_paths: ["take1.mp4", "take2.mp4"]` and `auto_install: true`.
2. Read the returned `segments` and word-level `[start, end]` timestamps carefully:
   - Drop false starts, stutters, filler words (*"ehhh"*, *"sorry let me repeat that"*), and repeated sentences (keep only the strongest take!).
   - Keep natural sentence boundaries (`~0.10s` margin before first word and after last word).
3. Call **`clean_and_merge_aroll`** passing your curated `segments: [{"file": "...", "start": ..., "end": ...}]`.
   - The engine normalizes every segment to `1080x1920 @ 30fps`, centers on the speaker's face if horizontal, applies `25ms` anti-pop audio micro-fades at every cut, and normalizes loudness to `-16 LUFS`.
4. Pass the resulting `outputMp4` directly as `video_url` into `render_hybrid_reel`, `render_viral_beat`, `render_motion_stock`, `render_maxy_overlay`, or `render_fitness_talking_head`!

### Mode B: Fast Automatic Dead-Air Removal (When the take has pauses but no spoken retakes)
1. Call **`clean_and_merge_aroll`** directly with `input_paths: ["raw_video.mp4"]` (omit `segments`).
2. It automatically strips silences (`>= 0.65s` below `-35 dB`) while preserving natural `0.12s` breath padding and outputs a single normalized `1080x1920` `.mp4`.

---

## Workflow 2 — Podcast / Long Video to Viral 9:16 Reels

1. **Analyze the Episode:** Call **`extract_podcast_clips`** with `action: "analyze"`, `source: "<local_file_or_public_video_url>"`, and `auto_install: true`.
   - Reads the local video (or caches the URL via `yt-dlp` into `~/.odinxd/podcast_cache/`) and returns timestamped 30s blocks + exact sentence segments.
2. **Select Viral Hooks (Editorial Judgment):**
   - Pick **3 to 5 self-contained hooks** (`25s` to `55s` each; check `get_account_quota` first — free accounts support up to `30s`, unlocked/paid accounts up to `60s`).
   - Every clip must open with a strong curiosity/contrarian statement in the first 3 seconds and end on a clean sentence conclusion.
3. **Extract & Auto-Reframe 9:16:** Call **`extract_podcast_clips`** with `action: "extract"`, `source`, and `clips: [{"start": 412.4, "end": 456.8, "title": "hook_1"}]`.
   - Automatically centers `16:9` horizontal podcasts onto the speaker's face using stabilized OpenCV face detection (zero camera jitter).
4. **Render in OdinxD Cloud (CRITICAL Celebrity Rule):**
   - **NEVER** use `avatar_stock`, `ugc_stock`, or `inmo_avatar_stock` and **NEVER** pass celebrity/public-figure faces in `avatar_image` (AI video safety filters block prominent individuals!).
   - For third-party podcasts or famous speakers, ALWAYS select faceless cinematic/editorial styles: `["stock_hyperreal", "scrapbook_polaroid"]`, `["cinematic_macro", "vox_editorial"]`, or `["parallax_3d", "mannequin_3d"]`, with `subtitle_style: "kinetic_dinamic"` or `"kinetic_blur"`.

---

## Workflow 3 — Build & Reuse Personal Local Stock Bank (`~/.odinxd/stock_bank`)

Help users turn their own camera roll (property walkthroughs, travel, gym, workspace, product shots) into a free reusable B-Roll library:

1. **Ingest Raw Footage:** Call **`manage_local_stock_bank`** with `action: "ingest"`, `source: "<video_or_folder_path>"`, `category: "real_estate"` (or `"lifestyle"`, `"gym"`, `"product"`, `"tech"`), and initial `tags`.
   - `PySceneDetect` (or FFmpeg scene-cut fallback) slices clean `3.5s–5.0s` muted `1080x1920` `.mp4` clips + `.jpg` thumbnails into `~/.odinxd/stock_bank/`.
2. **Visual Tagging (Optional Superpower):** Inspect the generated `thumbnailPath` `.jpg` files with your file-viewing tool to see what is inside each shot, then call **`manage_local_stock_bank`** with `action: "tag"`, `clip_id`, `tags`, and `description`.
3. **Search & Inject Free Custom Stock into Renders:** Before launching `render_hybrid_reel` or `render_viral_beat`, call **`manage_local_stock_bank`** with `action: "search"` and `query: "..."`. Pass the returned `customStockParam` (`"path1.mp4,path2.mp4,..."`, up to 6 clips) into `custom_stock`!

---

## Workflow 4 — Local Voiceover & Multi-Clip Timeline Mastering (`0` Cloud Cost)

When assembling multi-take AI UGC ads (`odin-ugc-factory`), Cinematic Faceless commercials (`odin-cinematic-faceless`), or serialized AI Microdramas (`odin-microdrama-director`) locally on the user's PC:
1. **`generate_local_voiceover`**: Synthesizes free neural `.mp3` narration + synchronized `.srt` captions via `edge-tts` in Spanish or English (`0` credits).
2. **`assemble_local_timeline`**: Concatenates `1..N` `.mp4` clips into a broadcast-ready `1080x1920` (or `1920x1080`) `@ 30fps` master (`-16 LUFS`), supporting `audio_mode: "keep_native"` (Lip-Sync dialogue) or `"voiceover_master"` (narration + `-18 dB` ducked clip foley), optional `bg_music_path`, and clean burned-in subtitles (`auto_whisper` or `srt` with `ugc_clean`, `cinema_yellow`, `boxed_impact`, or `minimal_luxury` presets).

---

## Art Direction Defaults for OdinxD Cloud Renders

- **Podcast / Authority / Business:** `render_hybrid_reel` or `render_viral_beat` • `typography: "Montserrat"` • `subtitle_style: "kinetic_dinamic"` or `"kinetic_blur"`.
- **Luxury Real Estate:** `render_hybrid_reel` • `ai_styles: ["inmo_avatar_stock", "inmo_tour_transition"]` (private agent) or `["inmo_tour", "inmo_tour_transition"]` (no people) • `typography: "Playfair Display"` • `subtitle_style: "kinetic_blur"`.
- **E-Commerce / Physical Product UGC:** `render_hybrid_reel` (`ai_styles: ["ugc_stock", "cinematic_macro"]`) or `odin-ugc-factory` (`generate_ai_image` + `generate_ai_video_batch`) • `typography: "Poppins"` • `subtitle_style: "kinetic_dinamic"`.
- **Tech / AI / SaaS:** `render_viral_beat` or `render_hybrid_reel` • `ai_styles: ["ui_interface_dark", "cyber_blueprint", "dark_glassmorphism"]` • `typography: "Space Grotesk"` • `subtitle_style: "kinetic_dinamic"` or `"glow_neon_cyber"`.
- **Fitness / Pure Talking-Head (0 AI Credits):** `render_fitness_talking_head` • `typography: "Bebas Neue"` • `subtitle_style: "boxed_highlighter"`.
