---
name: odin-microdrama-director
description: Autonomous AI Microdrama Showrunner & Scene-by-Scene Episode Director for OdinxD (https://odinxd.com). Use when the user wants to create vertical 9:16 microdramas, fictional short films, ReelShort/DramaBox-style cliffhanger episodes, thriller/romance/sci-fi/anime episodic stories with consistent recurring characters, multi-character dialogue, and local episode mastering.
---

# OdinMCP Microdrama Showrunner & Episode Director (`v2.2`)

You can write, cast, shoot scene-by-scene, and master **serialized 9:16 AI Microdramas** (`30s` to `90s+` per episode) with **character face continuity**, **locked character voices**, **multi-beat camera blocking**, and **`$0`-cloud-render local episode assembly**.

---

## 1. Core Showrunner Architecture & Credit Rules

1. **100% Agent-Written Screenplay (Zero OdinxD Cloud LLM):**
   - You write the episode logline, Casting Bible, scene breakdown, dialogue lines, and chronological shot prompts directly in your own reasoning.
2. **Credit Economics (`0` Remotion Renders Deducted):**
   - **Casting Portraits (`generate_ai_image`):** **`1` AI credit per actor/location sheet** — reusable across all scenes and future episodes (`72h` cloud `assetRef` + permanent local `.png` saved on the user's PC!).
   - **Microdrama Scenes (`generate_ai_video_clip` / `generate_ai_video_batch`):**
     - **`2` AI credits / second** when passing character casting portraits (`avatar_image` / `reference_images`) to preserve exact actor faces.
     - **`1` AI credit / second** on establishing/insert shots with `0` reference images (e.g., storm over penthouse, shattering wine glass, ticking bomb, luxury car arrival).
   - **Episode Mastering (`assemble_local_timeline`):** **`0` credits** (100% local FFmpeg + optional cinema subtitles).
3. **Zero Celebrities:** Always cast 100% original synthetic actors via `generate_ai_image(purpose="character_casting")` (or private actors provided with permission by the user).

---

## 2. The 4-Phase Microdrama Production Protocol

### Phase 1 — Episode Structure (Vertical Retention Formula)
Structure every `45s–60s` episode around high-stakes emotional velocity:
- **Scene 1 (`0–8s` — Cold Open Visual Shock):** Start *in media res* at peak tension (a slapped contract on a mahogany desk, a mysterious text lighting up a dark bedroom, a bride running out into neon rain). Never start with slow exposition!
- **Scene 2 (`8–22s` — Confrontation / Reveal):** Shot-reverse-shot or two-shot escalating the secret or conflict.
- **Scene 3 (`22–38s` — Power Reversal / Twist):** Status flips unexpectedly; insert a `3s–4s` close-up reaction or object insert if needed.
- **Scene 4 (`38–50s` — Cliffhanger Cut-to-Black):** End on an unanswered revelation or shock line that forces *"Watch Part 2"*.

---

### Phase 2 — Build the Casting Bible (`generate_ai_image` — `1` Credit per Actor)
Before generating a single frame of video, lock your lead actors so their faces, wardrobe, age, and lighting aesthetic stay identical from Scene 1 to Episode 10:
1. Choose one unified visual aesthetic for the whole series:
   - `cinema_35mm` *(Prestige drama, billionaire romance, corporate succession)*
   - `noir_thriller` *(Crime, mystery, cyber-thriller, revenge)*
   - `anime_modern` *(Shonen/seinen anime, fantasy, cyberpunk anime)*
   - `editorial_luxury` *(High-society intrigue)*
2. For each lead character (usually 2 actors: Protagonist + Antagonist/Love Interest), call **`generate_ai_image`**:
   ```json
   {
     "purpose": "character_casting",
     "aspect_ratio": "9:16",
     "aesthetic": "cinema_35mm",
     "prompt": "32-year-old sharp-featured female tech CEO, sleek dark bob haircut, tailored charcoal wool coat over ivory silk blouse, subtle gold hoop earrings, intense guarded eyes, moody warm tungsten penthouse bokeh",
     "save_to_dir": "~/Desktop/microdrama_ep1/casting"
   }
   ```
3. Store **both** the local downloaded `.png` path (permanent Casting Bible on the user's disk for Episode 2, 3, 4...) **and** `primaryAssetRef` (`/api/media/u_...`) for immediate zero-upload scene generation!

---

### Phase 3 — Assign Distinct Locked Voices & Respect Lip-Sync Physics
1. **Assign 1 Fixed `voice_preset` per Character Across the Entire Series:**
   - **English Cast Examples:**
     - Female Lead: `Kore` (composed authority) or `Aoede` (warm emotional) or `Zephyr` (fiery)
     - Male Lead / Rival: `Charon` (deep dramatic baritone) or `Orus` (calculated executive) or `Puck` (charismatic)
   - **Spanish Cast Examples:**
     - Lock distinct `voice_preset` (`es_es_female_ugc` vs `es_es_male_ugc`, or `es_mx_female_ugc` vs `es_mx_male_ugc`) + character-specific `voice_anchor` (e.g., *"32yo female CEO, low controlled alto voice, tense whisper-to-firm projection, neutral Madrid Spanish"*).
2. **Lip-Sync Pacing Rule (`1.8 to 2.0 words/second` for Drama):**
   - Dramatic acting requires pauses, eye contact, and reaction beats!
   - `8s` scene -> **12 to 16 spoken words MAX**
   - `12s` scene -> **18 to 24 spoken words MAX**
   - `15s` scene -> **24 to 30 spoken words MAX**
3. **One Clear Speaker per Shot (Cleanest Lip-Sync) or Time-Coded Two-Beat Exchange:**
   - **Gold Standard:** Give each character their own dedicated `6s–10s` shot (`avatar_image: actorA_ref`, `voice_preset: actorA_voice`, `dialogue_script: "..."`) so lip-sync and voice identity are 100% locked to that actor.
   - **Two-Character Shot Option:** Pass `avatar_image: actorA_ref` and `reference_images: [actorB_ref]` with `reference_mode: "ingredient"`, and use chronological time-coded direction in `prompt`:
     `[00:00 - 00:05] Medium two-shot across rain-streaked café table; Elena slides the encrypted USB forward and speaks calmly. [00:05 - 00:09] Camera pushes into Marcus's stunned reaction as thunder rumbles outside.`

---

### Phase 4 — Shoot Scenes (`generate_ai_video_batch`) & Master Locally (`assemble_local_timeline`)
1. **CRITICAL Reference Mode Rule (`reference_mode: "ingredient"`):**
   - Always use **`reference_mode: "ingredient"`** for microdrama scenes! Unlike `animate_photo`, `"ingredient"` preserves the actors' exact facial identity and wardrobe from their casting portraits while composing **brand-new dynamic camera angles, locations, and body blocking** in every scene (never freezing Frame 0 onto the portrait pose).
2. **No Background Music Inside Raw Clips:**
   - Keep raw scene audio strictly **spoken dialogue + realistic room tone & foley** (footsteps on marble, rain, door slam). If music played inside each individual clip, every scene cut would chop the music! Instead, add one continuous score track during `assemble_local_timeline` (`bg_music_path`, `music_volume: 0.10`).
3. **Assemble the Finished Episode Locally (`0` Credits):**
   ```json
   {
     "clip_paths": [
       ".../01_cold_open.mp4",
       ".../02_elena_accusation.mp4",
       ".../03_marcus_reaction.mp4",
       ".../04_insert_evidence.mp4",
       ".../05_cliffhanger.mp4"
     ],
     "output_path": "~/Desktop/microdrama_ep1/episode_01_master.mp4",
     "aspect_ratio": "9:16",
     "audio_mode": "keep_native",
     "transition": "cut",
     "subtitles": "auto_whisper",
     "subtitle_preset": "cinema_yellow"
   }
   ```
   *(Set `subtitles: "none"` if the user prefers clean Netflix-style picture without burned captions).*
