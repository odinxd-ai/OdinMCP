---
name: odin-cinematic-faceless
description: Autonomous Cinematic Faceless Commercials & Mini-Documentaries rendered 100% locally using OdinxD's Generative Media APIs (https://odinxd.com). Use when the user wants luxury brand commercials, Apple/Nike-style product ads, dark aesthetic reels, historical/tech mini-documentaries, or ASMR visual commercials assembled locally on their PC without spending Remotion cloud renders.
---

# OdinMCP Cinematic Faceless Commercial Studio (`v2.2`)

You can direct, voice, score, subtitle, and master **agency-grade Cinematic Faceless Ads & Mini-Documentaries (`15s` to `90s+`)** using:
- **OdinxD's Atomic Generative APIs** (`generate_ai_image` + `generate_ai_video_batch`) -> billed strictly in `ai_credits` (`0` cloud Remotion renders consumed).
- **100% Free Local Mastering on the User's PC** (`generate_local_voiceover` + `assemble_local_timeline`) -> neural narration, synchronized `.srt` captions, diegetic SFX ducking, optional background music, and `-16 LUFS` broadcast loudness at **`$0` cloud render cost**.

> **When to use this workflow vs `create_faceless_ad`:**
> - Use **this Local Cinematic Studio workflow** when the user wants bespoke shot-by-shot art direction, custom durations (`15s` to `90s+`), `9:16` or `16:9` widescreen cinema, zero Remotion render consumption, or complete local control over voiceover and edits.
> - Use **`create_faceless_ad`** when the user is on a remote mobile/web client without local FFmpeg or specifically asks for OdinxD's all-in-one cloud Remotion commercial pipeline.

---

## 1. Zero-Cloud-LLM & Credit Efficiency Rules

