"""Stage 6 — upload the finished Short to YouTube (Made for Kids).

    python scripts/upload_youtube.py --authorize          # one-time browser login
    python scripts/upload_youtube.py --job 123 --privacy private
    python scripts/upload_youtube.py --job 123 --publish-at 2026-08-01T15:00:00Z

Sets selfDeclaredMadeForKids=true on every upload (see docs/KIDS-CONTENT-RULES.md).

NOTE: YouTube's "altered or synthetic content" (AI) disclosure is not reliably settable
via the Data API — set it in YouTube Studio at publish time, and keep the honest note in
the description. This script puts an AI-disclosure line in the description automatically.
"""
import argparse

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from common import env, job_dir, load_script

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
AI_DISCLOSURE = "\n\nThis video uses AI-generated narration and illustrations."


def get_credentials() -> Credentials:
    token = env("YOUTUBE_TOKEN", "token.json")
    secret = env("YOUTUBE_CLIENT_SECRET", "client_secret.json")
    creds = None
    try:
        creds = Credentials.from_authorized_user_file(token, SCOPES)
    except FileNotFoundError:
        pass
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(secret, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(token, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return creds


def upload(job: str, privacy: str, publish_at: str | None) -> None:
    script = load_script(job)
    video_file = job_dir(job) / "video.mp4"
    if not video_file.exists():
        raise SystemExit(f"{video_file} not found — run assemble_video.py first.")

    youtube = build("youtube", "v3", credentials=get_credentials())

    status = {
        "privacyStatus": "private" if publish_at else privacy,
        "selfDeclaredMadeForKids": True,
    }
    if publish_at:
        status["publishAt"] = publish_at  # RFC3339 UTC, e.g. 2026-08-01T15:00:00Z

    body = {
        "snippet": {
            "title": script["title"][:100],
            "description": (script["description"] + AI_DISCLOSURE)[:5000],
            "tags": script.get("tags", [])[:15],
            "categoryId": "1",  # Film & Animation
        },
        "status": status,
    }

    media = MediaFileUpload(str(video_file), chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        _, response = request.next_chunk()

    vid = response["id"]
    url = f"https://youtu.be/{vid}"
    (job_dir(job) / "upload.json").write_text(
        f'{{"video_id": "{vid}", "url": "{url}"}}\n', encoding="utf-8"
    )
    print(f"✅ Uploaded: {url}")
    if publish_at:
        print(f"   Scheduled to go public at {publish_at}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--authorize", action="store_true", help="Run the one-time OAuth flow and exit.")
    ap.add_argument("--job")
    ap.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    ap.add_argument("--publish-at", help="RFC3339 UTC time to auto-publish (implies private now).")
    args = ap.parse_args()

    if args.authorize:
        get_credentials()
        print("✅ Authorized — token saved.")
        return

    if not args.job:
        ap.error("--job is required (or use --authorize)")
    upload(args.job, args.privacy, args.publish_at)


if __name__ == "__main__":
    main()
