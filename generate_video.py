#!/usr/bin/env python3
"""
Reddit Story Video Bot
– Story  : Gemini 2.5 Flash (free API key, no billing required)
– Voice  : gTTS (Google TTS, totally free, no key)
– Video  : FFmpeg (installed on GitHub Actions runner)
– Upload : rclone → Google Drive (free 15 GB)
– Host   : GitHub Actions daily cron (free for public repos)
"""

import os, sys, json, random, re, subprocess, tempfile
from pathlib import Path
from datetime import datetime

# ── dependencies (installed by workflow) ──────────────────────────────────────
import requests
from gtts import gTTS

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG  (all values come from GitHub Actions Secrets — nothing hardcoded)
# ══════════════════════════════════════════════════════════════════════════════
GEMINI_API_KEY   = os.environ["GEMINI_API_KEY"]         # Secret: GEMINI_API_KEY
RCLONE_CONFIG_B64= os.environ["RCLONE_CONFIG_B64"]      # Secret: RCLONE_CONFIG_B64
GDRIVE_FOLDER    = os.getenv("GDRIVE_FOLDER", "RedditStoryBot")

VIDEO_W, VIDEO_H = 1080, 1920   # 9:16 vertical (Shorts / TikTok)
MAX_SECONDS      = 58           # YouTube Shorts max is 60 s
WORDS_PER_SUB    = 5            # words shown per subtitle card
TTS_TLD          = "com"        # "com"=US  "co.uk"=British  "com.au"=Australian

SUBREDDITS = [
    "AITA", "tifu", "relationship_advice",
    "TrueOffMyChest", "confession",
    "entitledparents", "ProRevenge", "pettyrevenge",
]