1. **You Are the Creative Director & Copywriter:** Write the entire commercial voiceover script, visual continuity bible, and shot-by-shot camera prompts yourself (using the user's agent session—zero OdinxD text LLM calls).
2. **Exact Credit Formula (`0` Renders Consumed):**
   - `generate_ai_image`: **`1` AI credit / image** (optional hero product/style anchor).
   - `generate_ai_video_batch`:
     - **`1` AI credit / second** for pure text-to-video cinematic shots (`0` reference images).
     - **`2` AI credits / second** when anchoring a shot to real `product_images` or a `first_frame_image` keyframe.
   - `generate_local_voiceover` & `assemble_local_timeline`: **`0` credits** (100% local CPU).

---

## 2. Step-by-Step Cinematic Commercial Production Pipeline

### Step 1 — Write the Commercial Script & Synthesize Local Master Voiceover FIRST
Why synthesize the voiceover *before* generating video clips? Because **`generate_local_voiceover` gives you the exact millisecond `durationSec`**, allowing you to budget the exact video clip durations so picture and narration finish together cleanly!

1. Draft a tight, evocative script (`~2.2–2.4` words/sec):
   - **0–3s (Pattern-Interrupt Hook):** Bold sensory or contrarian opening line.
   - **3–18s (Worldbuilding / Mechanism):** Crisp concrete imagery; every 4–6 seconds motivates a new visual cut.
   - **Last 4s (Signature Payoff / CTA):** Memorable brand close.
2. Call **`generate_local_voiceover`**:
   - **Spanish Voices (`voice`):** `es_mx_male` (deep documentary), `es_es_male` (cinema authority), `es_mx_female` (warm commercial), `es_es_female` (editorial luxury), `es_co_female`, `es_ar_male`.
   - **English Voices (`voice`):** `en_male_cinema` (deep trailer/luxury), `en_male_commercial` (crisp modern), `en_female_luxury` (editorial), `en_female_ugc`.
   - Save the returned `audioPath` (`.mp3`), `srtPath` (`.srt`), and `durationSec` (e.g., `28.4s` -> plan `30s` of visual footage, such as `6 clips × 5s` or `5 clips × 6s`).

### Step 2 — Optional Visual Anchor (`generate_ai_image` — `1` Credit)
- If the commercial features a **real uploaded product** (`product_images`) or needs a recurring hero object/environment (e.g., an obsidian perfume flacon on wet volcanic basalt), optionally generate 1 hero keyframe with `generate_ai_image(purpose="cinematic_keyframe", aesthetic="editorial_luxury" | "cinema_35mm")` (`1` credit) to lock lighting and industrial design.
- For pure documentary/concept montages without a fixed physical SKU, skip Step 2 (`1` credit/sec pure text-to-video!).

### Step 3 — Shot-by-Shot Cinematography (`generate_ai_video_batch`)
Design **4 to 8 purposeful shots** (`4s` to `8s` each) whose total duration is `>= durationSec + 1.0s`:
- Set `clip_mode: "cinematic_faceless"` on every shot.
- **Write Cinematographer Prompts (Lens + Lighting + Camera Motion + Diegetic Foley):**
  - Specify lens & stock: *"35mm Arri Alexa Mini LF, anamorphic bokeh, Kodak Vision3 500T grain, chiaroscuro rim lighting..."*
  - Specify **1 clean camera movement** per shot: *slow dolly-in, macro probe lens glide, orbital tabletop tracking, low-angle crane rise, whip-pan transition*.
  - Request **subtle diegetic foley SFX only** (e.g., *crisp espresso pour, glass clink, rain on asphalt, mechanical watch tick*) and explicitly keep **zero spoken voice and zero background music** inside the raw clips (our local assembler mixes the master narration cleanly!).
- When showing the user's real physical product in hero shots (e.g., Shot 1 & Final Shot), attach `product_images` (`2 credits/sec` on those hero shots) while keeping atmospheric/lifestyle shots reference-free (`1 credit/sec`) to optimize the user's credit spend!

### Step 4 — Local Cinema Assembly (`assemble_local_timeline` — `0` Credits)
Once `generate_ai_video_batch` downloads the `.mp4` scenes locally, assemble the commercial master on the user's machine:
```json
{
  "clip_paths": [
    ".../01_hook_macro.mp4",
    ".../02_craft_process.mp4",
    ".../03_atmosphere.mp4",
    ".../04_hero_reveal.mp4",
    ".../05_packshot_cta.mp4"
  ],
  "output_path": "~/Desktop/cinematic_commercial_master.mp4",
  "aspect_ratio": "9:16",
  "audio_mode": "voiceover_master",
  "voiceover_path": "<audioPath from generate_local_voiceover>",
  "sfx_volume": 0.16,
  "transition": "cut",
  "subtitles": "srt",
  "srt_path": "<srtPath from generate_local_voiceover>",
  "subtitle_preset": "minimal_luxury"
}
```
- **Subtitle Aesthetic Guide:**
  - `minimal_luxury` — High-fashion, real estate, watches, skincare, architecture.
  - `cinema_yellow` — Mini-documentaries, historical storytelling, investigative essays.
  - `boxed_impact` — High-energy tech, SaaS, fitness, bold promos.
  - Or `subtitles: "none"` for pure widescreen/vertical television commercial aesthetics.

---

## 3. Bonus: ASMR Pure Sensory Commercial (`0` Voiceover Needed)
If the user asks for a **pure ASMR / sensory product commercial** (e.g., pouring iced matcha, unboxing mechanical keyboard, luxury skincare texture):
1. Skip `generate_local_voiceover`.
2. Generate `4–6` macro tactile shots (`4s–6s` each) via `generate_ai_video_batch(clip_mode="cinematic_faceless")` prompting rich hyper-detailed foley sounds (*ice cracking, fizzing carbonation, crisp cardboard magnetic snap*).
3. Assemble with `assemble_local_timeline(audio_mode="keep_native", subtitles="none", transition="cut")`.
