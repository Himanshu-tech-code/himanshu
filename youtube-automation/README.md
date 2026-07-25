# Faceless Animated Kids Stories — Automated YouTube Shorts Pipeline

An **n8n-orchestrated** pipeline that turns a topic into a finished YouTube Short with only
**two approval taps** from you. Built for a **"Made for Kids" (MFK)** animated-stories channel.

```
[0] Trend research (Claude + web search) → ranked kid-safe topics
        │
[1] Idea + Script (Claude, from top topic)  ──►  ✅ APPROVAL #1 (script)
        │
[2] Voiceover (ElevenLabs / TTS)
        │
[3] Scene images (AI, consistent style)
        │
[4] Assemble video (FFmpeg: images + voice + captions + music)  ──►  ✅ APPROVAL #2 (final)
        │
[5] Title / description / tags / thumbnail (Claude)
        │
[6] Upload + schedule to YouTube (madeForKids = true)
        │
[7] Pull analytics ──► feed next ideas
```

> ⚠️ **Read `docs/KIDS-CONTENT-RULES.md` before publishing.** "Made for Kids" is a legal
> designation (COPPA). It turns off personalized ads (low RPM), disables comments, and
> triggers extra platform scrutiny of mass AI content. This pipeline is tuned for that reality:
> quality-gated, high-retention, batch-produced.

---

## What each piece does

| Stage | File | Tool | Notes |
|---|---|---|---|
| Trend research | `scripts/research_trends.py` | Claude + web search | Researches what's working now, outputs ranked **kid-safe** topics to `topics.json` |
| Script + metadata | `scripts/generate_script.py` | Claude API | Uses the top researched topic; splits into scenes with narration + image prompt |
| Voiceover | `scripts/generate_voiceover.py` | ElevenLabs (or any TTS) | One MP3 per scene |
| Images | `scripts/generate_images.py` | AI image API (pluggable) | One image per scene, consistent style |
| Assembly | `scripts/assemble_video.py` | FFmpeg | Stitches images + audio + captions + music into a 9:16 MP4 |
| Upload | `scripts/upload_youtube.py` | YouTube Data API v3 | Sets `madeForKids: true`, schedules or publishes |
| Orchestration | `n8n/workflow.json` | n8n | Runs the whole flow, sends you the two approvals |

Every stage reads and writes a **job folder** at `output/<job_id>/` so the steps chain cleanly
(n8n calls them with Execute Command nodes, or you run them by hand to test).

### The job folder contract
```
output/<job_id>/
├── topics.json      # written by stage 0  (ranked kid-safe topic ideas)
├── script.json      # written by stage 1  (title, scenes[], metadata)
├── audio/           # written by stage 2  (scene_000.mp3, scene_001.mp3, …)
├── images/          # written by stage 3  (scene_000.png, scene_001.png, …)
├── video.mp4        # written by stage 4  (the finished Short)
└── upload.json      # written by stage 6  (YouTube video id + url)
```

---

## Step-by-step setup

### 1. Create the channel + Google Cloud project
1. Create the YouTube channel (a dedicated Google account is cleanest).
2. In [Google Cloud Console](https://console.cloud.google.com/): new project → **enable "YouTube Data API v3"**.
3. **OAuth consent screen** → External → add your account as a test user.
4. **Credentials → Create OAuth client ID → Desktop app** → download `client_secret.json`.

### 2. Get the API keys
- **Anthropic** (script + metadata): https://console.anthropic.com
- **ElevenLabs** (voiceover) or a free TTS (Google/Azure): https://elevenlabs.io
- **Image generation**: pick one (Flux / Stable Diffusion host / DALL·E / etc.) — see
  `scripts/generate_images.py` for where to plug it in.

### 3. Local install (for testing the scripts by hand)
```bash
cd youtube-automation
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# FFmpeg must be installed on the system:  apt-get install ffmpeg   (or brew install ffmpeg)
cp .env.example .env      # then fill in your keys
```

### 4. First-run: authorize YouTube once
```bash
python scripts/upload_youtube.py --authorize   # opens a browser, writes token.json
```

### 5. Test the pipeline end-to-end by hand (before automating)
```bash
JOB=$(date +%s)
python scripts/research_trends.py    --job "$JOB" --count 5
#   → review output/$JOB/topics.json (ranked kid-safe topics from live research)
python scripts/generate_script.py    --job "$JOB" --from-research
#   → review output/$JOB/script.json, edit if needed   (this is APPROVAL #1)
#   (or override the topic manually:  --topic "a shy little cloud learns to make rain")
python scripts/generate_voiceover.py --job "$JOB"
python scripts/generate_images.py    --job "$JOB"
python scripts/assemble_video.py     --job "$JOB"
#   → watch output/$JOB/video.mp4                        (this is APPROVAL #2)
python scripts/upload_youtube.py     --job "$JOB" --privacy private
```
Run 3–5 videos this way until the quality is where you want it.

### 6. Stand up n8n and wire the approvals
```bash
docker run -it --rm --name n8n -p 5678:5678 \
  -v ~/.n8n:/home/node/.n8n \
  -v $(pwd):/workspace \
  docker.n8n.io/n8nio/n8n
```
Open http://localhost:5678 → import `n8n/workflow.json`. See `n8n/README.md` for wiring the
Execute Command nodes, the two **"Send and Wait for Approval"** nodes (Telegram or email), and
the schedule trigger.

### 7. Turn on the schedule and batch toward monetization
Set the n8n Schedule trigger to your cadence (e.g. 2–3 shorts/day). Once you clear the
YouTube Partner Program threshold, apply for monetization.

---

## Cost (rough, ~1–3 shorts/day)
- Anthropic + ElevenLabs + image gen: **~$30–80/mo**
- n8n: free self-hosted (or ~$20/mo cloud)
- FFmpeg / YouTube API: free
- **Total: ~$40–150/mo** depending on volume and quality tier.

## Repo layout
```
youtube-automation/
├── README.md                     ← you are here
├── .env.example
├── requirements.txt
├── docs/KIDS-CONTENT-RULES.md    ← READ THIS
├── prompts/
│   ├── research_prompt.md
│   ├── story_prompt.md
│   └── metadata_prompt.md
├── scripts/
│   ├── common.py
│   ├── research_trends.py
│   ├── generate_script.py
│   ├── generate_voiceover.py
│   ├── generate_images.py
│   ├── assemble_video.py
│   └── upload_youtube.py
└── n8n/
    ├── README.md
    └── workflow.json
```
