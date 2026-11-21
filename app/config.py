"""Configuration loading for race-engineer-ai."""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "config.yaml"


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


DEFAULTS: dict[str, Any] = {
    "telemetry": {"host": "0.0.0.0", "port": 20777},
    "audio": {
        "input_device": None,
        "output_device": None,
        "ptt_key": "f9",
        "ptt_mode": "tap",
        "end_on_silence_s": 1.2,
        "over_check_interval_s": 0.8,
        "over_words": ["over", "over and out"],
        "record_max_seconds": 25,
        "sample_rate": 16000,
    },
    "stt": {
        "model": "small.en",
        "spotter_model": "tiny.en",
        "device": "cpu",
        "compute_type": "int8",
        "language": "en",
        "beam_size": 1,
    },
    "tts": {
        "piper_exe": "models/piper/piper.exe",
        "voice_model": "models/piper/en_GB-alan-medium.onnx",
        "radio_filter": True,
        "volume": 1.0,
        "speed": 1.05,
        "player_output": False,
    },
    "brain": {
        "default_provider": "local",
        "smart_provider": "deepseek",
        "escalate_when": ["why", "should", "strategy", "undercut", "overcut", "choice",
                          "compare", "explain", "plan", "recommend", "predict"],
        "escalate_min_words": 12,
        "providers": {
            "local": {
                "base_url": "http://127.0.0.1:8080/v1",
                "model": "qwen2.5-7b-instruct",
                "api_key": "local",
                "temperature": 0.3,
                "max_tokens": 220,
                "timeout_s": 12,
                "first_token_deadline_s": 2.5,
            },
            "deepseek": {
                "base_url": "https://api.deepseek.com/v1",
                "model": "deepseek-flash",
                "api_key_env": "DEEPSEEK_API_KEY",
                "temperature": 0.3,
                "max_tokens": 220,
                "timeout_s": 20,
                "disable_thinking": True,
            },
        },
    },
    "engineer": {
        "name": "Race engineer",
        "max_sentences": 2,
        "proactive": True,
        "cooldown_s": 25,
        "speak_status_every_s": 0,
    },
    "strategy": {
        "pit_loss_s": 21.0,
        "traffic_window_s": 2.0,
    },
    "overlay": {
        "enabled": True,
        "state_file": ".temp/live_state.json",
        "x": 40,
        "y": 40,
        "scale": 1.0,
        "opacity": 0.88,
        "toggle_key": "f10",
    },
}


@dataclass
class Config:
    raw: dict[str, Any] = field(default_factory=dict)
    path: Path = DEFAULT_CONFIG

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def resolve_path(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else (PROJECT_ROOT / path)

    def provider(self, name: str) -> dict[str, Any]:
        providers = self.raw.get("brain", {}).get("providers", {})
        if name not in providers:
            raise KeyError(f"unknown brain provider: {name}")
        data = dict(providers[name])
        env = data.pop("api_key_env", None)
        if env:
            data["api_key"] = os.environ.get(env, "")
            data["api_key_env"] = env
        return data


def load_config(path: str | Path | None = None) -> Config:
    cfg_path = Path(path) if path else DEFAULT_CONFIG
    data: dict[str, Any] = {}
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"{cfg_path} must contain a YAML mapping")
        data = loaded
    return Config(raw=_deep_merge(DEFAULTS, data), path=cfg_path)
