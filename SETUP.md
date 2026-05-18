# 🎬 Reddit Story Bot — Cloud Setup Guide
### Everything runs on GitHub. Nothing installs on your PC.

---

## What You Need (all free)

| Thing | Where to get it | Time |
|-------|----------------|------|
| GitHub account | github.com | 2 min |
| Gemini API key | aistudio.google.com | 2 min |
| Google Drive folder | Already have it | 1 min |
| rclone config (encoded) | rclone.org | 5 min |
| Background video(s) | pexels.com/videos | 5 min |

Total setup time: ~15 minutes, then it runs forever on autopilot.

---

## Step 1 — Create the GitHub Repository

1. Go to **github.com** → click **"New"** (top left, green button)
2. Name it something like `reddit-story-bot`
3. Set it to **Public** (required for unlimited free Actions minutes)
4. Click **Create repository**

Now upload all the files from this zip:
- `generate_video.py`
- `requirements.txt`
- `.github/workflows/daily_video.yml`
- `backgrounds/README.md`

To upload: on your new repo page, click **"uploading an existing file"** and drag them in.

> For `.github/workflows/daily_video.yml` — GitHub needs you to create the folder path.
> Click **"Create new file"**, type `.github/workflows/daily_video.yml` as the filename,
> paste the contents of that file, and click **Commit changes**.

---

## Step 2 — Get Your Free Gemini API Key

1. Go to **https://aistudio.google.com/**
2. Sign in with your Google account
3. Click **"Get API key"** → **"Create API key"**
4. Copy the key (looks like `AIzaSy...`)

This is the free tier — **no billing, no credit card**. You get 250 requests/day on
Gemini 2.5 Flash, which is more than enough for 1 video per day.

---

## Step 3 — Set Up Google Drive Storage with rclone

rclone is a free tool that connects to Google Drive. You need to run it **once**
on any computer (or use the web option below) to generate a config file.

### Option A — Use a friend's computer or any PC/Mac just once:

1. Download rclone from **https://rclone.org/downloads/** (no install needed — it's one file)
2. Open a terminal/command prompt in that folder and run:
   ```
   ./rclone config        (Mac/Linux)
   rclone.exe config      (Windows)
   ```
3. Follow these prompts:
   - `n` → New remote
   - Name: `gdrive`
   - Storage type: type `drive` and press Enter
   - Client ID: just press Enter (leave blank)
   - Client Secret: just press Enter
   - Scope: type `1` (full access)
   - Root folder ID: press Enter
   - Service Account: press Enter
   - Advanced config: `n`
   - Auto config: `y` → browser opens → sign into Google → Allow
   - Team drive: `n`
   - Confirm: `y`
4. Now encode the config to paste into GitHub:
   ```bash
   # Mac/Linux:
   base64 ~/.config/rclone/rclone.conf

   # Windows (PowerShell):
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("$env:APPDATA\rclone\rclone.conf"))
   ```
5. Copy the long base64 string — you'll paste it in Step 4.

### Option B — Google Colab (no computer at all):
1. Go to **colab.research.google.com** → New notebook
2. Run this cell:
   ```python
   !pip install rclone
   !rclone config
   ```
3. Follow the same prompts as above (use `n` for auto config, paste the auth URL
   into your browser, copy the code back)
4. Then run:
   ```python
   import base64
   with open("/root/.config/rclone/rclone.conf", "rb") as f:
       print(base64.b64encode(f.read()).decode())
   ```
5. Copy that output.

---

## Step 4 — Add Secrets to GitHub

Your API key and rclone config go into GitHub Secrets (encrypted, never visible).

1. Go to your repo on GitHub
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **"New repository secret"** and add these two:

| Secret Name | Value |
|-------------|-------|
| `GEMINI_API_KEY` | Your key from Step 2 (starts with `AIzaSy...`) |
| `RCLONE_CONFIG_B64` | The base64 string from Step 3 |

---

## Step 5 — Add Background Videos

1. In your repo, click on the `backgrounds/` folder
2. Click **"Add file"** → **"Upload files"**
3. Drag in 2–4 `.mp4` files (keep each under 100 MB)

**Free sources:**
- **pexels.com/videos** → search "minecraft" / "subway surfers" / "rain" / "cooking"
- **pixabay.com/videos** → similar selection

The bot picks one randomly each day. More variety = more unique-looking videos.

> **File too big?** Compress it online at **https://www.freeconvert.com/video-compressor**
> or use FFmpeg if you have it: `ffmpeg -i input.mp4 -crf 28 small.mp4`

---

## Step 6 — Create the Google Drive Folder

1. Go to **drive.google.com**
2. Create a new folder called `RedditStoryBot`
3. That's it — rclone will upload there automatically

---

## Step 7 — Test Run (Manual Trigger)

1. Go to your repo → click **Actions** tab
2. Click **"Reddit Story Bot — Daily Video"** on the left
3. Click **"Run workflow"** → **"Run workflow"** (green button)
4. Watch it run! Each step shows in real time (~3-4 minutes total)
5. When done, click the run → scroll down to **Artifacts** → download your video
6. Also check your Google Drive `RedditStoryBot` folder — it should be there too

---

## Step 8 — It Now Runs Every Day Automatically

The workflow is set to run at **10:00 AM UTC** every day.
You don't have to do anything — GitHub runs it, makes the video, uploads to Drive.

To change the time, edit `.github/workflows/daily_video.yml` and change:
```yaml
- cron: '0 10 * * *'
```
Use **crontab.guru** to build any schedule you want.

---

## Customizing the Bot

All customization is in `generate_video.py` — edit it directly on GitHub:

| What to change | Where in the file |
|---------------|------------------|
| Subreddits to pick from | `SUBREDDITS` list |
| TTS voice accent | `TTS_TLD = "co.uk"` for British, `"com.au"` for Australian |
| Words per subtitle card | `WORDS_PER_SUB = 5` |
| Max video length | `MAX_SECONDS = 58` |
| Upload folder name | `GDRIVE_FOLDER` env var in the workflow YAML |

---

## Reading Results

After each run, click the workflow run in the **Actions** tab.
You'll see a **Summary** at the top with:
- Story title
- Subreddit
- Google Drive link to the video

The video is also saved as an **Artifact** for 7 days (downloadable directly from GitHub).

---

## Troubleshooting

**"No backgrounds found"** — Make sure you uploaded `.mp4` files to `backgrounds/`

**Gemini API error 429** — You hit the free rate limit (rare at 1/day). Wait and retry.

**rclone upload fails** — Re-run Steps 3–4 to regenerate and re-paste the config.
The Google OAuth token in the config expires after a few months — redo Step 3 when that happens.

**Workflow not running on schedule** — GitHub disables scheduled workflows after
60 days of repo inactivity. Make any small commit (like editing a comment) to re-enable.

**Video renders but looks wrong** — Check the Actions log for FFmpeg errors.
Usually a background video encoding issue — re-download and re-upload the background.
