#!/usr/bin/env python3
"""
Reddit Story Video Bot — Fully Automated
- Story      : Gemini 2.5 Flash
- Voice      : ElevenLabs (Adam) with word-level timestamps
- Video      : FFmpeg, one word centered, perfectly synced
- Storage    : Google Drive (rclone)
- YouTube    : Auto-upload as scheduled, goes public next day at peak time
               Title, description, hashtags all AI-generated
"""

import os, sys, json, random, subprocess, tempfile, re, base64, time
from pathlib import Path
from datetime import datetime, timedelta, timezone
import requests

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════
GEMINI_API_KEY     = os.environ["GEMINI_API_KEY"]
ELEVENLABS_API_KEY = os.environ["ELEVENLABS_API_KEY"]
RCLONE_CONFIG_B64  = os.environ["RCLONE_CONFIG_B64"]
YT_CLIENT_ID       = os.environ["YT_CLIENT_ID"]
YT_CLIENT_SECRET   = os.environ["YT_CLIENT_SECRET"]
YT_REFRESH_TOKEN   = os.environ["YT_REFRESH_TOKEN"]
GDRIVE_FOLDER      = os.getenv("GDRIVE_FOLDER", "RedditStoryBot")

VIDEO_W, VIDEO_H   = 1080, 1920
VOICE_ID           = "pNInz6obpgDQGcFmaJgB"   # Adam — dominant, firm
FONT               = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# YouTube publish time: next day at this hour UTC
# 8 PM EST = 00:00 UTC  |  8 PM PST = 03:00 UTC  |  8 PM GMT = 20:00 UTC
PUBLISH_HOUR_UTC   = int(os.getenv("PUBLISH_HOUR_UTC", "23"))  # 7 PM EST default

SUBREDDITS = [
    "AITA", "tifu", "relationship_advice", "TrueOffMyChest",
    "confession", "entitledparents", "ProRevenge", "pettyrevenge",
]
BACKGROUND_DIR = Path("backgrounds")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Generate story + YouTube metadata
# ══════════════════════════════════════════════════════════════════════════════
def generate_story() -> dict:
    sub = random.choice(SUBREDDITS)
    print(f"  Subreddit : r/{sub}")

    prompt = f"""Write a viral Reddit story for r/{sub} formatted for a YouTube Short.

Story rules:
- Start with a punchy hook (max 10 words) like "She stole from me. So I destroyed her career."
- Story body: 130 to 150 words total including the hook
- First-person, past tense, emotionally engaging
- Clear setup, conflict, satisfying resolution or twist
- No Edit sections, no usernames, no markdown

Also generate YouTube metadata:
- yt_title: Punchy YouTube title under 70 chars, no clickbait emojis, grabs attention
- yt_description: 3-4 sentence description that teases the story without spoiling it. End with "Like and subscribe for daily Reddit stories!"
- yt_tags: list of 10-15 relevant hashtag strings (without # symbol) e.g. ["reddit","AITA","storytime"]

Return JSON with keys: title, subreddit, story, yt_title, yt_description, yt_tags"""

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
                    "title":          {"type": "string"},
                    "subreddit":      {"type": "string"},
                    "story":          {"type": "string"},
                    "yt_title":       {"type": "string"},
                    "yt_description": {"type": "string"},
                    "yt_tags":        {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "subreddit", "story", "yt_title", "yt_description", "yt_tags"],
            },
        },
    }

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
    print(f"  Title    : {data['title']}")
    print(f"  YT Title : {data['yt_title']}")
    print(f"  Words    : {len(data['story'].split())}")
    print(f"  Tags     : {data['yt_tags'][:5]}…")
    return data


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — ElevenLabs TTS with word-level timestamps
# ══════════════════════════════════════════════════════════════════════════════
def text_to_speech(text: str, mp3_path: str) -> list:
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

    data       = resp.json()
    audio_bytes = base64.b64decode(data["audio_base64"])
    Path(mp3_path).write_bytes(audio_bytes)
    print(f"  Audio: {len(audio_bytes)//1024} KB")

    alignment = data.get("alignment", {})
    chars     = alignment.get("characters", [])
    starts    = alignment.get("character_start_times_seconds", [])
    ends      = alignment.get("character_end_times_seconds", [])

    if not chars:
        print("  WARNING: no alignment data")
        return []

    entries = []
    word_chars, word_starts, word_ends = [], [], []
    for ch, s, e in zip(chars, starts, ends):
        if ch in (" ", "\n", "\t"):
            if word_chars:
                entries.append((word_starts[0], word_ends[-1], "".join(word_chars)))
                word_chars, word_starts, word_ends = [], [], []
        else:
            word_chars.append(ch)
            word_starts.append(s)
            word_ends.append(e)
    if word_chars:
        entries.append((word_starts[0], word_ends[-1], "".join(word_chars)))

    print(f"  Words synced: {len(entries)}")
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
# ══════════════════════════════════════════════════════════════════════════════
def compose_video(bg: str, audio: str, entries: list, duration: float, out: str):
    word_files = []
    for i, (_, _, word) in enumerate(entries):
        wf = f"/tmp/w{i:04d}.txt"
        Path(wf).write_text(word, encoding="utf-8")
        word_files.append(wf)

    stmts = []
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

    Path("/tmp/fg.txt").write_text(";\n".join(stmts), encoding="utf-8")
    print(f"  Filtergraph: {len(stmts)} statements")

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", bg,
        "-i", audio,
        "-filter_complex_script", "/tmp/fg.txt",
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
# STEP 6 — Upload to Google Drive via rclone
# ══════════════════════════════════════════════════════════════════════════════
def upload_drive(local_path: str, filename: str) -> str:
    import tempfile as tf
    cfg      = base64.b64decode(RCLONE_CONFIG_B64)
    cfg_file = tf.NamedTemporaryFile(suffix=".conf", delete=False, mode="wb")
    cfg_file.write(cfg)
    cfg_file.close()

    dest = f"gdrive:{GDRIVE_FOLDER}/{filename}"
    r = subprocess.run(
        ["rclone", "--config", cfg_file.name, "copyto", local_path, dest],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print("rclone error:", r.stderr)
        return "(drive upload failed)"
    lr = subprocess.run(
        ["rclone", "--config", cfg_file.name, "link", dest],
        capture_output=True, text=True,
    )
    link = lr.stdout.strip() if lr.returncode == 0 else dest
    print(f"  Drive: {link}")
    return link


# ══════════════════════════════════════════════════════════════════════════════
# STEP 7 — Upload to YouTube (scheduled for next day peak time)
# ══════════════════════════════════════════════════════════════════════════════
def get_youtube_token() -> str:
    """Exchange refresh token for a fresh access token."""
    print(f"  Client ID  : {YT_CLIENT_ID[:12]}...")
    print(f"  Refresh tok: {YT_REFRESH_TOKEN[:12]}...")
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id":     YT_CLIENT_ID,
        "client_secret": YT_CLIENT_SECRET,
        "refresh_token": YT_REFRESH_TOKEN,
        "grant_type":    "refresh_token",
    })
    body = resp.json()
    if resp.status_code != 200:
        print(f"  Google error: {body}")
        resp.raise_for_status()
    token = body["access_token"]
    print("  YouTube token obtained")
    return token


