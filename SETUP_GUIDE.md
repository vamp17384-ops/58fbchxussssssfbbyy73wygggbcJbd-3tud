# 🎬 Reddit Story Bot — Setup Guide
### You already have the code (forked). Just need your API keys. Takes 20 minutes.

Every day at 6 AM Montreal time the bot makes a Reddit story video and posts it
to your YouTube channel automatically at 7 PM the same day.

---

## STEP 1 — Get your free Gemini API key
*The AI that writes the stories*

1. Go to **aistudio.google.com**
2. Sign in with your Google account
3. Click **Get API key** → **Create API key**
4. Copy it — looks like `AIzaSyXXXXXXXXXXXXXXXX`
5. Save it in your Notes app for now

---

## STEP 2 — Get your ElevenLabs API key
*The voice that reads the stories — sounds very human*

1. Go to **elevenlabs.io** → create a free account
2. Click your profile picture (top right) → **Profile**
3. Copy your **API Key**
4. Save it in Notes

Free tier = about 60 videos per month.
Want more? $5/month Starter plan = ~200 videos/month.

---

## STEP 3 — Set up Google Drive backup (optional but recommended)
*Saves a copy of every video to your Drive just in case*

Do this in **Google Colab** — no installs needed, just a browser.

1. Go to **colab.research.google.com** → click **New notebook**

2. Paste into Cell 1 and press ▶:
```python
!curl https://rclone.org/install.sh | sudo bash
```

3. Paste into Cell 2 and press ▶:
```python
!rclone config
```
When it asks questions answer exactly like this:
- `n` → Enter (new remote)
- Name: `gdrive` → Enter
- Storage type: `drive` → Enter
- Client ID: just Enter (blank)
- Client Secret: just Enter (blank)
- Scope: `1` → Enter
- Root folder ID: just Enter (blank)
- Service Account: just Enter (blank)
- Advanced config: `n` → Enter
- Auto config: `n` → Enter
- Copy the long URL it shows → open it in your browser
- Sign into Google → Allow
- Copy the code → paste it back into Colab → Enter
- Team drive: `n` → Enter
- Confirm: `y` → Enter

4. Paste into Cell 3 and press ▶:
```python
import base64
with open("/root/.config/rclone/rclone.conf", "rb") as f:
    print(base64.b64encode(f.read()).decode())
```
Copy the long string it prints — this is your `RCLONE_CONFIG_B64`

5. Go to **drive.google.com** → create a folder called `RedditStoryBot`

---

## STEP 4 — Connect your YouTube channel
*So the bot can post directly to your channel*

### Part A — Enable YouTube API

1. Go to **console.cloud.google.com**
2. Top left → **Select a project** → **New Project** → name it `RedditBot` → **Create**
3. Search bar at top → type `YouTube Data API v3` → click it → click **Enable**

### Part B — Create OAuth credentials

1. Left menu → **APIs & Services** → **Credentials**
2. Click **Configure Consent Screen**:
   - Pick **External** → **Create**
   - App name: `RedditBot`
   - Add your email → **Save and Continue**
   - On the Scopes page → **Add or Remove Scopes** → search `youtube.upload` → check it → **Update**
   - **Save and Continue** through the rest
   - On Test Users → **Add Users** → add your Gmail → **Save**
   - Click **Back to Dashboard**
3. Click **Credentials** → **Create Credentials** → **OAuth client ID**:
   - Application type: **Desktop app**
   - Name: `RedditBot` → **Create**
4. A popup appears — copy your **Client ID** and **Client Secret** and save in Notes

### Part C — Get your refresh token

1. Go to **colab.research.google.com** → new notebook
2. Paste into Cell 1 — swap in your real Client ID and Secret:
```python
CLIENT_ID     = "YOUR_CLIENT_ID_HERE"
CLIENT_SECRET = "YOUR_CLIENT_SECRET_HERE"

auth_url = (
    "https://accounts.google.com/o/oauth2/auth"
    f"?client_id={CLIENT_ID}"
    "&redirect_uri=urn:ietf:wg:oauth:2.0:oob"
    "&response_type=code"
    "&scope=https://www.googleapis.com/auth/youtube.upload"
    "&access_type=offline"
    "&prompt=consent"
)
print("Open this URL in your browser:")
print(auth_url)
```
Press ▶ → open the URL → sign in → Allow → copy the code

