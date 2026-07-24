"""Stage 4 — assemble the finished vertical Short with FFmpeg.

For each scene it builds a clip (image + gentle Ken-Burns zoom + burned-in caption + the
scene's voiceover), concatenates them, and mixes optional background music.

Writes output/<job>/video.mp4 — this is APPROVAL #2: watch it before uploading.

    python scripts/assemble_video.py --job 123

Requires ffmpeg + ffprobe on PATH.
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

from common import env, job_dir, load_script, scene_stem

FONT_CANDIDATES = [
    env("FONT_PATH"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def font_path() -> str | None:
    for p in FONT_CANDIDATES:
        if p and Path(p).exists():
            return p
    return None


def audio_duration(path: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    )
    return float(out.strip())


def build_scene_clip(image: Path, audio: Path, caption: str, out: Path,
                     w: int, h: int, font: str | None) -> None:
    dur = audio_duration(audio)
    frames = max(1, int(dur * 25))

    # Gentle Ken-Burns zoom on a single still, scaled up first to avoid jitter.
    vf = (
        f"scale=8000:-1,"
        f"zoompan=z='min(zoom+0.0005,1.15)':d={frames}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps=25,"
        f"format=yuv420p"
    )

    if font and caption:
        # Caption goes in a temp file so arbitrary narration text needs no escaping.
        cap_file = out.with_suffix(".caption.txt")
        cap_file.write_text(caption, encoding="utf-8")
        vf += (
            f",drawtext=fontfile='{font}':textfile='{cap_file}':"
            f"fontcolor=white:fontsize=54:box=1:boxcolor=black@0.5:boxborderw=18:"
            f"line_spacing=8:x=(w-text_w)/2:y=h-text_h-180"
        )

    subprocess.run(
        ["ffmpeg", "-y", "-loop", "1", "-i", str(image), "-i", str(audio),
         "-t", f"{dur}", "-vf", vf,
         "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-r", "25", "-shortest", str(out)],
        check=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    args = ap.parse_args()

    w = int(env("VIDEO_WIDTH", "1080"))
    h = int(env("VIDEO_HEIGHT", "1920"))
    font = font_path()
    if not font:
        print("⚠  No caption font found — building video without burned-in captions. "
              "Set FONT_PATH in .env to enable them.")

    jd = job_dir(args.job)
    script = load_script(args.job)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        clips = []
        for i, scene in enumerate(script["scenes"]):
            stem = scene_stem(i)
            clip = tmp / f"{stem}.mp4"
            build_scene_clip(
                image=jd / "images" / f"{stem}.png",
                audio=jd / "audio" / f"{stem}.mp3",
                caption=scene["narration"],
                out=clip, w=w, h=h, font=font,
            )
            clips.append(clip)
            print(f"  🎬 scene {i}")

        concat_list = tmp / "list.txt"
        concat_list.write_text("".join(f"file '{c}'\n" for c in clips), encoding="utf-8")

        stitched = tmp / "stitched.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
             "-c", "copy", str(stitched)],
            check=True,
        )

        final = jd / "video.mp4"
        music = env("BG_MUSIC_PATH")
        if music and Path(music).exists():
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(stitched), "-i", music,
                 "-filter_complex",
                 "[1:a]volume=0.12[m];[0:a][m]amix=inputs=2:duration=first[a]",
                 "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
                 "-b:a", "192k", str(final)],
                check=True,
            )
        else:
            stitched.replace(final)

    print(f"✅ Wrote {final}")
    print("   → Watch it now (this is APPROVAL #2) before uploading.")


if __name__ == "__main__":
    main()