def upload_youtube(video_path: str, story: dict) -> str:
    """
    Upload video to YouTube as private/scheduled.
    Publishes next day at PUBLISH_HOUR_UTC.
    Returns the YouTube video URL.
    """
    token = get_youtube_token()

    # Schedule: tomorrow at peak hour UTC
    now       = datetime.now(timezone.utc)
    publish_at = (now + timedelta(days=1)).replace(
        hour=PUBLISH_HOUR_UTC, minute=0, second=0, microsecond=0
    )
    publish_str = publish_at.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    print(f"  Scheduled for: {publish_str}")

    # Build description with hashtags at the bottom
    hashtags    = " ".join(f"#{t}" for t in story["yt_tags"])
    description = (
        story["yt_description"]
        + f"\n\n{hashtags}"
        + "\n\n#shorts #reddit #redditstories #storytime"
    )

    # Metadata part
    metadata = {
        "snippet": {
            "title":       story["yt_title"],
            "description": description,
            "tags":        story["yt_tags"] + ["shorts", "reddit", "redditstories", "storytime"],
            "categoryId":  "24",   # Entertainment
        },
        "status": {
            "privacyStatus":       "private",   # stays private until publish_at
            "publishAt":           publish_str,
            "selfDeclaredMadeForKids": False,
            "madeForKids":         False,
        },
    }

    # Resumable upload (handles large files reliably)
    headers = {
        "Authorization":  f"Bearer {token}",
        "Content-Type":   "application/json",
        "X-Upload-Content-Type": "video/mp4",
        "X-Upload-Content-Length": str(Path(video_path).stat().st_size),
    }
    init_resp = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos"
        "?uploadType=resumable&part=snippet,status",
        headers=headers,
        json=metadata,
    )
    init_resp.raise_for_status()
    upload_url = init_resp.headers["Location"]

    # Upload video bytes
    with open(video_path, "rb") as f:
        video_bytes = f.read()

    upload_resp = requests.put(
        upload_url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "video/mp4",
        },
        data=video_bytes,
        timeout=300,
    )
    upload_resp.raise_for_status()

    video_id  = upload_resp.json()["id"]
    yt_url    = f"https://youtube.com/shorts/{video_id}"
    print(f"  YouTube: {yt_url}")
    print(f"  Goes public: {publish_str}")
    return yt_url


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

        print("\n[1/6] Generating story + YouTube metadata…")
        story = generate_story()

        print("\n[2/6] Text-to-speech (ElevenLabs Adam)…")
        entries = text_to_speech(story["story"], audio)

        print("\n[3/6] Picking background…")
        bg = pick_background()

        print("\n[4/6] Composing video…")
        dur = get_duration(audio)
        print(f"  Duration: {dur:.1f}s")
        compose_video(bg, audio, entries, dur, video_path)

        print("\n[5/6] Uploading to Google Drive…")
        drive_link = upload_drive(video_path, video_name)

        print("\n[6/6] Uploading to YouTube (scheduled)…")
        yt_link = upload_youtube(video_path, story)

    summary = os.getenv("GITHUB_STEP_SUMMARY", "")
    if summary:
        with open(summary, "a") as f:
            f.write(f"## Reddit Story Bot\n")
            f.write(f"**Title:** {story['yt_title']}\n\n")
            f.write(f"**Sub:** r/{story['subreddit']}\n\n")
            f.write(f"**YouTube:** {yt_link}\n\n")
            f.write(f"**Drive:** {drive_link}\n\n")
            f.write(f"**Publishes:** next day at {PUBLISH_HOUR_UTC}:00 UTC\n")

    print(f"""
{"="*48}
Done!
  Story   : {story['title']}
  YT      : {yt_link}
  Drive   : {drive_link}
  Publish : tomorrow {PUBLISH_HOUR_UTC}:00 UTC
{"="*48}
""")


if __name__ == "__main__":
    main()
