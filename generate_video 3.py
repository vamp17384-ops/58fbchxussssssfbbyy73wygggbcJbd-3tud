#!/usr/bin/env python3
"""
Reddit Story Video Bot
- Story  : Gemini 2.5 Flash (free API key, no billing required)
- Voice  : gTTS + ffmpeg atempo speed-up (faster, less robotic)
- Video  : FFmpeg
- Upload : rclone -> Google Drive
- Host   : GitHub Actions daily cron
"""

import os, sys, json, random, subprocess, tempfile
from pathlib import Path
from datetime import datetime

import requests
from gtts import gTTS

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════
GEMINI_API_KEY    = os.environ["GEMINI_API_KEY"]
RCLONE_CONFIG_B64 = os.environ["RCLONE_CONFIG_B64"]
GDRIVE_FOLDER     = os.getenv("GDRIVE_FOLDER", "RedditStoryBot")

VIDEO_W, VIDEO_H  = 1080, 1920
MAX_SECONDS       = 58
WORDS_PER_SUB     = 4       # words per caption card — 4 is easy to read
TTS_TLD           = "com"   # "com"=US  "co.uk"=British  "com.au"=Australian
TTS_SPEED         = 1.25    # speed multiplier applied after TTS generation

SUBREDDITS = [
    "AITA", "tifu", "relationship_advice",
    "TrueOffMyChest", "confession",
    "entitledparents", "ProRevenge", "pettyrevenge",
]

BACKGROUND_DIR = Path("backgrounds")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Generate story
# ══════════════════════════════════════════════════════════════════════════════
def generate_story() -> dict:
    sub = random.choice(SUBREDDITS)
    print(f"  Subreddit : r/{sub}")

    prompt = f"""Write a Reddit story for r/{sub}.

Rules:
- Story body: 180 to 220 words
- First-person, past tense, emotionally engaging
- Clear setup, conflict, and resolution or twist
- No Edit sections, no usernames, no markdown
- Title: Reddit-style question or statement"""

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.85,
            "maxOutputTokens": 2000,
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "object",
                "properties": {
                    "title":     {"type": "string"},
                    "subreddit": {"type": "string"},
                    "story":     {"type": "string"},
                },
                "required": ["title", "subreddit", "story"],
            },
        },
    }
    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    data = json.loads(resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip())
    print(f"  Title     : {data['title']}")
    print(f"  Words     : {len(data['story'].split())}")
    return data


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — TTS then speed up with ffmpeg atempo
# ══════════════════════════════════════════════════════════════════════════════
def text_to_speech(text: str, out_mp3: str):
    raw = out_mp3 + "_raw.mp3"
    gTTS(text=text, lang="en", tld=TTS_TLD, slow=False).save(raw)

    # atempo speeds up audio without changing pitch; max single value is 2.0
    subprocess.run([
        "ffmpeg", "-y", "-i", raw,
        "-filter:a", f"atempo={TTS_SPEED}",
        "-q:a", "3", out_mp3
    ], capture_output=True, check=True)

    os.remove(raw)
    print(f"  Audio saved (x{TTS_SPEED} speed)")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Pick background
# ══════════════════════════════════════════════════════════════════════════════
def pick_background() -> str:
    videos = list(BACKGROUND_DIR.glob("*.mp4")) + list(BACKGROUND_DIR.glob("*.mov"))
    if not videos:
        raise FileNotFoundError(
            f"No .mp4 files in {BACKGROUND_DIR}/ — add royalty-free clips.\n"
            "Free sources: pexels.com/videos  pixabay.com/videos"
        )
    choice = random.choice(videos)
    print(f"  Background: {choice.name}")
    return str(choice)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — Audio duration
# ══════════════════════════════════════════════════════════════════════════════
def get_duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(r.stdout.strip())


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5 — SRT subtitles (timed to sped-up audio)
# ══════════════════════════════════════════════════════════════════════════════
def build_srt(text: str, duration: float, srt_path: str):
    words = text.split()
    chunks = [words[i:i+WORDS_PER_SUB] for i in range(0, len(words), WORDS_PER_SUB)]
    spw = duration / max(len(words), 1)  # seconds per word

    lines, t = [], 0.0
    for idx, chunk in enumerate(chunks, 1):
        end = t + spw * len(chunk)
        lines += [str(idx), f"{_ts(t)} --> {_ts(end)}", " ".join(chunk), ""]
        t = end

    Path(srt_path).write_text("\n".join(lines))
    print(f"  Subtitles: {len(chunks)} cards")


