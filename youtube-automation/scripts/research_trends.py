"""Stage 0 — research currently-viral, kid-safe topics with Claude's web search.

Writes output/<job>/topics.json (a ranked list). Stage 1 (generate_script.py --from-research)
uses the top entry unless you pick a different one.

    python scripts/research_trends.py --job 123 --count 5

The web-search tool runs server-side on Anthropic's infra; results feed the model directly.
"""
import argparse
import json
from typing import List

import anthropic
from pydantic import BaseModel, Field

from common import env, job_dir, prompt_text

# Latest web-search tool (dynamic filtering). Fall back to web_search_20250305 on older models.
WEB_SEARCH_TOOL = env("WEB_SEARCH_TOOL", "web_search_20260209")


class Topic(BaseModel):
    topic: str = Field(description="Short topic label.")
    angle: str = Field(description="The specific story hook/angle.")
    why_trending: str = Field(description="Why it should perform, tied to the research.")
    kid_safe: bool


class Topics(BaseModel):
    topics: List[Topic]


def research(count: int) -> Topics:
    client = anthropic.Anthropic()
    model = env("CLAUDE_MODEL", "claude-opus-5")
    instructions = prompt_text("research_prompt.md").replace("{{N}}", str(count))

    # Step 1: research with web search. Loop to handle server-tool pause_turn.
    messages = [{"role": "user", "content": instructions}]
    tools = [{"type": WEB_SEARCH_TOOL, "name": "web_search"}]
    resp = None
    for _ in range(6):
        resp = client.messages.create(model=model, max_tokens=4000, tools=tools, messages=messages)
        if resp.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": resp.content})
            continue
        break

    research_text = "".join(b.text for b in resp.content if b.type == "text")

    # Step 2: structure the findings into a clean ranked list, kid-safe only.
    structured = client.messages.parse(
        model=model,
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": (
                f"From this research, extract the {count} best KID-SAFE animated-story topics, "
                f"ranked best first. Drop anything not fully safe for ages 3-7.\n\n{research_text}"
            ),
        }],
        output_format=Topics,
    )
    topics = structured.parsed_output
    if topics is None or not topics.topics:
        raise SystemExit("No topics returned — try re-running the research.")
    # Keep only kid-safe, preserve order.
    topics.topics = [t for t in topics.topics if t.kid_safe] or topics.topics
    return topics


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--count", type=int, default=5)
    args = ap.parse_args()

    topics = research(args.count)
    out = job_dir(args.job) / "topics.json"
    out.write_text(json.dumps(topics.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"✅ Wrote {out}")
    for i, t in enumerate(topics.topics):
        print(f"  {i}. {t.topic} — {t.angle}")
    print("   Top pick will be used by generate_script.py --from-research.")


if __name__ == "__main__":
    main()
