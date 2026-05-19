#!/usr/bin/env python3
"""
Reddit Story Video Bot
- Story  : Gemini 2.5 Flash (free)
- Voice  : ElevenLabs TTS with character-level timestamps -> word sync
- Video  : FFmpeg drawtext per word, dead center, perfectly synced
- Upload : rclone -> Google Drive
- Host   : GitHub Actions daily cron
"""

import os, sys, json, random, subprocess, tempfile, re, base64, time
from pathlib import Path
from datetime import datetime
import requests

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════
GEMINI_API_KEY    = os.environ["GEMINI_API_KEY"]
ELEVENLABS_API_KEY= os.environ["ELEVENLABS_API_KEY"]
RCLONE_CONFIG_B64 = os.environ["RCLONE_CONFIG_B64"]
GDRIVE_FOLDER     = os.getenv("GDRIVE_FOLDER", "RedditStoryBot")

VIDEO_W, VIDEO_H  = 1080, 1920
VOICE_ID          = "pNInz6obpgDQGcFmaJgB"   # Adam — dominant, firm
FONT              = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

SUBREDDITS = [
    "AITA", "tifu", "relationship_advice", "TrueOffMyChest",
    "confession", "entitledparents", "ProRevenge", "pettyrevenge",
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
- Story body: 120 to 150 words
- First-person, past tense, emotionally engaging
- Clear setup, conflict, resolution or twist
- No Edit sections, no usernames, no markdown
- Start the story with a short punchy hook sentence (max 10 words) that grabs attention immediately, like "He cheated, so I ruined his life." or "My boss stole my work. Here's what I did." — dramatic, direct, no fluff
- No poncuation like commas, dots etc
- Title: Reddit-style question or punchy statement"""

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.85,
            "maxOutputTokens": 4000,
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

    # Retry with fallback models on 503
    for model in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
        attempt_url = url.replace("gemini-2.5-flash", model)
        try:
            resp = requests.post(attempt_url, json=payload, timeout=60)
            if resp.status_code == 503:
                print(f"  503 on {model}, retrying…")
                time.sleep(5)
                continue
            resp.raise_for_status()
            print(f"  Model: {model}")
            break
        except Exception as e:
            print(f"  {model} failed: {e}")
            time.sleep(5)
    else:
        raise RuntimeError("All Gemini attempts failed")

    data = json.loads(resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip())
    print(f"  Title : {data['title']}")
    print(f"  Words : {len(data['story'].split())}")
    return data


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — ElevenLabs TTS with timestamps
#   Uses /v1/text-to-speech/{voice_id}/with-timestamps
#   Returns base64 audio + character_start_times_seconds array
#   We group characters into words to get word-level start/end times
# ══════════════════════════════════════════════════════════════════════════════
def text_to_speech(text: str, mp3_path: str) -> list:
    """
    Returns list of (start_sec, end_sec, word) tuples — one per word.
    """
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}/with-timestamps"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.35,
            "similarity_boost": 0.85,
            "style": 0.4,
            "use_speaker_boost": True,
        },
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    if resp.status_code != 200:
        print("ElevenLabs error:", resp.status_code, resp.text[:500])
        resp.raise_for_status()

    data = resp.json()

    # Save audio
    audio_bytes = base64.b64decode(data["audio_base64"])
    Path(mp3_path).write_bytes(audio_bytes)
    print(f"  Audio: {len(audio_bytes)//1024} KB")

    # Extract alignment
    alignment = data.get("alignment", {})
    chars      = alignment.get("characters", [])
    starts     = alignment.get("character_start_times_seconds", [])
    ends       = alignment.get("character_end_times_seconds", [])

    if not chars:
        print("  WARNING: no alignment data returned")
        return []

    # Group characters into words
    entries = []
    word_chars  = []
    word_starts = []
    word_ends   = []

    for ch, s, e in zip(chars, starts, ends):
        if ch in (" ", "\n", "\t"):
            # Flush current word
            if word_chars:
                word = "".join(word_chars)
                entries.append((word_starts[0], word_ends[-1], word))
                word_chars, word_starts, word_ends = [], [], []
        else:
            word_chars.append(ch)
            word_starts.append(s)
            word_ends.append(e)

    # Flush last word
    if word_chars:
        word = "".join(word_chars)
        entries.append((word_starts[0], word_ends[-1], word))

    print(f"  Words synced: {len(entries)}")
    if entries:
        print(f"  First: {entries[0]}  Last: {entries[-1]}")
    return entries


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Pick background
# ══════════════════════════════════════════════════════════════════════════════
def pick_background() -> str:
    videos = list(BACKGROUND_DIR.glob("*.mp4")) + list(BACKGROUND_DIR.glob("*.mov"))
    if not videos:
        raise FileNotFoundError(f"No videos in {BACKGROUND_DIR}/")
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
#   One word at a time, dead center.
#   Each word written to its own file (no escaping issues).
#   filter_complex_script with semicolons between chains.
# ══════════════════════════════════════════════════════════════════════════════
def compose_video(bg: str, audio: str, entries: list, duration: float, out: str):
    # Write each word to a temp file
    word_files = []
    for i, (_, _, word) in enumerate(entries):
        wf = f"/tmp/w{i:04d}.txt"
        Path(wf).write_text(word, encoding="utf-8")
        word_files.append(wf)

    stmts = []

    # Base: scale/crop/eq -> [v0]
    stmts.append(
        "[0:v]"
        f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=increase,"
        f"crop={VIDEO_W}:{VIDEO_H},"
        "fps=30,"
        "eq=brightness=-0.05:saturation=1.1"
        "[v0]"
    )

    if entries:
        for i, (start, end, _) in enumerate(entries):
            src = f"[v{i}]"
            dst = f"[v{i+1}]" if i < len(entries)-1 else "[out]"
            # \, escapes commas inside between() in filter_complex_script files
            stmts.append(
                f"{src}drawtext="
                f"textfile={word_files[i]}:"
                f"fontfile={FONT}:"
                f"fontsize=90:"
                f"fontcolor=white:"
                f"bordercolor=black:borderw=5:"
                f"x=(w-text_w)/2:"
                f"y=(h-text_h)/2:"
                r"enable=between(t\,"
                + f"{start:.3f}"
                + r"\,"
                + f"{end:.3f})"
                + dst
            )
    else:
        stmts.append("[v0]copy[out]")

    sep     = ";\n"
    fg_text = sep.join(stmts)
    fg_path = "/tmp/fg.txt"
    Path(fg_path).write_text(fg_text, encoding="utf-8")
    print(f"  Filtergraph: {len(stmts)} statements, {len(entries)} words")

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
        print("FFmpeg error:\n", r.stderr[-3000:])
        raise RuntimeError("FFmpeg failed")
    print(f"  Done: {out}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 6 — Upload via rclone
# ══════════════════════════════════════════════════════════════════════════════
def upload(local_path: str, filename: str) -> str:
    import tempfile as tf

    cfg      = base64.b64decode(RCLONE_CONFIG_B64)
    cfg_file = tf.NamedTemporaryFile(suffix=".conf", delete=False, mode="wb")
    cfg_file.write(cfg)
    cfg_file.close()

    dest = f"gdrive:{GDRIVE_FOLDER}/{filename}"
    print(f"  Uploading → {dest}")
    r = subprocess.run(
        ["rclone", "--config", cfg_file.name, "copyto", local_path, dest],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print("rclone error:", r.stderr)
        return "(upload failed)"

    lr   = subprocess.run(
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

        print("\n[1/5] Generating story…")
        story = generate_story()

        print("\n[2/5] Text-to-speech (ElevenLabs)…")
        entries = text_to_speech(story["story"], audio)

        print("\n[3/5] Picking background…")
        bg = pick_background()

        print("\n[4/5] Composing video…")
        dur = get_duration(audio)
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

    print(f"\nDone!\n  {story['title']}\n  {link}\n")


if __name__ == "__main__":
    main()
