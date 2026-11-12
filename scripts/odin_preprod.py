#!/usr/bin/env python3
"""
OdinMCP Local Pre-Production & Assembly Studio Engine (v2.2.0)
==============================================================
100% local video pre-production, neural voiceover, and timeline mastering toolkit executed on the user's computer:
  1. `doctor`     — Checks FFmpeg, Python/uv, faster-whisper, yt-dlp, OpenCV, PySceneDetect & edge-tts (auto-setup in ~/.odinxd/preprod_env).
  2. `transcribe` — Local word-timestamped Whisper transcription + acoustic silence map across 1..N raw takes.
  3. `clean-aroll`— Cuts spoken mistakes/bad takes or auto-strips dead silences into ONE clean 9:16 MP4 for OdinxD.
  4. `podcast`    — Downloads/analyzes long podcasts (yt-dlp + Whisper) and extracts 9:16 vertical clips with OpenCV face-centering.
  5. `stock-bank` — Slices raw personal footage into reusable 3–5s 9:16 B-Roll clips with JPEG keyframes (~/.odinxd/stock_bank).
  6. `voiceover`  — Synthesizes free local neural voiceover MP3 + SRT subtitles via edge-tts ($0 server cost).
  7. `assemble`   — Stitches multi-take 30s–60s+ UGC ads, Cinematic Faceless commercials, or Microdrama episodes locally in 1080x1920 (or 1920x1080) @ 30fps with -16 LUFS mastering, SFX/music ducking, and burned-in .ass captions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ENGINE_VERSION = "2.2.0"

VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS

SENSITIVE_DIR_RE = re.compile(r"(^|[\\/])(\.ssh|\.aws|\.gnupg|\.git|\.kube|\.docker)([\\/]|$)", re.IGNORECASE)
SENSITIVE_FILE_RE = re.compile(
    r"^(\.env(\..+)?|id_(rsa|dsa|ecdsa|ed25519)(\.pub)?|credentials(\.json)?|\.npmrc|\.pypirc|\.netrc)$",
    re.IGNORECASE,
)

PREPROD_WHEELS = [
    "faster-whisper>=1.0.3",
    "yt-dlp>=2024.8.0",
    "opencv-python-headless>=4.9.0",
    "scenedetect>=0.6.4",
    "edge-tts>=6.1.12",
]

LOCAL_VOICEOVER_PRESETS = {
    "es_mx_male": "es-MX-JorgeNeural",
    "es_mx_female": "es-MX-DaliaNeural",
    "es_es_male": "es-ES-AlvaroNeural",
    "es_es_female": "es-ES-ElviraNeural",
    "es_co_female": "es-CO-SalomeNeural",
    "es_ar_male": "es-AR-TomasNeural",
    "en_male_cinema": "en-US-ChristopherNeural",
    "en_male_commercial": "en-US-GuyNeural",
    "en_female_ugc": "en-US-AvaNeural",
    "en_female_luxury": "en-GB-SoniaNeural",
}


def get_odin_home() -> Path:
    custom = (os.environ.get("ODINXD_HOME") or "").strip()
    base = Path(custom).expanduser() if custom else (Path.home() / ".odinxd")
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_managed_venv_python() -> Path:
    venv_dir = get_odin_home() / "preprod_env"
    if platform.system().lower().startswith("win"):
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def is_running_in_managed_venv() -> bool:
    try:
        return Path(sys.executable).resolve() == get_managed_venv_python().resolve()
    except Exception:
        return False


def maybe_reexec_in_managed_venv() -> None:
    if os.environ.get("ODINMCP_NO_REEXEC") == "1" or is_running_in_managed_venv():
        return
    venv_py = get_managed_venv_python()
    if venv_py.is_file():
        env = {**os.environ, "ODINMCP_NO_REEXEC": "1"}
        res = subprocess.run([str(venv_py), str(Path(__file__).resolve()), *sys.argv[1:]], env=env, shell=False)
        sys.exit(res.returncode)


def assert_safe_local_path(raw_path: str | Path, allow_dir: bool = False, must_exist: bool = True) -> Path:
    expanded = Path(str(raw_path)).expanduser()
    resolved_str = str(expanded.resolve())
    if SENSITIVE_DIR_RE.search(resolved_str) or SENSITIVE_FILE_RE.match(expanded.name):
        raise PermissionError(
            f"LOCAL_SECURITY_BLOCKED: Refusing to access sensitive path or file '{expanded.name}'."
        )
    if must_exist:
        if not expanded.exists():
            raise FileNotFoundError(f"LOCAL_FILE_NOT_FOUND: File not found: '{raw_path}'")
        if expanded.is_symlink():
            raise PermissionError(f"LOCAL_SYMLINK_BLOCKED: Symbolic links are blocked for security: '{expanded.name}'")
        if expanded.is_dir() and not allow_dir:
            raise ValueError(f"INVALID_MEDIA_PATH: Expected a media file, got directory: '{raw_path}'")
    else:
        if expanded.exists() and expanded.is_symlink():
            raise PermissionError(f"LOCAL_SYMLINK_BLOCKED: Refusing to overwrite symbolic link: '{expanded.name}'")
    return expanded.resolve()


def assert_safe_media_input(raw_path: str | Path) -> Path:
    p = assert_safe_local_path(raw_path, allow_dir=False, must_exist=True)
    ext = p.suffix.lower()
    if ext not in MEDIA_EXTENSIONS:
        raise ValueError(
            f"UNSUPPORTED_MEDIA_EXTENSION: '{ext}' is not supported. Allowed: {sorted(MEDIA_EXTENSIONS)}"
        )
    if p.stat().st_size <= 0:
        raise ValueError(f"EMPTY_LOCAL_FILE: '{p.name}' is empty (0 bytes).")
    return p


def assert_safe_mp4_output(raw_path: Optional[str], default_prefix: str = "clean_aroll") -> Path:
    if not raw_path or not str(raw_path).strip():
        out_dir = get_odin_home() / "preprod_exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        return (out_dir / f"{default_prefix}_{stamp}.mp4").resolve()

    p = assert_safe_local_path(raw_path, allow_dir=True, must_exist=False)
    if p.exists() and p.is_dir():
        stamp = time.strftime("%Y%m%d_%H%M%S")
        p = p / f"{default_prefix}_{stamp}.mp4"
    if p.suffix.lower() != ".mp4":
        raise ValueError("INVALID_OUTPUT_EXTENSION: Output video path must end in '.mp4'.")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p.resolve()


def find_binary(name: str) -> Optional[str]:
    direct = shutil.which(name)
    if direct:
        return direct

    is_win = platform.system().lower().startswith("win")
    exe = f"{name}.exe" if is_win else name
    candidates: List[Path] = []
    if is_win:
        local_app = Path(os.environ.get("LOCALAPPDATA", ""))
        if local_app.is_dir():
            winget_pkgs = local_app / "Microsoft" / "WinGet" / "Packages"
            if winget_pkgs.is_dir():
                candidates.extend(winget_pkgs.rglob(exe))
            candidates.append(local_app / "Microsoft" / "WinGet" / "Links" / exe)
        candidates.extend([
            Path.home() / "scoop" / "shims" / exe,
            Path("C:/ProgramData/chocolatey/bin") / exe,
            Path("C:/ffmpeg/bin") / exe,
        ])
    else:
        candidates.extend([
            Path("/opt/homebrew/bin") / exe,
            Path("/usr/local/bin") / exe,
            Path("/usr/bin") / exe,
            Path.home() / ".local" / "bin" / exe,
            Path.home() / ".cargo" / "bin" / exe,
        ])

    for c in candidates:
        if c.is_file():
            return str(c)
    return None


def require_ffmpeg() -> Tuple[str, str]:
    ffmpeg_bin = find_binary("ffmpeg")
    ffprobe_bin = find_binary("ffprobe")
    if not ffmpeg_bin or not ffprobe_bin:
        sys_name = platform.system().lower()
        if "darwin" in sys_name:
            hint = "brew install ffmpeg"
        elif "win" in sys_name:
            hint = "winget install Gyan.FFmpeg"
        else:
            hint = "sudo apt-get update && sudo apt-get install -y ffmpeg"
        raise RuntimeError(
            f"FFMPEG_NOT_FOUND: FFmpeg/FFprobe is required locally for video pre-production. Install it with: `{hint}`"
        )
    return ffmpeg_bin, ffprobe_bin


def check_module_installed(mod_name: str) -> bool:
    try:
        __import__(mod_name)
        return True
    except Exception:
        return False


def provision_managed_environment() -> Dict[str, Any]:
    venv_dir = get_odin_home() / "preprod_env"
    venv_py = get_managed_venv_python()
    uv_bin = find_binary("uv")

    if not venv_py.is_file():
        if uv_bin:
            subprocess.run([uv_bin, "venv", str(venv_dir)], check=True, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        else:
            subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if uv_bin:
        cmd = [uv_bin, "pip", "install", "--python", str(venv_py), *PREPROD_WHEELS]
    else:
        subprocess.run(
            [str(venv_py), "-m", "pip", "install", "--upgrade", "pip"],
            check=False,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        cmd = [str(venv_py), "-m", "pip", "install", "--prefer-binary", *PREPROD_WHEELS]

    proc = subprocess.run(cmd, check=False, shell=False, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"PREPROD_ENV_INSTALL_FAILED: {proc.stderr[-800:] or proc.stdout[-800:]}")

    return {
        "managedVenv": str(venv_dir),
        "pythonExecutable": str(venv_py),
        "installerUsed": "uv" if uv_bin else "pip",
        "installedPackages": PREPROD_WHEELS,
    }


def probe_media_info(ffprobe_bin: str, media_path: Path) -> Dict[str, Any]:
    proc = subprocess.run(
        [
            ffprobe_bin,
            "-v", "error",
            "-show_entries", "format=duration,size:stream=index,codec_type,codec_name,width,height,r_frame_rate",
            "-of", "json",
            "--",
            str(media_path),
        ],
        capture_output=True,
        text=True,
        check=True,
        shell=False,
        timeout=30,
    )
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams") or []
    fmt = data.get("format") or {}

    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    width = int(v_stream.get("width") or 0) if v_stream else 0
    height = int(v_stream.get("height") or 0) if v_stream else 0
    fps = 30.0
    if v_stream and v_stream.get("r_frame_rate"):
        num_den = str(v_stream["r_frame_rate"]).split("/")
        if len(num_den) == 2 and float(num_den[1]) > 0:
            fps = round(float(num_den[0]) / float(num_den[1]), 3)

    duration = float(fmt.get("duration") or 0.0)
    return {
        "path": str(media_path),
        "filename": media_path.name,
        "durationSec": round(duration, 3),
        "sizeBytes": int(fmt.get("size") or media_path.stat().st_size),
        "hasVideo": v_stream is not None,
        "hasAudio": a_stream is not None,
        "width": width,
        "height": height,
        "fps": fps,
        "orientation": "vertical" if height >= width and height > 0 else ("horizontal" if width > height else "audio_only"),
    }


def detect_silences_ffmpeg(
    ffmpeg_bin: str,
    media_path: Path,
    duration_sec: float,
    noise_db: float = -35.0,
    min_silence_sec: float = 0.65,
    pad_sec: float = 0.12,
) -> Tuple[List[Dict[str, float]], List[Dict[str, float]]]:
    proc = subprocess.run(
        [
            ffmpeg_bin,
            "-hide_banner",
            "-nostats",
            "-i", str(media_path),
            "-af", f"silencedetect=noise={noise_db}dB:d={min_silence_sec}",
            "-f", "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
        shell=False,
        timeout=300,
    )
    log = proc.stderr or ""
    starts = [float(m.group(1)) for m in re.finditer(r"silence_start:\s*([0-9.]+)", log)]
    ends = [float(m.group(1)) for m in re.finditer(r"silence_end:\s*([0-9.]+)", log)]

    silences: List[Dict[str, float]] = []
    for idx, s_start in enumerate(starts):
        s_end = ends[idx] if idx < len(ends) else duration_sec
        if s_end > s_start:
            silences.append({
                "start": round(max(0.0, s_start), 3),
                "end": round(min(duration_sec, s_end), 3),
                "duration": round(max(0.0, min(duration_sec, s_end) - max(0.0, s_start)), 3),
            })

    # Compute speech intervals (inverse of silences) with natural breath padding
    speech: List[Dict[str, float]] = []
    cursor = 0.0
    for sil in silences:
        seg_end = min(duration_sec, sil["start"] + pad_sec)
        seg_start = max(0.0, cursor - (pad_sec if cursor > 0 else 0.0))
        if seg_end - seg_start >= 0.25:
            if speech and seg_start <= speech[-1]["end"] + 0.08:
                speech[-1]["end"] = round(max(speech[-1]["end"], seg_end), 3)
            else:
                speech.append({"start": round(seg_start, 3), "end": round(seg_end, 3)})
        cursor = sil["end"]

    if duration_sec - cursor >= 0.25:
        seg_start = max(0.0, cursor - (pad_sec if cursor > 0 else 0.0))
        if speech and seg_start <= speech[-1]["end"] + 0.08:
            speech[-1]["end"] = round(duration_sec, 3)
        else:
            speech.append({"start": round(seg_start, 3), "end": round(duration_sec, 3)})

    if not speech and duration_sec > 0.2:
        speech = [{"start": 0.0, "end": round(duration_sec, 3)}]

    return silences, speech


def transcribe_file_whisper(
    ffmpeg_bin: str,
    media_path: Path,
    model_size: str = "base",
    language: Optional[str] = None,
) -> Dict[str, Any]:
    import numpy as np  # type: ignore
    from faster_whisper import WhisperModel  # type: ignore

    models_cache = get_odin_home() / "whisper_models"
    models_cache.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = Path(tmpdir) / "audio_16k.wav"
        subprocess.run(
            [
                ffmpeg_bin, "-y", "-v", "error",
                "-i", str(media_path),
                "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                str(wav_path),
            ],
            check=True,
            shell=False,
            timeout=300,
        )

        # Load PCM s16le directly into float32 [-1.0, 1.0] ndarray to bypass PyAV av.open() signature mismatches
        with wave.open(str(wav_path), "rb") as wf:
            pcm_bytes = wf.readframes(wf.getnframes())
        audio_f32 = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        model = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",
            download_root=str(models_cache),
        )
        lang_arg = language if language and language != "auto" else None
        segments_gen, info = model.transcribe(
            audio_f32,
            language=lang_arg,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 450},
        )

        segments_out: List[Dict[str, Any]] = []
        full_text_parts: List[str] = []
        for seg in segments_gen:
            txt = (seg.text or "").strip()
            if not txt:
                continue
            full_text_parts.append(txt)
            words_list = []
            for w in (seg.words or []):
                words_list.append({
                    "word": (w.word or "").strip(),
                    "start": round(float(w.start), 3),
                    "end": round(float(w.end), 3),
                })
            segments_out.append({
                "start": round(float(seg.start), 3),
                "end": round(float(seg.end), 3),
                "text": txt,
                "words": words_list,
            })

        return {
            "detectedLanguage": getattr(info, "language", lang_arg or "unknown"),
            "languageProbability": round(float(getattr(info, "language_probability", 0.0)), 3),
            "fullText": " ".join(full_text_parts),
            "segments": segments_out,
        }


def estimate_face_center_x_ratio(
    video_path: Path,
    start_sec: float,
    end_sec: float,
) -> Optional[float]:
    """
    Samples frames inside [start_sec, end_sec] using OpenCV Haar Frontal/Profile Face cascades
    and returns a stabilized horizontal center ratio in [0.15, 0.85] for 9:16 vertical reframing.
    """
    if not check_module_installed("cv2"):
        return None

    import cv2  # type: ignore

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None

    try:
        cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        detector = cv2.CascadeClassifier(cascade_path)
        dur = max(0.2, end_sec - start_sec)
        sample_count = min(14, max(4, int(dur * 1.5)))
        centers: List[float] = []

        for i in range(sample_count):
            t = start_sec + (dur * (i + 0.5) / sample_count)
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            h, w = frame.shape[:2]
            if w <= 0 or h <= 0:
                continue
            scale = min(1.0, 640.0 / float(w))
            small = cv2.resize(frame, (max(1, int(w * scale)), max(1, int(h * scale))))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            faces = detector.detectMultiScale(gray, scaleFactor=1.12, minNeighbors=5, minSize=(28, 28))
            if len(faces) > 0:
                # Pick largest prominent face in frame
                fx, fy, fw, fh = max(faces, key=lambda r: r[2] * r[3])
                cx_ratio = ((fx + fw * 0.5) / float(small.shape[1]))
                centers.append(max(0.15, min(0.85, cx_ratio)))

        if not centers:
            return None

        # Median suppresses outlier detections and camera jitter (deadzone stabilization)
        centers.sort()
        median_ratio = centers[len(centers) // 2]
        if abs(median_ratio - 0.5) < 0.045:
            return 0.5
        return round(median_ratio, 4)
    finally:
        cap.release()


def build_vertical_vf_filter(
    width: int,
    height: int,
    face_x_ratio: Optional[float] = None,
    target_w: int = 1080,
    target_h: int = 1920,
) -> str:
    if width > height and width > 0 and height > 0:
        # Horizontal source -> smart 9:16 crop centered on speaker face (or center 0.5)
        cx = 0.5 if face_x_ratio is None else max(0.0, min(1.0, face_x_ratio))
        return (
            f"scale=-2:{target_h}:flags=lanczos,"
            f"crop={target_w}:{target_h}:clip((iw-{target_w})*{cx:.4f}\\,0\\,iw-{target_w}):0,"
            f"setsar=1,fps=30,format=yuv420p"
        )
    # Already vertical or square -> scale to cover 1080x1920 cleanly without black bars
    return (
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={target_w}:{target_h},setsar=1,fps=30,format=yuv420p"
    )


def render_clean_merged_aroll(
    ffmpeg_bin: str,
    ffprobe_bin: str,
    segments: List[Dict[str, Any]],
    output_mp4: Path,
    smart_reframe: bool = True,
    normalize_audio: bool = True,
) -> Dict[str, Any]:
    if not segments:
        raise ValueError("NO_SEGMENTS_TO_RENDER: Segment cut-list is empty after silence/mistake filtering.")

    media_cache: Dict[str, Dict[str, Any]] = {}
    rendered_parts: List[Path] = []
    kept_summary: List[Dict[str, Any]] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        for idx, seg in enumerate(segments):
            src_path = assert_safe_media_input(seg["file"])
            key = str(src_path)
            if key not in media_cache:
                media_cache[key] = probe_media_info(ffprobe_bin, src_path)
            info = media_cache[key]
            if not info["hasVideo"]:
                raise ValueError(f"VIDEO_STREAM_REQUIRED: '{src_path.name}' has no video stream.")

            start_s = max(0.0, float(seg["start"]))
            end_s = min(float(info["durationSec"]), float(seg["end"]))
            seg_dur = round(end_s - start_s, 3)
            if seg_dur < 0.22:
                continue

            face_ratio: Optional[float] = None
            if smart_reframe and info["width"] > info["height"]:
                face_ratio = estimate_face_center_x_ratio(src_path, start_s, end_s)

            vf = build_vertical_vf_filter(info["width"], info["height"], face_ratio)
            fade_dur = min(0.025, seg_dur * 0.15)
            fade_out_st = max(0.0, seg_dur - fade_dur)

            part_path = tmp_root / f"seg_{idx:04d}.ts"
            cmd = [
                ffmpeg_bin, "-y", "-v", "error",
                "-ss", f"{start_s:.3f}",
                "-t", f"{seg_dur:.3f}",
                "-i", str(src_path),
                "-vf", vf,
            ]
            if info["hasAudio"]:
                af = (
                    f"aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                    f"afade=t=in:st=0:d={fade_dur:.3f},afade=t=out:st={fade_out_st:.3f}:d={fade_dur:.3f}"
                )
                cmd.extend(["-af", af, "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"])
            else:
                cmd.extend(["-f", "lavfi", "-t", f"{seg_dur:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"])
                cmd.extend(["-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "128k", "-shortest"])

            cmd.extend([
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-f", "mpegts",
                str(part_path),
            ])
            subprocess.run(cmd, check=True, shell=False, timeout=600)
            rendered_parts.append(part_path)
            kept_summary.append({
                "sourceFile": src_path.name,
                "start": round(start_s, 3),
                "end": round(end_s, 3),
                "duration": seg_dur,
                "faceCenterXRatio": face_ratio,
            })

        if not rendered_parts:
            raise ValueError("ALL_SEGMENTS_TOO_SHORT: No valid video segments (>= 0.22s) remained.")

        concat_list = tmp_root / "concat_list.txt"
        concat_list.write_text(
            "\n".join(f"file '{p.as_posix()}'" for p in rendered_parts) + "\n",
            encoding="utf-8",
        )

        final_cmd = [
            ffmpeg_bin, "-y", "-v", "error",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
        ]
        if normalize_audio:
            final_cmd.extend([
                "-c:v", "copy",
                "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            ])
        else:
            final_cmd.extend(["-c", "copy"])

        final_cmd.extend(["-movflags", "+faststart", str(output_mp4)])
        subprocess.run(final_cmd, check=True, shell=False, timeout=600)

    out_info = probe_media_info(ffprobe_bin, output_mp4)
    return {
        "outputMp4": str(output_mp4),
        "durationSec": out_info["durationSec"],
        "width": out_info["width"],
        "height": out_info["height"],
        "fps": out_info["fps"],
        "segmentsKeptCount": len(kept_summary),
        "segmentsKept": kept_summary,
        "readyForOdinxD": True,
        "nextStepHint": (
            "Pass 'outputMp4' directly as 'video_url' in render_hybrid_reel, render_viral_beat, "
            "render_motion_stock, render_maxy_overlay, or render_fitness_talking_head."
        ),
    }


def resolve_podcast_source(source: str, auto_install: bool = True) -> Path:
    trimmed = str(source or "").strip()
    if re.match(r"^https?://", trimmed, re.IGNORECASE):
        if not check_module_installed("yt_dlp"):
            if auto_install:
                provision_managed_environment()
                maybe_reexec_in_managed_venv()
            else:
                raise RuntimeError(
                    "YTDLP_NOT_INSTALLED: Run local_preprod_doctor with auto_install=true to enable podcast URL downloads."
                )
        cache_dir = get_odin_home() / "podcast_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        url_hash = hashlib.sha256(trimmed.encode("utf-8")).hexdigest()[:14]
        existing = sorted(cache_dir.glob(f"pod_{url_hash}.*"))
        media_existing = [p for p in existing if p.suffix.lower() in VIDEO_EXTENSIONS]
        if media_existing:
            return media_existing[0].resolve()

        out_tmpl = str(cache_dir / f"pod_{url_hash}.%(ext)s")
        ffmpeg_bin, _ = require_ffmpeg()
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--no-playlist",
            "--ffmpeg-location", str(Path(ffmpeg_bin).parent),
            "-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/b",
            "--merge-output-format", "mp4",
            "-o", out_tmpl,
            "--",
            trimmed,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, shell=False, timeout=900)
        if proc.returncode != 0:
            raise RuntimeError(f"PODCAST_DOWNLOAD_FAILED: {proc.stderr[-600:] or proc.stdout[-600:]}")

        downloaded = [p for p in sorted(cache_dir.glob(f"pod_{url_hash}.*")) if p.suffix.lower() in VIDEO_EXTENSIONS]
        if not downloaded:
            raise RuntimeError("PODCAST_DOWNLOAD_EMPTY: yt-dlp completed without producing a video file.")
        return downloaded[0].resolve()

    return assert_safe_media_input(trimmed)


def detect_scene_boundaries(ffmpeg_bin: str, video_path: Path, duration_sec: float) -> List[Tuple[float, float]]:
    if check_module_installed("scenedetect"):
        try:
            from scenedetect import ContentDetector, detect  # type: ignore

            scene_list = detect(str(video_path), ContentDetector(threshold=27.0, min_scene_len=45))
            if scene_list:
                return [(round(s[0].get_seconds(), 3), round(s[1].get_seconds(), 3)) for s in scene_list]
        except Exception:
            pass

    # Fallback: FFmpeg scene-change filter
    proc = subprocess.run(
        [
            ffmpeg_bin, "-hide_banner", "-nostats",
            "-i", str(video_path),
            "-vf", "select='gt(scene,0.32)',showinfo",
            "-an", "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
        check=False,
        shell=False,
        timeout=300,
    )
    cuts = [0.0]
    for m in re.finditer(r"pts_time:([0-9.]+)", proc.stderr or ""):
        t = float(m.group(1))
        if t - cuts[-1] >= 2.0 and duration_sec - t >= 1.5:
            cuts.append(round(t, 3))
    cuts.append(round(duration_sec, 3))

    scenes: List[Tuple[float, float]] = []
    for i in range(len(cuts) - 1):
        s_st, s_en = cuts[i], cuts[i + 1]
        if s_en - s_st >= 2.0:
            scenes.append((s_st, s_en))

    if not scenes and duration_sec >= 1.5:
        # Uniform slicing fallback for continuous gimbal takes
        step = 4.5
        cur = 0.0
        while cur + 2.2 <= duration_sec:
            scenes.append((round(cur, 3), round(min(duration_sec, cur + step), 3)))
            cur += step

    return scenes


def get_stock_bank_paths() -> Tuple[Path, Path, Path, Path]:
    bank_root = get_odin_home() / "stock_bank"
    clips_dir = bank_root / "clips"
    thumbs_dir = bank_root / "thumbs"
    index_file = bank_root / "index.json"
    clips_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    return bank_root, clips_dir, thumbs_dir, index_file


def load_stock_index(index_file: Path) -> List[Dict[str, Any]]:
    if not index_file.is_file():
        return []
    try:
        raw = json.loads(index_file.read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else []
    except Exception:
        return []


def save_stock_index(index_file: Path, items: List[Dict[str, Any]]) -> None:
    tmp = index_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(index_file)


def tokenize_tags(text: str) -> List[str]:
    tokens = re.findall(r"[a-zA-Z0-9áéíóúñÁÉÍÓÚÑ]{3,}", (text or "").lower())
    stop = {"video", "clip", "mov", "mp4", "img", "dsc", "vid", "raw", "final", "copy"}
    out: List[str] = []
    for tok in tokens:
        if tok not in stop and not tok.isdigit() and tok not in out:
            out.append(tok)
    return out[:12]


# ─────────────────────────────────────────────────────────────────────────────
# CLI SUBCOMMAND HANDLERS
# ─────────────────────────────────────────────────────────────────────────────


def cmd_doctor(args: argparse.Namespace) -> Dict[str, Any]:
    provision_info = None
    if args.install:
        provision_info = provision_managed_environment()
        if not is_running_in_managed_venv():
            maybe_reexec_in_managed_venv()

    ffmpeg_bin = find_binary("ffmpeg")
    ffprobe_bin = find_binary("ffprobe")
    uv_bin = find_binary("uv")
    _, _, _, index_file = get_stock_bank_paths()
    stock_items = load_stock_index(index_file)

    modules = {
        "faster_whisper": check_module_installed("faster_whisper"),
        "yt_dlp": check_module_installed("yt_dlp"),
        "opencv_headless": check_module_installed("cv2"),
        "scenedetect": check_module_installed("scenedetect"),
        "edge_tts": check_module_installed("edge_tts"),
    }
    all_ready = bool(ffmpeg_bin and ffprobe_bin and all(modules.values()))

    return {
        "engineVersion": ENGINE_VERSION,
        "ready": all_ready,
        "odinHome": str(get_odin_home()),
        "pythonExecutable": sys.executable,
        "runningInManagedVenv": is_running_in_managed_venv(),
        "binaries": {
            "ffmpeg": ffmpeg_bin,
            "ffprobe": ffprobe_bin,
            "uv": uv_bin,
        },
        "pythonModules": modules,
        "localStockBankClipsCount": len(stock_items),
        "provisionResult": provision_info,
        "hint": (
            "All local pre-production engines are ready!"
            if all_ready
            else "Call local_preprod_doctor with auto_install=true (or `python odin_preprod.py doctor --install`) to auto-install missing Python packages into ~/.odinxd/preprod_env."
        ),
    }


def cmd_transcribe(args: argparse.Namespace) -> Dict[str, Any]:
    ffmpeg_bin, ffprobe_bin = require_ffmpeg()
    has_whisper = check_module_installed("faster_whisper")
    if not has_whisper and args.auto_install:
        provision_managed_environment()
        maybe_reexec_in_managed_venv()
        has_whisper = check_module_installed("faster_whisper")

    results: List[Dict[str, Any]] = []
    for raw_p in args.inputs:
        media_p = assert_safe_media_input(raw_p)
        info = probe_media_info(ffprobe_bin, media_p)
        silences, speech = detect_silences_ffmpeg(
            ffmpeg_bin,
            media_p,
            info["durationSec"],
            noise_db=args.silence_db,
            min_silence_sec=args.min_silence,
        )
        entry: Dict[str, Any] = {
            "media": info,
            "silencesDetected": silences,
            "speechIntervals": speech,
            "whisperAvailable": has_whisper,
        }
        if has_whisper and info["hasAudio"]:
            tx = transcribe_file_whisper(ffmpeg_bin, media_p, model_size=args.model, language=args.language)
            entry["transcription"] = tx
        else:
            entry["transcriptionNote"] = (
                "Whisper not yet installed in ~/.odinxd/preprod_env; returned acoustic speechIntervals. "
                "Pass auto_install=true to enable word-level transcription for mistake/retake detection."
            )
        results.append(entry)

    return {
        "filesCount": len(results),
        "files": results,
        "editorialGuidance": (
            "Inspect 'transcription.segments' (with exact word timestamps) across all takes to drop false starts, "
            "spoken mistakes, or repeated sentences, then pass your chosen clean [{'file', 'start', 'end'}] list "
            "to clean_and_merge_aroll."
        ),
    }


def cmd_clean_aroll(args: argparse.Namespace) -> Dict[str, Any]:
    ffmpeg_bin, ffprobe_bin = require_ffmpeg()
    output_mp4 = assert_safe_mp4_output(args.output, default_prefix="clean_aroll")

    segments: List[Dict[str, Any]] = []
    if args.segments_json:
        parsed = json.loads(args.segments_json)
        if not isinstance(parsed, list) or not parsed:
            raise ValueError("INVALID_SEGMENTS_JSON: Expected a non-empty JSON array of {file, start, end} objects.")
        for item in parsed:
            f_ref = item.get("file") or (args.inputs[0] if args.inputs else None)
            if not f_ref:
                raise ValueError("MISSING_SEGMENT_FILE: Each segment must include 'file' (or pass --inputs).")
            segments.append({
                "file": str(f_ref),
                "start": float(item["start"]),
                "end": float(item["end"]),
            })
    else:
        if not args.inputs:
            raise ValueError("MISSING_INPUTS: Provide --inputs or --segments-json.")
        for raw_p in args.inputs:
            media_p = assert_safe_media_input(raw_p)
            info = probe_media_info(ffprobe_bin, media_p)
            _, speech = detect_silences_ffmpeg(
                ffmpeg_bin,
                media_p,
                info["durationSec"],
                noise_db=args.silence_db,
                min_silence_sec=args.min_silence,
                pad_sec=args.pad_sec,
            )
            for sp in speech:
                segments.append({
                    "file": str(media_p),
                    "start": sp["start"],
                    "end": sp["end"],
                })

    if args.smart_reframe and not check_module_installed("cv2") and args.auto_install:
        provision_managed_environment()
        maybe_reexec_in_managed_venv()

    return render_clean_merged_aroll(
        ffmpeg_bin=ffmpeg_bin,
        ffprobe_bin=ffprobe_bin,
        segments=segments,
        output_mp4=output_mp4,
        smart_reframe=args.smart_reframe,
        normalize_audio=not args.no_loudnorm,
    )


def cmd_podcast(args: argparse.Namespace) -> Dict[str, Any]:
    ffmpeg_bin, ffprobe_bin = require_ffmpeg()
    src_video = resolve_podcast_source(args.source, auto_install=args.auto_install)
    info = probe_media_info(ffprobe_bin, src_video)

    if args.action == "analyze":
        if not check_module_installed("faster_whisper") and args.auto_install:
            provision_managed_environment()
            maybe_reexec_in_managed_venv()

        if not check_module_installed("faster_whisper"):
            raise RuntimeError(
                "WHISPER_REQUIRED_FOR_PODCAST: Run with auto_install=true so faster-whisper can transcribe the podcast."
            )

        tx = transcribe_file_whisper(ffmpeg_bin, src_video, model_size=args.model, language=args.language)
        # Group into ~30s blocks for compact LLM context window consumption on 1h+ podcasts
        blocks: List[Dict[str, Any]] = []
        cur_segs: List[Dict[str, Any]] = []
        block_start = 0.0
        for seg in tx["segments"]:
            if not cur_segs:
                block_start = seg["start"]
            cur_segs.append(seg)
            if seg["end"] - block_start >= 30.0:
                blocks.append({
                    "start": round(block_start, 3),
                    "end": round(seg["end"], 3),
                    "text": " ".join(s["text"] for s in cur_segs),
                })
                cur_segs = []
        if cur_segs:
            blocks.append({
                "start": round(block_start, 3),
                "end": round(cur_segs[-1]["end"], 3),
                "text": " ".join(s["text"] for s in cur_segs),
            })

        return {
            "action": "analyze",
            "localSourceVideo": str(src_video),
            "media": info,
            "detectedLanguage": tx["detectedLanguage"],
            "blocksCount": len(blocks),
            "blocks": blocks,
            "segments": tx["segments"],
            "nextStepHint": (
                "Select the strongest 25s–58s viral moments (exact sentence boundaries from 'segments'), then call "
                "extract_podcast_clips with action='extract' and clips=[{'start', 'end', 'title'}]. "
                "IMPORTANT ODINXD RULE: If the podcast features a celebrity or public figure, NEVER pass avatar_image "
                "or 'avatar_stock'; always render with faceless editorial AI styles like ['stock_hyperreal', 'scrapbook_polaroid'] "
                "or ['cinematic_macro', 'vox_editorial']."
            ),
        }

    # action == "extract"
    if not args.clips_json:
        raise ValueError("MISSING_CLIPS_JSON: action='extract' requires --clips-json with [{'start', 'end', 'title'}].")
    raw_clips = json.loads(args.clips_json)
    if not isinstance(raw_clips, list) or not raw_clips:
        raise ValueError("INVALID_CLIPS_JSON: Expected a non-empty JSON array of clip definitions.")

    if not check_module_installed("cv2") and args.auto_install:
        provision_managed_environment()
        maybe_reexec_in_managed_venv()

    out_dir = (
        assert_safe_local_path(args.output_dir, allow_dir=True, must_exist=False)
        if args.output_dir
        else (get_odin_home() / "preprod_exports" / f"podcast_{time.strftime('%Y%m%d_%H%M%S')}")
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    extracted: List[Dict[str, Any]] = []
    for idx, c in enumerate(raw_clips[:12], start=1):
        st = max(0.0, float(c["start"]))
        en = min(float(info["durationSec"]), float(c["end"]))
        if en - st < 3.0:
            continue
        title = str(c.get("title") or f"clip_{idx:02d}").strip()
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", title.lower()).strip("_")[:42] or f"clip_{idx:02d}"
        clip_mp4 = (out_dir / f"{idx:02d}_{slug}.mp4").resolve()

        res = render_clean_merged_aroll(
            ffmpeg_bin=ffmpeg_bin,
            ffprobe_bin=ffprobe_bin,
            segments=[{"file": str(src_video), "start": st, "end": en}],
            output_mp4=clip_mp4,
            smart_reframe=True,
            normalize_audio=True,
        )
        extracted.append({
            "index": idx,
            "title": title,
            "start": round(st, 3),
            "end": round(en, 3),
            "durationSec": res["durationSec"],
            "outputMp4": res["outputMp4"],
            "faceCenterXRatio": res["segmentsKept"][0]["faceCenterXRatio"] if res["segmentsKept"] else None,
        })

    return {
        "action": "extract",
        "sourceVideo": str(src_video),
        "outputDirectory": str(out_dir),
        "extractedCount": len(extracted),
        "clips": extracted,
        "celebritySafetyReminder": (
            "When sending third-party podcast clips to OdinxD (render_hybrid_reel or render_viral_beat), "
            "NEVER use 'avatar_stock' or pass famous faces in 'avatar_image'. Use ['stock_hyperreal', 'scrapbook_polaroid'], "
            "['cinematic_macro', 'vox_editorial'], or ['parallax_3d', 'mannequin_3d']."
        ),
    }


def cmd_stock_bank(args: argparse.Namespace) -> Dict[str, Any]:
    bank_root, clips_dir, thumbs_dir, index_file = get_stock_bank_paths()
    items = load_stock_index(index_file)

    if args.action == "list":
        cat = (args.category or "").strip().lower()
        filtered = [x for x in items if not cat or str(x.get("category", "")).lower() == cat]
        return {
            "bankDirectory": str(bank_root),
            "totalClips": len(items),
            "returnedClips": len(filtered[:50]),
            "clips": filtered[:50],
        }

    if args.action == "search":
        q_tokens = tokenize_tags(f"{args.query or ''} {args.category or ''}")
        scored: List[Tuple[int, Dict[str, Any]]] = []
        for item in items:
            if not Path(item.get("clipPath", "")).is_file():
                continue
            haystack = " ".join([
                str(item.get("category", "")),
                str(item.get("description", "")),
                " ".join(item.get("tags") or []),
                str(item.get("sourceFile", "")),
            ]).lower()
            if not q_tokens:
                score = 1
            else:
                score = sum(3 if tok in (item.get("tags") or []) else (1 if tok in haystack else 0) for tok in q_tokens)
            if score > 0:
                scored.append((score, item))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        limit = max(1, min(6, int(args.limit or 6)))
        top_items = [x[1] for x in scored[:limit]]
        return {
            "query": args.query or "",
            "matchedCount": len(top_items),
            "clips": top_items,
            "customStockParam": ",".join(x["clipPath"] for x in top_items),
            "usageHint": "Pass 'customStockParam' directly as the 'custom_stock' argument in render_hybrid_reel or render_viral_beat.",
        }

    if args.action == "tag":
        if not args.clip_id:
            raise ValueError("MISSING_CLIP_ID: action='tag' requires --clip-id.")
        updated_item = None
        new_tags = [t.strip().lower() for t in (args.tags or "").split(",") if t.strip()]
        for item in items:
            if item.get("id") == args.clip_id:
                if new_tags:
                    merged = list(dict.fromkeys([*(item.get("tags") or []), *new_tags]))
                    item["tags"] = merged
                if args.category:
                    item["category"] = args.category.strip().lower()
                if args.description:
                    item["description"] = args.description.strip()
                updated_item = item
                break
        if not updated_item:
            raise KeyError(f"CLIP_ID_NOT_FOUND: '{args.clip_id}' does not exist in ~/.odinxd/stock_bank/index.json")
        save_stock_index(index_file, items)
        return {"updated": True, "clip": updated_item}

    if args.action == "remove":
        if not args.clip_id:
            raise ValueError("MISSING_CLIP_ID: action='remove' requires --clip-id.")
        kept: List[Dict[str, Any]] = []
        removed = None
        for item in items:
            if item.get("id") == args.clip_id:
                removed = item
                for f_key in ("clipPath", "thumbnailPath"):
                    fp = Path(str(item.get(f_key) or ""))
                    if fp.is_file():
                        fp.unlink(missing_ok=True)
            else:
                kept.append(item)
        save_stock_index(index_file, kept)
        return {"removed": removed is not None, "clipId": args.clip_id, "remainingClips": len(kept)}

    # action == "ingest"
    if not args.source:
        raise ValueError("MISSING_SOURCE: action='ingest' requires --source (video file or folder path).")

    ffmpeg_bin, ffprobe_bin = require_ffmpeg()
    if not check_module_installed("scenedetect") and args.auto_install:
        provision_managed_environment()
        maybe_reexec_in_managed_venv()

    src_target = assert_safe_local_path(args.source, allow_dir=True, must_exist=True)
    video_files: List[Path] = []
    if src_target.is_dir():
        for p in sorted(src_target.rglob("*")):
            if p.is_file() and not p.is_symlink() and p.suffix.lower() in VIDEO_EXTENSIONS:
                try:
                    assert_safe_media_input(p)
                    video_files.append(p)
                except Exception:
                    continue
    else:
        video_files.append(assert_safe_media_input(src_target))

    if not video_files:
        raise ValueError(f"NO_VIDEOS_FOUND: No valid video files found in '{args.source}'.")

    clip_len = max(2.5, min(6.0, float(args.clip_duration or 4.0)))
    max_per_video = max(1, min(20, int(args.max_clips_per_video or 8)))
    base_tags = [t.strip().lower() for t in (args.tags or "").split(",") if t.strip()]
    category = (args.category or "general").strip().lower()

    created: List[Dict[str, Any]] = []
    for vf_path in video_files[:25]:
        info = probe_media_info(ffprobe_bin, vf_path)
        if not info["hasVideo"] or info["durationSec"] < 2.0:
            continue
        scenes = detect_scene_boundaries(ffmpeg_bin, vf_path, info["durationSec"])
        auto_tags = list(dict.fromkeys([*base_tags, category, *tokenize_tags(f"{vf_path.parent.name} {vf_path.stem}")]))

        for s_idx, (s_start, s_end) in enumerate(scenes[:max_per_video], start=1):
            avail = s_end - s_start
            if avail < 2.0:
                continue
            use_dur = round(min(clip_len, avail), 3)
            # Trim 0.15s after scene cut to avoid transition flash frames
            trim_start = round(s_start + (0.15 if avail - use_dur >= 0.2 else 0.0), 3)
            digest = hashlib.sha256(f"{vf_path}:{trim_start}:{use_dur}".encode("utf-8")).hexdigest()[:10]
            clip_id = f"stk_{digest}"

            if any(existing.get("id") == clip_id for existing in items):
                continue

            out_clip = (clips_dir / f"{clip_id}.mp4").resolve()
            out_thumb = (thumbs_dir / f"{clip_id}.jpg").resolve()
            vf_filter = build_vertical_vf_filter(info["width"], info["height"], None)

            subprocess.run(
                [
                    ffmpeg_bin, "-y", "-v", "error",
                    "-ss", f"{trim_start:.3f}",
                    "-t", f"{use_dur:.3f}",
                    "-i", str(vf_path),
                    "-an",
                    "-vf", vf_filter,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart",
                    str(out_clip),
                ],
                check=True,
                shell=False,
                timeout=180,
            )

            mid_sec = round(use_dur * 0.45, 3)
            subprocess.run(
                [
                    ffmpeg_bin, "-y", "-v", "error",
                    "-ss", f"{mid_sec:.3f}",
                    "-i", str(out_clip),
                    "-frames:v", "1",
                    "-vf", "scale=360:-2",
                    "-q:v", "4",
                    str(out_thumb),
                ],
                check=True,
                shell=False,
                timeout=60,
            )

            record = {
                "id": clip_id,
                "clipPath": str(out_clip),
                "thumbnailPath": str(out_thumb),
                "sourceFile": vf_path.name,
                "startSec": trim_start,
                "durationSec": use_dur,
                "category": category,
                "tags": auto_tags,
                "description": args.description or f"9:16 stock clip from {vf_path.stem} ({trim_start}s)",
                "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            items.append(record)
            created.append(record)

    save_stock_index(index_file, items)
    return {
        "ingestedCount": len(created),
        "totalBankClips": len(items),
        "bankDirectory": str(bank_root),
        "createdClips": created,
        "visionTaggingHint": (
            "Inspect 'thumbnailPath' JPEGs to see each clip visually and call manage_local_stock_bank "
            "with action='tag' to enrich semantic tags (e.g. 'cocina,marmol,luz_natural' or 'gym,pesas')."
        ),
    }


def _format_ass_time(seconds: float) -> str:
    s = max(0.0, float(seconds))
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = int(s % 60)
    cs = int(round((s - int(s)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{sec:02d}.{cs:02d}"


def _escape_ass_text(raw: str) -> str:
    txt = str(raw or "").replace("\\", "").replace("{", "(").replace("}", ")")
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def _parse_srt_entries(srt_text: str) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    blocks = re.split(r"\r?\n\r?\n+", (srt_text or "").strip())
    time_re = re.compile(
        r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{2,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{2,3})"
    )
    for b in blocks:
        lines = [ln.strip() for ln in b.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        m = None
        text_start_idx = 1
        for i, ln in enumerate(lines[:2]):
            cand = time_re.search(ln)
            if cand:
                m = cand
                text_start_idx = i + 1
                break
        if not m:
            continue
        ms1 = float(m.group(4).ljust(3, "0")[:3]) / 1000.0
        ms2 = float(m.group(8).ljust(3, "0")[:3]) / 1000.0
        st = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + ms1
        en = int(m.group(5)) * 3600 + int(m.group(6)) * 60 + int(m.group(7)) + ms2
        txt = " ".join(lines[text_start_idx:]).strip()
        if txt and en > st:
            entries.append({"start": st, "end": en, "text": txt})
    return entries


def _build_ass_document(
    cues: List[Dict[str, Any]],
    play_res_x: int,
    play_res_y: int,
    preset: str = "ugc_clean",
) -> str:
    is_vertical = play_res_y >= play_res_x
    font_size = 64 if is_vertical else 52
    margin_v = 290 if is_vertical else 90

    # ASS colors use &HAABBGGRR format
    styles = {
        "ugc_clean": {
            "font": "Arial",
            "size": font_size,
            "primary": "&H00FFFFFF",
            "outline_color": "&H00000000",
            "back_color": "&H64000000",
            "border_style": 1,
            "outline": 4,
            "shadow": 2,
            "bold": -1,
            "uppercase": False,
        },
        "cinema_yellow": {
            "font": "Arial",
            "size": int(font_size * 0.92),
            "primary": "&H0038D4FF",
            "outline_color": "&H00000000",
            "back_color": "&H64000000",
            "border_style": 1,
            "outline": 4,
            "shadow": 2,
            "bold": -1,
            "uppercase": False,
        },
        "boxed_impact": {
            "font": "Arial",
            "size": int(font_size * 1.02),
            "primary": "&H00FFFFFF",
            "outline_color": "&H30101010",
            "back_color": "&H30101010",
            "border_style": 3,
            "outline": 14,
            "shadow": 0,
            "bold": -1,
            "uppercase": True,
        },
        "minimal_luxury": {
            "font": "Georgia",
            "size": int(font_size * 0.88),
            "primary": "&H00F2F5F8",
            "outline_color": "&H00121212",
            "back_color": "&H50000000",
            "border_style": 1,
            "outline": 3,
            "shadow": 1,
            "bold": 0,
            "uppercase": False,
        },
    }
    st = styles.get(preset, styles["ugc_clean"])

    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {play_res_x}",
        f"PlayResY: {play_res_y}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        (
            f"Style: Default,{st['font']},{st['size']},{st['primary']},&H000000FF,"
            f"{st['outline_color']},{st['back_color']},{st['bold']},0,0,0,100,100,0,0,"
            f"{st['border_style']},{st['outline']},{st['shadow']},2,80,80,{margin_v},1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    for c in cues:
        txt = _escape_ass_text(c.get("text") or "")
        if not txt:
            continue
        if st["uppercase"]:
            txt = txt.upper()
        t0 = _format_ass_time(float(c["start"]))
        t1 = _format_ass_time(max(float(c["start"]) + 0.18, float(c["end"])))
        header.append(f"Dialogue: 0,{t0},{t1},Default,,0,0,0,,{{\\fad(60,60)}}{txt}")

    return "\n".join(header) + "\n"


def _whisper_segments_to_short_cues(segments: List[Dict[str, Any]], max_words: int = 4) -> List[Dict[str, Any]]:
    cues: List[Dict[str, Any]] = []
    for seg in segments:
        words = seg.get("words") or []
        if words:
            chunk: List[Dict[str, Any]] = []
            for w in words:
                w_txt = str(w.get("word") or "").strip()
                if not w_txt:
                    continue
                chunk.append(w)
                ends_punct = w_txt.endswith((".", ",", "!", "?", ";", ":"))
                if len(chunk) >= max_words or (len(chunk) >= 2 and ends_punct):
                    cues.append({
                        "start": float(chunk[0]["start"]),
                        "end": float(chunk[-1]["end"]),
                        "text": " ".join(str(x["word"]).strip() for x in chunk),
                    })
                    chunk = []
            if chunk:
                cues.append({
                    "start": float(chunk[0]["start"]),
                    "end": float(chunk[-1]["end"]),
                    "text": " ".join(str(x["word"]).strip() for x in chunk),
                })
        else:
            txt = str(seg.get("text") or "").strip()
            if txt:
                cues.append({"start": float(seg["start"]), "end": float(seg["end"]), "text": txt})
    return cues


def cmd_voiceover(args: argparse.Namespace) -> Dict[str, Any]:
    _, ffprobe_bin = require_ffmpeg()
    if not check_module_installed("edge_tts"):
        if args.auto_install:
            provision_managed_environment()
            maybe_reexec_in_managed_venv()
        if not check_module_installed("edge_tts"):
            raise RuntimeError(
                "EDGE_TTS_NOT_INSTALLED: Run local_preprod_doctor with auto_install=true to enable local neural voiceover."
            )

    import asyncio
    import edge_tts  # type: ignore

    text = str(args.text or "").strip()
    if not text and args.text_file:
        tf = assert_safe_local_path(args.text_file, allow_dir=False, must_exist=True)
        text = tf.read_text(encoding="utf-8").strip()
    if len(text) < 2:
        raise ValueError("EMPTY_VOICEOVER_TEXT: Provide non-empty narration text.")

    raw_voice = str(args.voice or "es_mx_male").strip()
    resolved_voice = LOCAL_VOICEOVER_PRESETS.get(raw_voice.lower(), raw_voice)
    rate_str = str(args.rate or "+0%").strip()
    if not re.match(r"^[+-]\d{1,2}%$", rate_str):
        rate_str = "+0%"

    if args.output:
        out_mp3 = assert_safe_local_path(args.output, allow_dir=True, must_exist=False)
        if out_mp3.exists() and out_mp3.is_dir():
            out_mp3 = out_mp3 / f"voiceover_{time.strftime('%Y%m%d_%H%M%S')}.mp3"
        if out_mp3.suffix.lower() != ".mp3":
            out_mp3 = out_mp3.with_suffix(".mp3")
    else:
        out_dir = get_odin_home() / "preprod_exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_mp3 = (out_dir / f"voiceover_{time.strftime('%Y%m%d_%H%M%S')}.mp3").resolve()

    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    out_srt = out_mp3.with_suffix(".srt")

    async def _synthesize() -> None:
        comm = edge_tts.Communicate(text, resolved_voice, rate=rate_str)
        submaker = edge_tts.SubMaker()
        with open(out_mp3, "wb") as f_audio:
            async for chunk in comm.stream():
                c_type = chunk.get("type")
                if c_type == "audio":
                    f_audio.write(chunk["data"])
                elif c_type in ("WordBoundary", "SentenceBoundary"):
                    if hasattr(submaker, "feed"):
                        submaker.feed(chunk)
                    elif hasattr(submaker, "create_sub"):
                        submaker.create_sub((chunk["offset"], chunk["duration"]), chunk["text"])
        srt_content = submaker.get_srt() if hasattr(submaker, "get_srt") else submaker.generate_subs()
        out_srt.write_text(srt_content or "", encoding="utf-8")

    asyncio.run(_synthesize())
    info = probe_media_info(ffprobe_bin, out_mp3)

    return {
        "audioPath": str(out_mp3),
        "srtPath": str(out_srt) if out_srt.is_file() and out_srt.stat().st_size > 0 else None,
        "durationSec": info["durationSec"],
        "voiceUsed": resolved_voice,
        "creditsCharged": 0,
        "nextStepHint": (
            "Generate cinematic clips matching 'durationSec' via generate_ai_video_batch(clip_mode='cinematic_faceless'), "
            "then stitch everything locally with assemble_local_timeline(audio_mode='voiceover_master', voiceover_path=audioPath, subtitles='srt', srt_path=srtPath)."
        ),
    }


def cmd_assemble(args: argparse.Namespace) -> Dict[str, Any]:
    ffmpeg_bin, ffprobe_bin = require_ffmpeg()
    output_mp4 = assert_safe_mp4_output(args.output, default_prefix="master_timeline")

    clip_list: List[str] = []
    if args.clips_json:
        parsed_c = json.loads(args.clips_json)
        if isinstance(parsed_c, list):
            for entry in parsed_c:
                if isinstance(entry, str) and entry.strip():
                    clip_list.append(entry.strip())
                elif isinstance(entry, dict) and entry.get("path"):
                    clip_list.append(str(entry["path"]).strip())
    if args.clips:
        clip_list.extend([c for c in args.clips if c and str(c).strip()])

    if not clip_list:
        raise ValueError("MISSING_CLIPS: Provide at least 1 video clip path to assemble.")

    is_16_9 = str(args.aspect_ratio or "9:16").strip() == "16:9"
    target_w = 1920 if is_16_9 else 1080
    target_h = 1080 if is_16_9 else 1920

    audio_mode = str(args.audio_mode or "keep_native").strip().lower()
    voiceover_p = assert_safe_media_input(args.voiceover) if args.voiceover else None
    bg_music_p = assert_safe_media_input(args.bg_music) if args.bg_music else None
    if audio_mode == "voiceover_master" and not voiceover_p:
        raise ValueError("VOICEOVER_REQUIRED: audio_mode='voiceover_master' requires --voiceover <path.mp3>.")

    sub_mode = str(args.subtitles or "none").strip().lower()
    if sub_mode == "auto_whisper" and not check_module_installed("faster_whisper"):
        if args.auto_install:
            provision_managed_environment()
            maybe_reexec_in_managed_venv()
        if not check_module_installed("faster_whisper"):
            raise RuntimeError("WHISPER_NOT_INSTALLED: Pass auto_install=true to burn auto_whisper subtitles.")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        norm_parts: List[Path] = []
        part_durations: List[float] = []

        for idx, raw_clip in enumerate(clip_list[:30]):
            c_path = assert_safe_media_input(raw_clip)
            c_info = probe_media_info(ffprobe_bin, c_path)
            if not c_info["hasVideo"] or c_info["durationSec"] < 0.3:
                continue

            dur = float(c_info["durationSec"])
            fade_d = min(0.03, dur * 0.1)
            fade_out_st = max(0.0, dur - fade_d)

            vf = (
                f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop={target_w}:{target_h},setsar=1,fps=30,format=yuv420p"
            )
            part_ts = tmp_root / f"clip_{idx:03d}.mp4"
            cmd_norm = [ffmpeg_bin, "-y", "-v", "error", "-i", str(c_path), "-vf", vf]
            if c_info["hasAudio"]:
                af = (
                    f"aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                    f"afade=t=in:st=0:d={fade_d:.3f},afade=t=out:st={fade_out_st:.3f}:d={fade_d:.3f}"
                )
                cmd_norm.extend(["-af", af, "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"])
            else:
                cmd_norm.extend(["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"])
                cmd_norm.extend(["-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "128k", "-shortest"])

            cmd_norm.extend([
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
                str(part_ts),
            ])
            subprocess.run(cmd_norm, check=True, shell=False, timeout=300)
            norm_parts.append(part_ts)
            part_durations.append(dur)

        if not norm_parts:
            raise ValueError("NO_VALID_CLIPS: None of the supplied clip files contained a valid video stream.")

        stitched_mp4 = tmp_root / "stitched_raw.mp4"
        use_xfade = str(args.transition or "cut").lower() == "crossfade" and len(norm_parts) >= 2 and len(norm_parts) <= 12
        xfade_dur = 0.25

        if use_xfade:
            xf_cmd = [ffmpeg_bin, "-y", "-v", "error"]
            for p in norm_parts:
                xf_cmd.extend(["-i", str(p)])
            filter_parts: List[str] = []
            offset = part_durations[0] - xfade_dur
            prev_v = "[0:v]"
            prev_a = "[0:a]"
            for i in range(1, len(norm_parts)):
                out_v = f"[v{i}]"
                out_a = f"[a{i}]"
                safe_off = max(0.05, offset)
                filter_parts.append(f"{prev_v}[{i}:v]xfade=transition=fade:duration={xfade_dur:.2f}:offset={safe_off:.3f}{out_v}")
                filter_parts.append(f"{prev_a}[{i}:a]acrossfade=d={xfade_dur:.2f}{out_a}")
                prev_v = out_v
                prev_a = out_a
                offset = safe_off + part_durations[i] - xfade_dur
            xf_cmd.extend([
                "-filter_complex", ";".join(filter_parts),
                "-map", prev_v, "-map", prev_a,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                str(stitched_mp4),
            ])
            subprocess.run(xf_cmd, check=True, shell=False, timeout=600)
        else:
            concat_txt = tmp_root / "concat.txt"
            concat_txt.write_text("\n".join(f"file '{p.as_posix()}'" for p in norm_parts) + "\n", encoding="utf-8")
            subprocess.run(
                [
                    ffmpeg_bin, "-y", "-v", "error",
                    "-f", "concat", "-safe", "0", "-i", str(concat_txt),
                    "-c", "copy",
                    str(stitched_mp4),
                ],
                check=True,
                shell=False,
                timeout=300,
            )

        stitched_info = probe_media_info(ffprobe_bin, stitched_mp4)
        total_dur = max(0.5, float(stitched_info["durationSec"]))
        sfx_vol = max(0.0, min(1.0, float(args.sfx_volume if args.sfx_volume is not None else 0.16)))
        music_vol = max(0.0, min(0.8, float(args.music_volume if args.music_volume is not None else 0.10)))

        mixed_mp4 = tmp_root / "mixed_audio.mp4"
        mix_cmd = [ffmpeg_bin, "-y", "-v", "error", "-i", str(stitched_mp4)]
        input_idx = 1
        vo_idx: Optional[int] = None
        bgm_idx: Optional[int] = None

        if voiceover_p and audio_mode == "voiceover_master":
            vo_info = probe_media_info(ffprobe_bin, voiceover_p)
            total_dur = max(total_dur, min(total_dur + 1.5, float(vo_info["durationSec"])))
            mix_cmd.extend(["-i", str(voiceover_p)])
            vo_idx = input_idx
            input_idx += 1

        if bg_music_p:
            mix_cmd.extend(["-stream_loop", "-1", "-i", str(bg_music_p)])
            bgm_idx = input_idx
            input_idx += 1

        fc_audio: List[str] = []
        mix_inputs: List[str] = []
        if vo_idx is not None:
            fc_audio.append(f"[0:a]volume={sfx_vol:.3f}[sfx]")
            fc_audio.append(f"[{vo_idx}:a]aresample=48000,volume=1.0[vo]")
            mix_inputs.extend(["[vo]", "[sfx]"])
        else:
            fc_audio.append("[0:a]aresample=48000,volume=1.0[nat]")
            mix_inputs.append("[nat]")

        if bgm_idx is not None:
            fade_m_st = max(0.0, total_dur - 1.5)
            fc_audio.append(
                f"[{bgm_idx}:a]atrim=0:{total_dur:.3f},aresample=48000,volume={music_vol:.3f},"
                f"afade=t=out:st={fade_m_st:.3f}:d=1.50[bgm]"
            )
            mix_inputs.append("[bgm]")

        if len(mix_inputs) == 1:
            fc_audio.append(f"{mix_inputs[0]}loudnorm=I=-16:TP=-1.5:LRA=11[aout]")
        else:
            fc_audio.append(
                f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=0,"
                f"loudnorm=I=-16:TP=-1.5:LRA=11[aout]"
            )

        mix_cmd.extend([
            "-filter_complex", ";".join(fc_audio),
            "-map", "0:v:0",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-shortest",
            str(mixed_mp4),
        ])
        subprocess.run(mix_cmd, check=True, shell=False, timeout=300)

        cues: List[Dict[str, Any]] = []
        if sub_mode == "srt" and args.srt_file:
            srt_p = assert_safe_local_path(args.srt_file, allow_dir=False, must_exist=True)
            cues = _parse_srt_entries(srt_p.read_text(encoding="utf-8", errors="replace"))
        elif sub_mode == "auto_whisper":
            tx = transcribe_file_whisper(ffmpeg_bin, mixed_mp4, model_size=args.whisper_model or "base", language=args.language)
            cues = _whisper_segments_to_short_cues(tx.get("segments") or [], max_words=4)

        if cues:
            ass_file = tmp_root / "captions.ass"
            ass_file.write_text(
                _build_ass_document(cues, target_w, target_h, preset=args.subtitle_preset or "ugc_clean"),
                encoding="utf-8",
            )
            # CRITICAL WINDOWS FIX: Run ffmpeg with cwd=tmp_root and relative 'ass=captions.ass' to avoid C:\ colon bug!
            subprocess.run(
                [
                    ffmpeg_bin, "-y", "-v", "error",
                    "-i", "mixed_audio.mp4",
                    "-vf", "ass=captions.ass",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
                    "-c:a", "copy",
                    "-movflags", "+faststart",
                    str(output_mp4),
                ],
                cwd=str(tmp_root),
                check=True,
                shell=False,
                timeout=600,
            )
        else:
            subprocess.run(
                [
                    ffmpeg_bin, "-y", "-v", "error",
                    "-i", str(mixed_mp4),
                    "-c", "copy",
                    "-movflags", "+faststart",
                    str(output_mp4),
                ],
                check=True,
                shell=False,
                timeout=180,
            )

    final_info = probe_media_info(ffprobe_bin, output_mp4)
    return {
        "outputMp4": str(output_mp4),
        "durationSec": final_info["durationSec"],
        "width": final_info["width"],
        "height": final_info["height"],
        "fps": final_info["fps"],
        "clipsCount": len(norm_parts),
        "clipsAssembledCount": len(norm_parts),
        "audioMode": audio_mode,
        "subtitlesBurned": len(cues) > 0,
        "subtitleCuesCount": len(cues),
        "odinxdServerRenderCreditsUsed": 0,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="OdinMCP Local Video Pre-Production Studio CLI")
    sub = p.add_subparsers(dest="subcommand", required=True)

    p_doc = sub.add_parser("doctor", help="Check or provision local pre-production dependencies")
    p_doc.add_argument("--install", action="store_true", help="Create ~/.odinxd/preprod_env and install wheels")

    p_tx = sub.add_parser("transcribe", help="Transcribe local media with word timestamps and silence detection")
    p_tx.add_argument("--inputs", nargs="+", required=True, help="1 or more local video/audio files")
    p_tx.add_argument("--model", default="base", choices=["tiny", "base", "small", "medium"])
    p_tx.add_argument("--language", default="auto")
    p_tx.add_argument("--silence-db", type=float, default=-35.0)
    p_tx.add_argument("--min-silence", type=float, default=0.65)
    p_tx.add_argument("--auto-install", action="store_true")

    p_cl = sub.add_parser("clean-aroll", help="Remove silences/bad takes and merge into ONE clean 9:16 MP4")
    p_cl.add_argument("--inputs", nargs="*", default=[])
    p_cl.add_argument("--segments-json", default="")
    p_cl.add_argument("--output", default="")
    p_cl.add_argument("--silence-db", type=float, default=-35.0)
    p_cl.add_argument("--min-silence", type=float, default=0.65)
    p_cl.add_argument("--pad-sec", type=float, default=0.12)
    p_cl.add_argument("--smart-reframe", action="store_true", default=True)
    p_cl.add_argument("--no-smart-reframe", dest="smart_reframe", action="store_false")
    p_cl.add_argument("--no-loudnorm", action="store_true")
    p_cl.add_argument("--auto-install", action="store_true")

    p_pod = sub.add_parser("podcast", help="Analyze or extract 9:16 clips from a podcast file or URL")
    p_pod.add_argument("--action", required=True, choices=["analyze", "extract"])
    p_pod.add_argument("--source", required=True, help="Local video path or public video URL")
    p_pod.add_argument("--clips-json", default="")
    p_pod.add_argument("--output-dir", default="")
    p_pod.add_argument("--model", default="base", choices=["tiny", "base", "small", "medium"])
    p_pod.add_argument("--language", default="auto")
    p_pod.add_argument("--auto-install", action="store_true")

    p_stk = sub.add_parser("stock-bank", help="Build, tag, and search the local 9:16 B-Roll stock bank")
    p_stk.add_argument("--action", required=True, choices=["ingest", "search", "list", "tag", "remove"])
    p_stk.add_argument("--source", default="")
    p_stk.add_argument("--query", default="")
    p_stk.add_argument("--category", default="")
    p_stk.add_argument("--tags", default="")
    p_stk.add_argument("--description", default="")
    p_stk.add_argument("--clip-id", default="")
    p_stk.add_argument("--clip-duration", type=float, default=4.0)
    p_stk.add_argument("--max-clips-per-video", type=int, default=8)
    p_stk.add_argument("--limit", type=int, default=6)
    p_stk.add_argument("--auto-install", action="store_true")

    p_vo = sub.add_parser("voiceover", help="Synthesize free local neural voiceover MP3 + SRT via edge-tts")
    p_vo.add_argument("--text", default="", help="Narration script text")
    p_vo.add_argument("--text-file", default="", help="Optional path to UTF-8 script text file")
    p_vo.add_argument("--voice", default="es_mx_male", help="Preset (e.g. es_mx_male, en_male_cinema) or Edge voice name")
    p_vo.add_argument("--rate", default="+0%", help="Speech rate offset e.g. '+5%%' or '-5%%'")
    p_vo.add_argument("--output", default="", help="Output MP3 path")
    p_vo.add_argument("--auto-install", action="store_true")

    p_asm = sub.add_parser("assemble", help="Stitch AI clips locally into a finished 1080x1920 / 1920x1080 master MP4")
    p_asm.add_argument("--clips", nargs="*", default=[], help="Ordered local MP4 clip paths")
    p_asm.add_argument("--clips-json", default="", help="JSON array of clip paths")
    p_asm.add_argument("--output", default="", help="Destination master MP4 path")
    p_asm.add_argument("--aspect-ratio", default="9:16", choices=["9:16", "16:9"])
    p_asm.add_argument("--audio-mode", default="keep_native", choices=["keep_native", "voiceover_master"])
    p_asm.add_argument("--voiceover", default="", help="Local voiceover MP3/WAV path when audio-mode=voiceover_master")
    p_asm.add_argument("--bg-music", default="", help="Optional local background music MP3/WAV path")
    p_asm.add_argument("--sfx-volume", type=float, default=0.16)
    p_asm.add_argument("--music-volume", type=float, default=0.10)
    p_asm.add_argument("--transition", default="cut", choices=["cut", "crossfade"])
    p_asm.add_argument("--subtitles", default="none", choices=["none", "auto_whisper", "srt"])
    p_asm.add_argument("--srt-file", default="", help="Optional SRT file path when subtitles=srt")
    p_asm.add_argument(
        "--subtitle-preset",
        default="ugc_clean",
        choices=["ugc_clean", "cinema_yellow", "boxed_impact", "minimal_luxury"],
    )
    p_asm.add_argument("--whisper-model", default="base", choices=["tiny", "base", "small", "medium"])
    p_asm.add_argument("--language", default="auto")
    p_asm.add_argument("--auto-install", action="store_true")

    return p


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    maybe_reexec_in_managed_venv()
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.subcommand == "doctor":
            payload = cmd_doctor(args)
        elif args.subcommand == "transcribe":
            payload = cmd_transcribe(args)
        elif args.subcommand == "clean-aroll":
            payload = cmd_clean_aroll(args)
        elif args.subcommand == "podcast":
            payload = cmd_podcast(args)
        elif args.subcommand == "stock-bank":
            payload = cmd_stock_bank(args)
        elif args.subcommand == "voiceover":
            payload = cmd_voiceover(args)
        elif args.subcommand == "assemble":
            payload = cmd_assemble(args)
        else:
            raise ValueError(f"Unknown subcommand: {args.subcommand}")

        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    except Exception as exc:
        err_payload = {
            "error": str(exc),
            "type": type(exc).__name__,
        }
        sys.stdout.write(json.dumps(err_payload, indent=2, ensure_ascii=False) + "\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