BACKGROUND_DIR = Path("backgrounds")   # folder checked into the repo


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Generate story with Gemini 2.5 Flash (free tier)
# ══════════════════════════════════════════════════════════════════════════════
def generate_story() -> dict:
    sub = random.choice(SUBREDDITS)
    print(f"  Subreddit : r/{sub}")

    prompt = f"""Write a Reddit story for r/{sub}.

Requirements:
- Exactly 210 to 250 words
- First-person, past tense
- Emotionally engaging, realistic, relatable
- Clear setup, conflict, and satisfying resolution or twist
- Do NOT include a title inside the story body
- Do NOT include "Edit:" sections, usernames, or markdown

Return ONLY a valid JSON object with no markdown fences:
{{"title":"Reddit-style title (question or statement)","subreddit":"{sub}","story":"Full story body…"}}"""

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.9,
            "maxOutputTokens": 800,
        },
    }
    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()

    raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

    # Strip accidental markdown fences
    raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\n?```$", "", raw, flags=re.MULTILINE)

    # Extract JSON even if the model added preamble text
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"Gemini didn't return valid JSON:\n{raw[:400]}")

    data = json.loads(match.group())
    print(f"  Title     : {data['title']}")
    print(f"  Words     : {len(data['story'].split())}")
    return data


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Text-to-speech with gTTS (free, no key)
# ══════════════════════════════════════════════════════════════════════════════
def text_to_speech(text: str, out_mp3: str):
    gTTS(text=text, lang="en", tld=TTS_TLD, slow=False).save(out_mp3)
    print(f"  ✓ Audio saved")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Pick background video from repo folder
# ══════════════════════════════════════════════════════════════════════════════
def pick_background() -> str:
    videos = list(BACKGROUND_DIR.glob("*.mp4")) + list(BACKGROUND_DIR.glob("*.mov"))
    if not videos:
        raise FileNotFoundError(
            f"No .mp4 files found in {BACKGROUND_DIR}/\n"
            "Add royalty-free videos to that folder and commit them to your repo.\n"
            "Free sources: pexels.com/videos  •  pixabay.com/videos"
        )
    choice = random.choice(videos)
    print(f"  ✓ Background: {choice.name}")
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
# STEP 5 — Build SRT subtitles
# ══════════════════════════════════════════════════════════════════════════════
def build_srt(text: str, duration: float, srt_path: str):
    words = text.split()
    chunks = [words[i:i+WORDS_PER_SUB] for i in range(0, len(words), WORDS_PER_SUB)]
    secs_per_word = duration / max(len(words), 1)

    lines, t = [], 0.0
    for idx, chunk in enumerate(chunks, 1):
        end = t + secs_per_word * len(chunk)
        lines += [str(idx), f"{_ts(t)} --> {_ts(end)}", " ".join(chunk), ""]
        t = end

    Path(srt_path).write_text("\n".join(lines))
    print(f"  ✓ Subtitles built ({len(chunks)} cards)")


def _ts(s: float) -> str:
    h, m = int(s // 3600), int((s % 3600) // 60)
    return f"{h:02}:{m:02}:{int(s%60):02},{int((s%1)*1000):03}"


# ══════════════════════════════════════════════════════════════════════════════
# STEP 6 — Compose video with FFmpeg
# ══════════════════════════════════════════════════════════════════════════════
def compose_video(bg: str, audio: str, srt: str,
                  title: str, sub: str, duration: float, out: str):

    def esc(t):
        return t.replace("'", "\u2019").replace("\\", "/").replace(":", "\\:")

    # DejaVu ships on Ubuntu (GitHub Actions runner) by default
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    if not Path(font).exists():
        font = ""   # fallback to FFmpeg built-in

    font_arg = f":fontfile='{font}'" if font else ""
    srt_esc  = srt.replace("\\", "/").replace(":", "\\:")

    fg = (
        f"[0:v]scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=increase,"
        f"crop={VIDEO_W}:{VIDEO_H},fps=30,"
        f"eq=brightness=-0.07:saturation=1.1[bg];"

        # Dark gradient band at top for title readability
        f"[bg]drawbox=x=0:y=0:w={VIDEO_W}:h=310:color=black@0.6:t=fill[bg2];"

        # Subreddit pill
        f"[bg2]drawbox=x=40:y=48:w=270:h=64:color=0xFF4500@0.92:t=fill[bg3];"
        f"[bg3]drawtext=text='{esc(f'r/{sub}')}':fontcolor=white:fontsize=34"
        f"{font_arg}:x=58:y=66[bg4];"

        # Story title
        f"[bg4]drawtext=text='{esc(title[:58])}':fontcolor=white:fontsize=46"
        f"{font_arg}:x=(w-text_w)/2:y=135:bordercolor=black:borderw=3[bg5];"

        # Burnt-in captions at bottom
        f"[bg5]subtitles='{srt_esc}':"
        f"force_style='FontSize=46,PrimaryColour=&H00FFFFFF,"
        f"OutlineColour=&H00000000,BackColour=&H80000000,"
        f"Outline=3,Shadow=1,Alignment=2,MarginV=190'"
        f"[out]"
    )

    clip_dur = min(duration + 0.5, MAX_SECONDS)
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", bg,
        "-i", audio,
        "-filter_complex", fg,
        "-map", "[out]", "-map", "1:a",
        "-t", str(clip_dur),
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", "-pix_fmt", "yuv420p",
        out,
    ]
    print("  ⚙ Rendering video…")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("FFmpeg stderr:\n", r.stderr[-3000:])
        raise RuntimeError("FFmpeg failed — see above.")
    print(f"  ✓ Video rendered: {out}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 7 — Upload via rclone (config injected from secret)
# ══════════════════════════════════════════════════════════════════════════════
def upload(local_path: str, filename: str) -> str:
    import base64, tempfile as tf

    # Write rclone config from base64-encoded secret
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

    # Get shareable link
    lr = subprocess.run(
        ["rclone", "--config", cfg_file.name, "link", dest],
        capture_output=True, text=True,
    )
    link = lr.stdout.strip() if lr.returncode == 0 else dest
    print(f"  ✓ Uploaded: {link}")
    return link


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    print("\n🎬 Reddit Story Bot  •  " + datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
    print("─" * 48)

    stamp      = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    video_name = f"reddit_{stamp}.mp4"
    out_dir    = Path("output")
    out_dir.mkdir(exist_ok=True)
    video_path = str(out_dir / video_name)

    with tempfile.TemporaryDirectory() as tmp:
        audio = os.path.join(tmp, "audio.mp3")
        srt   = os.path.join(tmp, "subs.srt")

        print("\n📝 [1/5] Generating story (Gemini 2.5 Flash)…")
        story = generate_story()

        print("\n🔊 [2/5] Text-to-speech (gTTS)…")
        text_to_speech(story["story"], audio)

        print("\n🎥 [3/5] Picking background…")
        bg = pick_background()

        print("\n🎞  [4/5] Composing video (FFmpeg)…")
        dur = get_duration(audio)
        build_srt(story["story"], dur, srt)
        compose_video(bg, audio, srt, story["title"], story["subreddit"], dur, video_path)

        print("\n☁  [5/5] Uploading to Google Drive…")
        link = upload(video_path, video_name)

    # Write job summary (visible in GitHub Actions run page)
    summary = os.getenv("GITHUB_STEP_SUMMARY", "")
    if summary:
        with open(summary, "a") as f:
            f.write(f"## ✅ Reddit Story Bot\n")
            f.write(f"**Title:** {story['title']}\n\n")
            f.write(f"**Subreddit:** r/{story['subreddit']}\n\n")
            f.write(f"**Drive link:** {link}\n\n")
            f.write(f"**Video file:** `{video_name}`\n")

    print(f"""
{"═"*48}
✅  Done!
   Title  : {story['title']}
   Sub    : r/{story['subreddit']}
   Video  : {video_path}
   Drive  : {link}
{"═"*48}
""")


if __name__ == "__main__":
    main()
