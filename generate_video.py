#!/usr/bin/env python3
"""
Reddit Story Video Bot
- Story  : Gemini 2.5 Flash (free)
- Voice  : edge-tts — Microsoft neural voices, free, no API key, very human
- Video  : FFmpeg — one word at a time, dead center screen
- Upload : rclone -> Google Drive
- Host   : GitHub Actions daily cron
"""

import os, sys, json, random, subprocess, tempfile, asyncio
from pathlib import Path
from datetime import datetime

import requests

# edge-tts installed by workflow
try:
    import edge_tts
except ImportError:
    sys.exit("Run: pip install edge-tts")

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════
GEMINI_API_KEY    = os.environ["GEMINI_API_KEY"]
RCLONE_CONFIG_B64 = os.environ["RCLONE_CONFIG_B64"]
GDRIVE_FOLDER     = os.getenv("GDRIVE_FOLDER", "RedditStoryBot")

VIDEO_W, VIDEO_H  = 1080, 1920

# Microsoft neural voices — all free via edge-tts, pick your favourite:
# "en-US-GuyNeural"      — US male, natural
# "en-US-JennyNeural"    — US female, warm
# "en-US-AriaNeural"     — US female, expressive
# "en-GB-RyanNeural"     — British male
# "en-AU-NatashaNeural"  — Australian female
TTS_VOICE = "en-US-GuyNeural"
TTS_RATE  = "+15%"   # speaking speed: +0% normal, +15% slightly fast, +25% faster

SUBREDDITS = [
    "AITA", "tifu", "relationship_advice",
    "TrueOffMyChest", "confession",
    "entitledparents", "ProRevenge", "pettyrevenge",
]

BACKGROUND_DIR = Path("backgrounds")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Generate story (no word cap — full story)
# ══════════════════════════════════════════════════════════════════════════════
def generate_story() -> dict:
    sub = random.choice(SUBREDDITS)
    print(f"  Subreddit : r/{sub}")

    prompt = f"""Write a Reddit story for r/{sub}.

Rules:
- Story body: exactly 120 to 150 words (short = fits in a 60s short)
- First-person, past tense, emotionally engaging
- Clear setup, conflict, and satisfying resolution or twist
- No "Edit:" sections, no usernames, no markdown
- Title: Reddit-style question or punchy statement"""

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
# STEP 2 — Edge TTS: neural voice + word-level timestamps
#   edge-tts returns a subtitle file (.vtt) with word timings automatically.
#   We convert that to SRT for ffmpeg.
# ══════════════════════════════════════════════════════════════════════════════
async def _run_tts(text: str, mp3_path: str, vtt_path: str):
    communicate = edge_tts.Communicate(text, TTS_VOICE, rate=TTS_RATE)
    submaker    = edge_tts.SubMaker()
    with open(mp3_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                submaker.feed(chunk)
    # write word-level VTT
    with open(vtt_path, "w", encoding="utf-8") as f:
        f.write(submaker.get_srt())   # edge-tts >=7.0 has get_srt()


def text_to_speech(text: str, mp3_path: str, srt_path: str):
    """Generate MP3 + word-timed SRT via Microsoft Edge TTS (free, neural)."""
    vtt_path = mp3_path + ".vtt"
    asyncio.run(_run_tts(text, mp3_path, vtt_path))

    # edge-tts get_srt() already writes SRT format directly
    # just move it to srt_path
    Path(vtt_path).rename(srt_path)
    print(f"  Voice     : {TTS_VOICE} @ rate {TTS_RATE}")
    print(f"  Audio     : {mp3_path}")
    print(f"  Subtitles : {srt_path}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Pick background
# ══════════════════════════════════════════════════════════════════════════════
def pick_background() -> str:
    videos = list(BACKGROUND_DIR.glob("*.mp4")) + list(BACKGROUND_DIR.glob("*.mov"))
    if not videos:
        raise FileNotFoundError(
            f"No .mp4 files in {BACKGROUND_DIR}/\n"
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
# STEP 5 — Compose video
#   - No badge, no band, no title overlay
#   - One word at a time, DEAD CENTER of screen
#   - SRT comes from edge-tts word boundaries — perfectly synced
#   - Video length = audio length (no artificial cap, full story plays)
# ══════════════════════════════════════════════════════════════════════════════
def parse_srt(srt_path: str):
    """Return list of (start_sec, end_sec, text) from SRT file."""
    import re
    entries = []
    text = open(srt_path, encoding="utf-8").read()
    blocks = re.split(r"\n\n+", text.strip())
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        times = lines[1]
        m = re.match(
            r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)", times
        )
        if not m:
            continue
        def ts(*args):
            h, mi, s, ms = int(args[0]), int(args[1]), int(args[2]), int(args[3])
            return h * 3600 + mi * 60 + s + ms / 1000
        start = ts(*m.groups()[0:4])
        end   = ts(*m.groups()[4:8])
        word  = " ".join(lines[2:]).strip()
        entries.append((start, end, word))
    return entries


def compose_video(bg: str, audio: str, srt: str, duration: float, out: str):
    """Compose final video using drawtext (no subtitles filter — no path issues)."""
    entries = parse_srt(srt)

    # Build one drawtext filter per word, each enabled only during its time window
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

    drawtext_filters = []
    for start, end, word in entries:
        # Escape special chars for ffmpeg drawtext
        safe = (word
            .replace("\\", "\\\\")
            .replace("'",  "")          # drop apostrophes to avoid shell issues
            .replace(":",  "\\:")
            .replace("%",  "\\%")
        )
        dt = (
            f"drawtext=text=\'{safe}\':"
            f"fontfile=\'{font}\':"
            f"fontsize=90:"
            f"fontcolor=white:"
            f"bordercolor=black:borderw=4:"
            f"x=(w-text_w)/2:"          # horizontal center
            f"y=(h-text_h)/2:"          # vertical center
            f"enable=\'between(t,{start:.3f},{end:.3f})\'"
        )
        drawtext_filters.append(dt)

    # Chain: scale/crop -> each drawtext
    vf_parts = [
        f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=increase",
        f"crop={VIDEO_W}:{VIDEO_H}",
        "fps=30",
        "eq=brightness=-0.05:saturation=1.1",
    ] + drawtext_filters

    vf = ",".join(vf_parts)

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", bg,
        "-i", audio,
        "-vf", vf,
        "-map", "0:v", "-map", "1:a",
        "-t", str(duration + 0.3),
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
    print(f"  Done: {out}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 6 — Upload via rclone
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
    print("\nReddit Story Bot  " + datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
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

        print("\n[2/5] Text-to-speech (Microsoft Edge neural)…")
        text_to_speech(story["story"], audio, srt)

        print("\n[3/5] Picking background…")
        bg = pick_background()

        print("\n[4/5] Composing video…")
        dur = get_duration(audio)
        print(f"  Duration  : {dur:.1f}s")
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

    print(f"\nDone!\n  {story['title']}\n  {link}\n")


if __name__ == "__main__":
    main()
