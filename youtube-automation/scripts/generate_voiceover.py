"""Stage 2 — narrate each scene with ElevenLabs TTS.

Writes output/<job>/audio/scene_NNN.mp3 for every scene in script.json.

    python scripts/generate_voiceover.py --job 123

Swap in Google/Azure TTS by replacing synth_scene() — the rest of the pipeline
only cares that one MP3 per scene lands in the audio/ folder.
"""
import argparse

import requests

from common import env, job_dir, load_script, scene_stem


def synth_scene(text: str, out_path) -> None:
    api_key = env("ELEVENLABS_API_KEY")
    voice = env("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")
    model = env("ELEVENLABS_MODEL", "eleven_multilingual_v2")
    if not api_key:
        raise SystemExit("Set ELEVENLABS_API_KEY in .env (or replace synth_scene with your TTS).")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
    resp = requests.post(
        url,
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
        json={
            "text": text,
            "model_id": model,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        },
        timeout=120,
    )
    resp.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(resp.content)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    args = ap.parse_args()

    script = load_script(args.job)
    audio_dir = job_dir(args.job) / "audio"
    audio_dir.mkdir(exist_ok=True)

    for i, scene in enumerate(script["scenes"]):
        out = audio_dir / f"{scene_stem(i)}.mp3"
        synth_scene(scene["narration"], out)
        print(f"  🔊 {out.name}")

    print(f"✅ Voiceover done for job {args.job}")


if __name__ == "__main__":
    main()
