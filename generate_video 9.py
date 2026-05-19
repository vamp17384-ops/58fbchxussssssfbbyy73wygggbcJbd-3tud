#!/usr/bin/env python3
"""
Reddit Story Video Bot
- Story  : Gemini 2.5 Flash (free)
- Voice  : edge-tts CLI — Microsoft neural, free, very human
- Video  : FFmpeg drawtext, one word centered, word-synced
- Upload : rclone -> Google Drive
- Host   : GitHub Actions daily cron
"""

import os, sys, json, random, subprocess, tempfile, re
from pathlib import Path
from datetime import datetime
import requests

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════
GEMINI_API_KEY    = os.environ["GEMINI_API_KEY"]
RCLONE_CONFIG_B64 = os.environ["RCLONE_CONFIG_B64"]
GDRIVE_FOLDER     = os.getenv("GDRIVE_FOLDER", "RedditStoryBot")

VIDEO_W, VIDEO_H  = 1080, 1920

# Microsoft neural voices (free, no key):
# en-US-GuyNeural / en-US-JennyNeural / en-US-AriaNeural
# en-GB-RyanNeural / en-AU-NatashaNeural
TTS_VOICE = "en-US-GuyNeural"
TTS_RATE  = "+15%"   # +0% normal, +15% slightly faster, +25% faster

SUBREDDITS = [
    "AITA", "tifu", "relationship_advice",
    "TrueOffMyChest", "confession",
    "entitledparents", "ProRevenge", "pettyrevenge",
]

BACKGROUND_DIR = Path("backgrounds")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Generate story
# ══════════════════════════════════════════════════════════════════════════════
def generate_story() -> dict:
    sub = random.choice(SUBREDDITS)
    print(f"  Subreddit : r/{sub}")

    prompt = f"""Write a Reddit story for r/{sub}.
Rules:
- Story body: 120 to 150 words
- First-person, past tense, emotionally engaging
- Clear setup, conflict, and resolution or twist
- No Edit sections, no usernames, no markdown
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
# STEP 2 — TTS via edge-tts CLI (most reliable way to get word-timed SRT)
# ══════════════════════════════════════════════════════════════════════════════
def text_to_speech(text: str, mp3_path: str, srt_path: str):
    """Call edge-tts CLI directly — avoids all Python API version issues."""
    cmd = [
        "edge-tts",
        "--voice", TTS_VOICE,
        "--rate", TTS_RATE,
        "--text", text,
        "--write-media", mp3_path,
        "--write-subtitles", srt_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("edge-tts error:", r.stderr)
        raise RuntimeError("edge-tts failed")
    print(f"  Voice: {TTS_VOICE} @ {TTS_RATE}")
    print(f"  SRT size: {Path(srt_path).stat().st_size} bytes")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Parse SRT (edge-tts writes VTT format with --> timecodes)
# ══════════════════════════════════════════════════════════════════════════════
def parse_srt(srt_path: str):
    raw = Path(srt_path).read_text(encoding="utf-8")
    # Normalise line endings
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    print(f"  SRT preview: {repr(text[:300])}")

    entries = []
    # Match timecode lines — both SRT (,) and VTT (.) decimal separators
    pattern = re.compile(
        r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)"
    )
    blocks = re.split(r"\n\n+", text.strip())
    for block in blocks:
        lines = block.strip().splitlines()
        for i, line in enumerate(lines):
            m = pattern.match(line.strip())
            if m:
                def ts(a, b, c, d):
                    return int(a)*3600 + int(b)*60 + int(c) + int(d)/1000
                start = ts(*m.groups()[0:4])
                end   = ts(*m.groups()[4:8])
                # text is everything after the timecode line
                word = " ".join(lines[i+1:]).strip()
                # Strip VTT tags like <c> </c>
                word = re.sub(r"<[^>]+>", "", word).strip()
                if word:
                    entries.append((start, end, word))
                break

    print(f"  Parsed {len(entries)} subtitle entries")
    return entries


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — Pick background
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
# STEP 5 — Audio duration
# ══════════════════════════════════════════════════════════════════════════════
def get_duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(r.stdout.strip())


# ══════════════════════════════════════════════════════════════════════════════
# STEP 6 — Compose video
#   Uses -filter_complex_script + textfile= to avoid ALL escaping issues.
#   Each word written to its own file; drawtext reads it directly.
#   Alignment: dead center (x=(w-text_w)/2, y=(h-text_h)/2)
# ══════════════════════════════════════════════════════════════════════════════
def compose_video(bg: str, audio: str, entries: list, duration: float, out: str):
    # Write each word to its own temp file (avoids escaping entirely)
    word_files = []
    for i, (_, _, word) in enumerate(entries):
        wf = f"/tmp/w{i:04d}.txt"
        Path(wf).write_text(word, encoding="utf-8")
        word_files.append(wf)

    # Build filtergraph as a script file
    # Scale/crop base
    lines = [
        f"[0:v]scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=increase,"
        f"crop={VIDEO_W}:{VIDEO_H},fps=30,"
        f"eq=brightness=-0.05:saturation=1.1"
        f"[v0]"
    ]

    if entries:
        prev = "[v0]"
        for i, (start, end, _) in enumerate(entries):
            nxt = f"[v{i+1}]" if i < len(entries) - 1 else "[out]"
            lines.append(
                f"{prev}drawtext="
                f"textfile={word_files[i]}:"
                f"fontfile={FONT}:"
                f"fontsize=90:"
                f"fontcolor=white:"
                f"bordercolor=black:borderw=5:"
                f"x=(w-text_w)/2:"
                f"y=(h-text_h)/2:"
                f"enable=between(t,{start:.3f},{end:.3f})"
                f"{nxt}"
            )
            prev = nxt
    else:
        # No subtitles — just rename label
        lines.append("[v0]copy[out]")

    fg_path = "/tmp/fg.txt"
    Path(fg_path).write_text("\n".join(lines))
    print(f"  Filtergraph: {len(lines)} lines, {len(entries)} words")

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", bg,
        "-i", audio,
        "-filter_complex_script", fg_path,
        "-map", "[out]", "-map", "1:a",
        "-t", str(duration + 0.3),
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", "-pix_fmt", "yuv420p",
        out,
    ]
    print("  Rendering…")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("FFmpeg error:\n", r.stderr[-2000:])
        raise RuntimeError("FFmpeg failed")
    print(f"  Done: {out}")


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

        print("\n[2/5] Text-to-speech…")
        text_to_speech(story["story"], audio, srt)

        print("\n[3/5] Picking background…")
        bg = pick_background()

        print("\n[4/5] Composing video…")
        dur     = get_duration(audio)
        entries = parse_srt(srt)
        print(f"  Duration: {dur:.1f}s")
        compose_video(bg, audio, entries, dur, video_path)

        print("\n[5/5] Uploading…")
        link = upload(video_path, video_name)

    summary = os.getenv("GITHUB_STEP_SUMMARY", "")
    if summary:
        with open(summary, "a") as f:
            f.write(f"## Reddit Story Bot\n")
            f.write(f"**Title:** {story['title']}\n\n")
            f.write(f"**Sub:** r/{story['subreddit']}\n\n")
            f.write(f"**Drive:** {link}\n\n")
            f.write(f"**File:** `{video_name}`\n")

    print(f"\nDone! {story['title']}\n{link}\n")


if __name__ == "__main__":
    main()
