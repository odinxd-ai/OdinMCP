---
name: odin-ugc-factory
description: Autonomous AI UGC Commercial & Batch Ad Factory for OdinxD (https://odinxd.com). Use when the user asks to generate UGC product ads (e.g. "Generate 10 short 15s UGC videos", "Make a 30s or 45s UGC ad for my serum/app/supplement"), composite an avatar holding a product (with or without reference photos), animate user photos speaking a script, or stitch multi-take UGC ads locally with voice consistency.
---

# OdinMCP Autonomous UGC Ad Factory Skill (`v2.2`)

You can produce **high-converting 9:16 UGC ads**—both **parallel batches of 15s hook variations** (e.g., 5–10 ads at once) and **long multi-take 30s–60s+ UGC commercials**—combining **OdinxD's Atomic Generative Media APIs** (`ai_credits` only, `0` cloud renders consumed) with **100% free local timeline mastering** on the user's computer.

---

## 1. Golden Architecture & Pricing Rules

1. **YOU Write 100% of Scripts & Prompts (Zero Cloud LLM Usage):**
   - Never ask OdinxD to write scripts for `/api/v1/ai/*` tools. **You** (the user's agent) write every hook, spoken script, persona visual description, and camera prompt directly.
2. **Spoken Word Budget (`~2.0 to 2.2 words/second` MAX):**
   - `15s` clip -> **28 to 33 words MAX**
   - `10s` clip -> **19 to 22 words MAX**
   - `8s` clip -> **15 to 17 words MAX**
   - Never cram 50 words into 15 seconds or the creator will rush/cut off mid-sentence! Leave `0.4s` of natural breathing room at the end of each take.
3. **Transparent Credit Math (`0` Remotion Renders Consumed):**
   - `generate_ai_image`: **`1` AI credit per image**
   - `generate_ai_video_clip` / `generate_ai_video_batch`:
     - **`1` AI credit / second** WITHOUT reference images (`0` images attached)
     - **`2` AI credits / second** WITH `>= 1` reference image (`first_frame_image`, `avatar_image`, or `product_images`)
   - `assemble_local_timeline`: **`0` credits** (runs 100% locally via FFmpeg + optional local `faster-whisper` subtitles).
   - Check `get_account_quota` first so you know the user's exact `aiCreditsRemaining` before launching large batches.
4. **Private Creators Only (Zero Celebrities):**
   - Never pass celebrity or public-figure faces. If the user provides no avatar photo, generate an original synthetic everyday creator via `generate_ai_image`.

---

## 2. All 4 Avatar + Product Input Combinations (Compositing Matrix)

Always solve **visual identity + product fidelity first** via `generate_ai_image(purpose="ugc_avatar_with_product", aspect_ratio="9:16", aesthetic="ugc_smartphone")` (`1` AI credit) whenever a clip needs a recurring creator or real product packaging, then animate the resulting `primaryAssetRef` (`/api/media/u_...`) directly in `generate_ai_video_clip` or `generate_ai_video_batch` without re-uploading!

| User Provides | Step 1: Composite Base Photo (`generate_ai_image`) | Step 2: Animate Talking Clip (`generate_ai_video_clip` / `_batch`) |
| :--- | :--- | :--- |
| **Case 1: Neither avatar nor product photo** *(e.g. "Make a UGC ad for a vitamin C serum")* | **Option A (Fastest, `1 cr/s`):** Skip `generate_ai_image` for single 15s clips and describe both creator + generic serum bottle directly in `generate_ai_video_clip` (`0` refs = `15` credits for `15s`).<br>**Option B (Multi-take `30s–60s`):** Call `generate_ai_image(purpose="ugc_avatar_with_product")` (`1` credit) to lock one consistent creator + bottle, then chain its `assetRef` across all takes! | Pass `clip_mode: "ugc_talking"`, `dialogue_script`, and `voice_preset`. |
| **Case 2: Product photo(s) ONLY** *(user gives `serum.png`, no avatar)* | Call `generate_ai_image` with `purpose: "ugc_avatar_with_product"`, `product_images: ["C:/.../serum.png"]`, and a prompt describing a relatable smartphone-selfie creator holding that exact bottle naturally in a sunlit bathroom/kitchen (`1` credit). | Animate using `first_frame_image: "<composite_assetRef>"`, `reference_mode: "animate_photo"` (Take 1) and `avatar_image: "<composite_assetRef>"`, `reference_mode: "ingredient"` (Takes 2..N). |
| **Case 3: Avatar photo ONLY** *(user gives `creator.jpg`, describes product in text)* | Call `generate_ai_image` with `purpose: "ugc_avatar_with_product"`, `avatar_image: "C:/.../creator.jpg"`, and prompt describing that exact person holding/using the described product (`1` credit). | Animate `composite_assetRef` speaking your `dialogue_script` with `clip_mode: "ugc_talking"`. |
| **Case 4: BOTH separate Avatar photo + Product photo(s)** *(user gives `creator.jpg` + `bottle.png`)* | **MANDATORY FUSION STEP:** Call `generate_ai_image` with `purpose: "ugc_avatar_with_product"`, `avatar_image: "C:/.../creator.jpg"`, `product_images: ["C:/.../bottle.png"]` (`1` credit). This fuses both into **one cohesive `9:16` photo** of that avatar holding that exact product! | Pass `first_frame_image: "<composite_assetRef>"`, `reference_mode: "animate_photo"` into `generate_ai_video_clip` (`clip_mode: "ugc_talking"`). |

> **Shortcut if user ALREADY sends a combined photo of the avatar holding the product:** Skip `generate_ai_image` and pass that photo straight as `first_frame_image` with `reference_mode: "animate_photo"`!

---

## 3. Voice Consistency Across Multi-Take Long UGC (`30s`, `45s`, `60s+`)

Each `gemini-omni-1.2-flash` generation produces `3s` to `15s`. To build a seamless `30s`, `45s`, or `60s` UGC commercial, generate **2 to 4 takes** (`10s–15s` each) + optional B-Roll product cutaway, and stitch them locally at `$0` render cost with `assemble_local_timeline`:

### English (`language: "en"`) — Exact Prebuilt Voice Library Lock
`gemini-omni-1.2-flash` includes an official English Voice Library that maintains remarkable timbre consistency across separate takes when you lock the same `voice_preset` on every take:
- **Female UGC Voices:**
  - `Aoede` — Warm, breezy 26yo US creator *(Best for Skincare, Beauty, Wellness, Lifestyle)*
  - `Zephyr` — Bright, energetic 24yo TikTok creator *(Best for Viral Hooks, Gadgets, Apps, Dropshipping)*
  - `Kore` — Confident, composed 30yo founder *(Best for High-Ticket, Supplements, Luxury)*
  - `Leda` — Youthful 22yo Gen-Z creator *(Best for Fashion, Study/Productivity, Snacks)*
  - `Vindemiatrix` — Calm, soothing 29yo creator *(Best for Sleep, Mindfulness, Home)*
- **Male UGC Voices:**
  - `Puck` — Upbeat, charismatic 27yo US creator *(Best for Tech, E-Commerce, Everyday Gear)*
  - `Fenrir` — High-energy 28yo creator *(Best for Fitness, Pre-Workout, Sports)*
  - `Orus` — Clear, trustworthy 31yo founder *(Best for SaaS, Finance, B2B)*
  - `Achird` — Casual, warm 26yo reviewer *(Best for Honest Reviews, Unboxing)*
  - `Charon` — Deep, cinematic 35yo voice *(Best for Luxury, Watches, Menswear)*

### Spanish (`language: "es"`) — Dialect Acoustic Lock + Editorial Pro-Tip
In Spanish, lock **both** `voice_preset` (`es_mx_female_ugc`, `es_mx_male_ugc`, `es_es_female_ugc`, `es_es_male_ugc`, `es_co_female_ugc`, or `es_ar_male_ugc`) **and** an identical `voice_anchor` description across every take of the batch.
- **Transparency & Pro Editing Trick:** Because native video-audio generation in Spanish does not yet use fixed speaker IDs like English, slight micro-variations in cadence or accent can occasionally happen between separate takes.
- **How to make Spanish `30s–45s` UGC look 100% seamless:**
  1. Keep all spoken takes in the same `generate_ai_video_batch` with identical `voice_preset` + `voice_anchor`.
  2. Insert a **`4s–5s` macro product application B-Roll clip** (`clip_mode: "cinematic_faceless"`, `product_images: [...]`, subtle tactile SFX, no speech) between Take 1 and Take 2—or vary Take 2's camera framing (`reference_mode: "ingredient"`, medium angle in kitchen vs bathroom closeup) so any subtle vocal shift feels like a natural real-life cut between moments!

---

## 4. Playbook A — Batch Short UGC Ads (e.g. *"Generate 10 short 15s UGC videos"*)

When the user asks for `N` standalone `15s` UGC ads to test hooks on Meta/TikTok Ads:
1. **Design `N` Distinct Direct-Response Angles** (never repeat the same script!):
   - *Angle 1 (Problem Callout):* "Stop scrolling if your skin still looks dull by noon..."
   - *Angle 2 (Skeptical-to-Obsessed):* "I honestly thought this serum was pure TikTok hype until week two..."
   - *Angle 3 (3-Second Visual Demo / Texture):* "Look at the glow from literally two drops of this..."
   - *Angle 4 (Price/Alternative Comparison):* "I replaced my \$120 clinic facial with this one bottle..."
   - *Angle 5 (Routine / POV):* "POV: The 10-second morning step I will never skip again..."
   *(Continue diversifying personas, settings, and voices: `Aoede`, `Zephyr`, `Puck`, `Leda`, `Orus`, etc.)*
2. **If Product Photos Exist:** First generate varied creator+product base photos with `generate_ai_image` (`purpose: "ugc_avatar_with_product"`, `1` credit each) so every creator holds the exact real product.
3. **Launch Parallel Batch (`generate_ai_video_batch`):**
   - Pass up to `10` clips per batch (`duration: 15`, `clip_mode: "ugc_talking"`, `save_to_dir: "~/Desktop/ugc_batch"`).
   - Optional: Run `assemble_local_timeline` (`subtitles: "auto_whisper"`, `subtitle_preset: "ugc_clean"`) on each downloaded clip if the user wants clean TikTok captions burned in at `0` extra cost!

---

## 5. Playbook B — Long Multi-Take UGC Ad (`30s` / `45s` / `60s`)

Example structure for a **40-second high-converting UGC ad** (`3` takes -> stitched locally):
1. **Step 1 (`1` AI credit):** Call `generate_ai_image` (`purpose: "ugc_avatar_with_product"`, `aspect_ratio: "9:16"`) to create/fuse the hero creator holding the product. Capture `primaryAssetRef`.
2. **Step 2 (`generate_ai_video_batch`):** Generate all 3 takes in parallel locking `voice_preset: "Aoede"` (or `es_mx_female_ugc`):
   - **Take 1 (`14s`, Hook + Pain Point):** `clip_mode: "ugc_talking"`, `reference_mode: "animate_photo"`, `first_frame_image: primaryAssetRef`, `dialogue_script` (~29 words).
   - **Take 2 (`12s`, Mechanism + Demo in fresh angle):** `clip_mode: "ugc_talking"`, `reference_mode: "ingredient"`, `avatar_image: primaryAssetRef`, prompt specifies slightly wider handheld kitchen/vanity angle applying the product, `dialogue_script` (~25 words).
   - **Take 3 (`14s`, Social Proof + CTA):** `clip_mode: "ugc_talking"`, `reference_mode: "ingredient"`, `avatar_image: primaryAssetRef`, close-up smiling holding bottle near cheek, `dialogue_script` (~29 words).
3. **Step 3 (`0` credits — Local Master):** Call `assemble_local_timeline`:
   ```json
   {
     "clip_paths": [".../01_hook.mp4", ".../02_demo.mp4", ".../03_cta.mp4"],
     "output_path": "~/Desktop/ugc_40s_master.mp4",
     "aspect_ratio": "9:16",
     "audio_mode": "keep_native",
     "transition": "cut",
     "subtitles": "auto_whisper",
     "subtitle_preset": "ugc_clean"
   }
   ```
