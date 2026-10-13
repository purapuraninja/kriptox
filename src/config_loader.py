"""Config loader + helpers."""
from __future__ import annotations
from pathlib import Path
import yaml


def load_config(path: str = "config/config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def ensure_state_dirs(cfg: dict) -> None:
    Path(cfg.get("data", {}).get("state_dir", "state")).mkdir(parents=True, exist_ok=True)
    Path(cfg.get("review", {}).get("log_dir", "state/logs")).mkdir(parents=True, exist_ok=True)
