"""Stage 1 — generate a kids story + YouTube metadata with the Claude API.

Writes output/<job>/script.json. This file is APPROVAL #1: review/edit it before
running the later stages.

    python scripts/generate_script.py --job 123 --topic "a shy cloud learns to rain"
"""
import argparse
from typing import List

import anthropic
from pydantic import BaseModel, Field

from common import env, prompt_text, save_script


class Scene(BaseModel):
    narration: str = Field(description="One or two sentences spoken aloud for this scene.")
    image_prompt: str = Field(description="Vivid illustrator description; keep characters consistent.")


class Story(BaseModel):
    title: str
    scenes: List[Scene]
    description: str = Field(description="2-4 friendly sentences plus 3-5 hashtags.")
    tags: List[str]


def generate(topic: str) -> Story:
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    model = env("CLAUDE_MODEL", "claude-opus-5")

    story_instructions = prompt_text("story_prompt.md").replace("{{TOPIC}}", topic)
    meta_instructions = prompt_text("metadata_prompt.md").split("Story:")[0].strip()

    prompt = (
        f"{story_instructions}\n\n"
        f"Also produce the metadata described here:\n{meta_instructions}"
    )

    resp = client.messages.parse(
        model=model,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
        output_format=Story,
    )

    if resp.stop_reason == "refusal":
        raise SystemExit("The model declined this topic — pick a different, wholesome topic.")

    story = resp.parsed_output
    if story is None:
        raise SystemExit("Model did not return a valid story; try re-running.")
    return story


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--topic", required=True)
    args = ap.parse_args()

    story = generate(args.topic)
    save_script(args.job, story.model_dump())

    print(f"✅ Wrote output/{args.job}/script.json")
    print(f"   Title:  {story.title}")
    print(f"   Scenes: {len(story.scenes)}")
    print("   → Review/edit script.json now (this is APPROVAL #1).")


if __name__ == "__main__":
    main()
