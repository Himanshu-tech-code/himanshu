"""Shared helpers for the pipeline: job folders and the script.json contract."""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# output/ lives next to the youtube-automation folder root.
ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"


def job_dir(job_id: str) -> Path:
    d = OUTPUT / str(job_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def script_path(job_id: str) -> Path:
    return job_dir(job_id) / "script.json"


def load_script(job_id: str) -> dict:
    with open(script_path(job_id), encoding="utf-8") as f:
        return json.load(f)


def save_script(job_id: str, data: dict) -> None:
    with open(script_path(job_id), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def scene_stem(index: int) -> str:
    """Stable per-scene filename stem, e.g. scene_003."""
    return f"scene_{index:03d}"


def prompt_text(name: str) -> str:
    with open(ROOT / "prompts" / name, encoding="utf-8") as f:
        return f.read()


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)