3. Paste into Cell 2 — swap in your code:
```python
import requests
AUTH_CODE = "PASTE_CODE_FROM_BROWSER_HERE"

resp = requests.post("https://oauth2.googleapis.com/token", data={
    "code":          AUTH_CODE,
    "client_id":     CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "redirect_uri":  "urn:ietf:wg:oauth:2.0:oob",
    "grant_type":    "authorization_code",
})
tokens = resp.json()
print("YOUR REFRESH TOKEN:")
print(tokens["refresh_token"])
```
Press ▶ → copy the refresh token

---

## STEP 5 — Add your keys to GitHub
*GitHub keeps them secret and uses them when the bot runs*

1. Go to your forked repo on GitHub
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret** and add all 6 of these:

| Secret name | Value |
|---|---|
| `GEMINI_API_KEY` | From Step 1 |
| `ELEVENLABS_API_KEY` | From Step 2 |
| `RCLONE_CONFIG_B64` | From Step 3 (skip if you skipped Step 3) |
| `YT_CLIENT_ID` | From Step 4B (full value ending in `.apps.googleusercontent.com`) |
| `YT_CLIENT_SECRET` | From Step 4B |
| `YT_REFRESH_TOKEN` | From Step 4C |

---

## STEP 6 — Add background videos
*The bot picks one randomly each day as the video background*

⚠️ **Only use videos from these free sites — anything else will get copyright blocked:**
- **pexels.com/videos** — search "rain", "cooking", "city night", "nature"
- **pixabay.com/videos** — same
- **mixkit.co** — free loops

Download 3–4 clips. Then in your GitHub repo:
1. Click the `backgrounds/` folder
2. **Add file** → **Upload files**
3. Upload your `.mp4` files → **Commit changes**

---

## STEP 7 — Test it

1. Go to your repo → click **Actions** tab
2. Click **Reddit Story Bot — Daily Video** on the left
3. Click **Run workflow** → **Run workflow** (green button)
4. Wait 3 minutes — watch it run live
5. Click the finished run → see the YouTube link in the summary
6. Check **YouTube Studio** → your video is there, scheduled to go public at 7 PM!

---

## Customize the stories

Go to your repo → click `generate_video.py` → click the ✏️ pencil icon → find this
section around line 40 and edit whatever you want:

```python
prompt = f"""Write a Reddit story for r/{sub}.
Rules:
- Start with a punchy hook sentence (max 10 words) like "She betrayed me. So I ended her career."
- Story body: 130 to 150 words total including the hook
- First-person, past tense, emotionally engaging
- Clear setup, conflict, satisfying resolution or twist
- No Edit sections, no usernames, no markdown
```

**Things you can change:**
- The hook style — make it funnier, darker, more dramatic
- Word count — shorter = faster video, longer = more detail
- Which subreddits it picks from — change the `SUBREDDITS` list
- The voice — change `TTS_VOICE` at the top of the file:
  - `en-US-GuyNeural` — US male (default)
  - `en-US-AriaNeural` — US female, expressive
  - `en-GB-RyanNeural` — British male
  - `en-AU-NatashaNeural` — Australian female

After editing click **Commit changes** — takes effect on the next run.

---

## Change what time the video posts

In your repo open `.github/workflows/daily_video.yml` and change `PUBLISH_HOUR_UTC`:

| Value | Montreal time |
|---|---|
| `22` | 6 PM |
| `23` | 7 PM ← default |
| `0` | 8 PM |
| `1` | 9 PM |

---

## Keep it running forever

- **Every 60 days** upload a new background video or make any small edit —
  GitHub pauses scheduled bots after 60 days of no activity
- **ElevenLabs** — upgrade to $5/month if you hit the free limit
- **YouTube refresh token** — if YouTube uploads stop working after several months,
  just redo Step 4C to get a fresh token and update the GitHub secret

---

## Something broke?

Go to **Actions** tab → click the failed run → look for the red error line.

| Error | Fix |
|---|---|
| `503 Gemini` | Just run it again — Gemini was temporarily busy |
| `401 YouTube` | Redo Step 4C to get a fresh refresh token |
| `Video blocked / Copyright` | Replace background videos with ones from Pexels/Pixabay |
| `No text on video` | Post the error in the support chat |
| `Drive upload failed` | Redo Step 3 — doesn't affect YouTube |
