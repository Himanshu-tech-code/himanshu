"""Stage 3 — generate one image per scene.

Writes output/<job>/images/scene_NNN.png.

    python scripts/generate_images.py --job 123

IMAGE PROVIDER IS PLUGGABLE. Point IMAGE_API_URL / IMAGE_API_KEY at whatever you use
(a Flux/Stable-Diffusion host, DALL-E, etc.) and adjust generate_image() to that API's
request/response shape. The default below assumes a generic JSON endpoint that accepts
{"prompt": ...} and returns either raw image bytes or {"image_base64": ...}. Adjust to fit.
"""
import argparse
import base64

import requests

from common import env, job_dir, load_script, scene_stem

# 9:16 vertical framing so the image fills a Short without letterboxing.
ASPECT = "vertical 9:16 composition, full-frame, subject centered"


def generate_image(prompt: str, out_path) -> None:
    api_url = env("IMAGE_API_URL")
    api_key = env("IMAGE_API_KEY")
    style = env("IMAGE_STYLE", "children's storybook illustration, warm colors, no text")
    if not api_url:
        raise SystemExit(
            "Set IMAGE_API_URL/IMAGE_API_KEY in .env and adapt generate_image() "
            "to your image provider's request/response shape."
        )

    full_prompt = f"{prompt}. {style}. {ASPECT}."
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    resp = requests.post(api_url, headers=headers, json={"prompt": full_prompt}, timeout=180)
    resp.raise_for_status()

    ctype = resp.headers.get("content-type", "")
    if ctype.startswith("image/"):
        data = resp.content
    else:
        # Assume JSON with a base64 field. Adjust the key to match your provider.
        body = resp.json()
        b64 = body.get("image_base64") or body.get("b64_json") or body.get("image")
        if not b64:
            raise SystemExit(f"Could not find image data in response: {list(body)[:5]}")
        data = base64.b64decode(b64)

    with open(out_path, "wb") as f:
        f.write(data)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    args = ap.parse_args()

    script = load_script(args.job)
    img_dir = job_dir(args.job) / "images"
    img_dir.mkdir(exist_ok=True)

    for i, scene in enumerate(script["scenes"]):
        out = img_dir / f"{scene_stem(i)}.png"
        generate_image(scene["image_prompt"], out)
        print(f"  🖼  {out.name}")

    print(f"✅ Images done for job {args.job}")


if __name__ == "__main__":
    main()
