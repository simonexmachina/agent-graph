"""Persistent configuration for browser-observed web URLs."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any, cast
from urllib.parse import urldefrag, urlparse

import yaml
from pydantic import BaseModel, Field


class WebConfig(BaseModel):
    observation_urls: list[str] = Field(default_factory=list)


def load_web_settings() -> WebConfig:
    raw = _load_web_config()
    return WebConfig(**raw) if raw is not None else WebConfig()


def add_observation_urls(urls: list[str]) -> tuple[WebConfig, list[str]]:
    selected = _normalise_urls(urls)
    if not selected:
        raise ValueError("Usage: agentgraph connector web add <url> [url...]")
    config = load_web_settings()
    merged = [*config.observation_urls]
    added: list[str] = []
    for url in selected:
        if url not in merged:
            merged.append(url)
            added.append(url)
    updated = WebConfig(observation_urls=merged)
    save_web_config(updated)
    return updated, added


def remove_observation_urls(urls: list[str]) -> tuple[WebConfig, list[str]]:
    selected = _normalise_urls(urls)
    if not selected:
        raise ValueError("Usage: agentgraph connector web remove <url> [url...]")
    config = load_web_settings()
    remove_set = set(selected)
    removed = [url for url in config.observation_urls if url in remove_set]
    if not removed:
        raise ValueError("No matching web observation URLs are configured for removal")
    updated = WebConfig(
        observation_urls=[url for url in config.observation_urls if url not in remove_set]
    )
    save_web_config(updated)
    return updated, removed


def save_web_config(config: WebConfig) -> None:
    from agentgraph.config import get_config_paths

    CONFIG_DIR, CONFIG_FILE, CONFIG_YAML_FILE, _, _ = get_config_paths()

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = config.model_dump(mode="json")
    if CONFIG_YAML_FILE.exists():
        raw = _load_yaml_root(CONFIG_YAML_FILE)
        connectors = raw.setdefault("connectors", {})
        if not isinstance(connectors, dict):
            connectors = {}
            raw["connectors"] = connectors
        connectors["web"] = payload
        CONFIG_YAML_FILE.write_text(
            yaml.safe_dump(raw, sort_keys=False, allow_unicode=False), encoding="utf-8"
        )
        return

    existing = CONFIG_FILE.read_text(encoding="utf-8") if CONFIG_FILE.exists() else ""
    begin = "# BEGIN AgentGraph managed web config"
    end = "# END AgentGraph managed web config"
    start = existing.find(begin)
    if start >= 0:
        finish = existing.find(end, start)
        existing = existing[:start] + (existing[finish + len(end):] if finish >= 0 else "")
    block = "\n".join(
        [
            begin,
            "[connectors.web]",
            f"observation_urls = [{', '.join(json.dumps(url) for url in config.observation_urls)}]",
            end,
            "",
        ]
    )
    prefix = existing.rstrip()
    CONFIG_FILE.write_text(f"{prefix}\n\n{block}" if prefix else block, encoding="utf-8")


def _load_web_config() -> dict[str, Any] | None:
    from agentgraph.config import get_config_paths

    _, CONFIG_FILE, CONFIG_YAML_FILE, _, _ = get_config_paths()

    if CONFIG_YAML_FILE.exists():
        raw = _load_yaml_root(CONFIG_YAML_FILE)
    elif CONFIG_FILE.exists():
        try:
            raw = tomllib.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return None
    else:
        return None
    connectors: object = raw.get("connectors")
    connectors_dict = cast(dict[str, Any], connectors) if isinstance(connectors, dict) else {}
    web: object = connectors_dict.get("web")
    return _normalise_config(cast(dict[str, Any], web)) if isinstance(web, dict) else None


def _load_yaml_root(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return cast(dict[str, Any], raw) if isinstance(raw, dict) else {}


def _normalise_config(raw: dict[str, Any]) -> dict[str, Any]:
    return {"observation_urls": _normalise_urls(raw.get("observation_urls", []))}


def _normalise_urls(urls: object) -> list[str]:
    if isinstance(urls, str):
        urls = [urls]
    if not isinstance(urls, list):
        return []
    raw_urls = cast(list[object], urls)
    result: list[str] = []
    for raw in raw_urls:
        if not isinstance(raw, str):
            continue
        value = raw.strip()
        is_prefix = value.endswith("/*")
        candidate = value[:-2] if is_prefix else value
        parsed = urlparse(urldefrag(candidate)[0])
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        normalized = urldefrag(candidate)[0]
        if is_prefix:
            normalized += "/*"
        if normalized not in result:
            result.append(normalized)
    return result