def _ts(s: float) -> str:
    h, m = int(s // 3600), int((s % 3600) // 60)
    return f"{h:02}:{m:02}:{int(s%60):02},{int((s%1)*1000):03}"


# ══════════════════════════════════════════════════════════════════════════════
# STEP 6 — Compose video
#   - NO badge, NO dark band, NO title overlay
#   - Captions: small (FontSize=26), centered bottom, word-synced, box background
# ══════════════════════════════════════════════════════════════════════════════
def compose_video(bg: str, audio: str, srt: str, duration: float, out: str):
    srt_esc = srt.replace("\\", "/").replace(":", "\\:")

    fg = (
        f"[0:v]"
        f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=increase,"
        f"crop={VIDEO_W}:{VIDEO_H},fps=30,"
        f"eq=brightness=-0.05:saturation=1.15"
        f"[bg];"

        f"[bg]subtitles='{srt_esc}':"
        f"force_style='"
        f"FontName=DejaVu Sans Bold,"
        f"FontSize=26,"
        f"PrimaryColour=&H00FFFFFF,"
        f"OutlineColour=&H00000000,"
        f"BackColour=&HBB000000,"
        f"BorderStyle=4,"
        f"Outline=2,Shadow=0,"
        f"Alignment=2,"
        f"MarginV=150,"
        f"MarginL=80,MarginR=80"
        f"'"
        f"[out]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", bg,
        "-i", audio,
        "-filter_complex", fg,
        "-map", "[out]", "-map", "1:a",
        "-t", str(min(duration + 0.5, MAX_SECONDS)),
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", "-pix_fmt", "yuv420p",
        out,
    ]
    print("  Rendering…")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("FFmpeg error:\n", r.stderr[-3000:])
        raise RuntimeError("FFmpeg failed")
    print(f"  Video: {out}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 7 — Upload via rclone
# ══════════════════════════════════════════════════════════════════════════════
def upload(local_path: str, filename: str) -> str:
    import base64, tempfile as tf

    cfg_bytes = base64.b64decode(RCLONE_CONFIG_B64)
    cfg_file  = tf.NamedTemporaryFile(suffix=".conf", delete=False, mode="wb")
    cfg_file.write(cfg_bytes)
    cfg_file.close()

    dest = f"gdrive:{GDRIVE_FOLDER}/{filename}"
    print(f"  Uploading to {dest}…")

    r = subprocess.run(
        ["rclone", "--config", cfg_file.name, "copyto", local_path, dest],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print("rclone error:", r.stderr)
        return "(upload failed)"

    lr = subprocess.run(
        ["rclone", "--config", cfg_file.name, "link", dest],
        capture_output=True, text=True,
    )
    link = lr.stdout.strip() if lr.returncode == 0 else dest
    print(f"  Uploaded: {link}")
    return link


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    print("\n Reddit Story Bot  " + datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
    print("-" * 48)

    stamp      = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    video_name = f"reddit_{stamp}.mp4"
    out_dir    = Path("output")
    out_dir.mkdir(exist_ok=True)
    video_path = str(out_dir / video_name)

    with tempfile.TemporaryDirectory() as tmp:
        audio = os.path.join(tmp, "audio.mp3")
        srt   = os.path.join(tmp, "subs.srt")

        print("\n[1/5] Generating story…")
        story = generate_story()

        print("\n[2/5] Text-to-speech…")
        text_to_speech(story["story"], audio)

        print("\n[3/5] Picking background…")
        bg = pick_background()

        print("\n[4/5] Composing video…")
        dur = get_duration(audio)
        build_srt(story["story"], dur, srt)
        compose_video(bg, audio, srt, dur, video_path)

        print("\n[5/5] Uploading…")
        link = upload(video_path, video_name)

    summary = os.getenv("GITHUB_STEP_SUMMARY", "")
    if summary:
        with open(summary, "a") as f:
            f.write(f"## Reddit Story Bot\n")
            f.write(f"**Title:** {story['title']}\n\n")
            f.write(f"**Subreddit:** r/{story['subreddit']}\n\n")
            f.write(f"**Drive link:** {link}\n\n")
            f.write(f"**Video:** `{video_name}`\n")

    print(f"\nDone! {story['title']}\nDrive: {link}\n")


if __name__ == "__main__":
    main()
