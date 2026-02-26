#!/usr/bin/env python3
"""Common helpers for the Houdini -> UE pipeline scripts."""

from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List


REPORT_KEYS = (
    "stage",
    "profile",
    "started_at",
    "ended_at",
    "status",
    "inputs",
    "outputs",
    "errors",
)


def utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def timestamp_compact() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d_%H%M%S")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")


class ConfigError(RuntimeError):
    pass


def load_config(path: str | Path) -> Dict[str, Any]:
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise ConfigError(f"Config does not exist: {cfg_path}")

    raw = read_text(cfg_path).lstrip("\ufeff")

    # YAML 1.2 is a superset of JSON. Keep config JSON-compatible to avoid hard dependency.
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ConfigError(f"Config root must be an object: {cfg_path}")
        return parsed
    except json.JSONDecodeError:
        pass

    try:
        import yaml  # type: ignore

        parsed = yaml.safe_load(raw)
        if not isinstance(parsed, dict):
            raise ConfigError(f"Config root must be an object: {cfg_path}")
        return parsed
    except ModuleNotFoundError as exc:
        raise ConfigError(
            "Config parsing failed as JSON, and PyYAML is not installed. "
            "Use JSON-compatible YAML or install PyYAML."
        ) from exc


def get_nested(data: Dict[str, Any], keys: Iterable[str], default: Any = None) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def require_nested(data: Dict[str, Any], keys: Iterable[str]) -> Any:
    cur: Any = data
    traversed: List[str] = []
    for key in keys:
        traversed.append(key)
        if not isinstance(cur, dict) or key not in cur:
            joined = ".".join(traversed)
            raise ConfigError(f"Missing required config key: {joined}")
        cur = cur[key]
    return cur


def profile_data(config: Dict[str, Any], profile: str) -> Dict[str, Any]:
    profiles = require_nested(config, ("profiles",))
    if profile not in profiles:
        raise ConfigError(f"Unknown profile '{profile}'. Valid: {sorted(profiles.keys())}")
    val = profiles[profile]
    if not isinstance(val, dict):
        raise ConfigError(f"Profile '{profile}' must be an object")
    return val


def make_report(stage: str, profile: str, inputs: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {
        "stage": stage,
        "profile": profile,
        "started_at": utc_now_iso(),
        "ended_at": "",
        "status": "running",
        "inputs": inputs or {},
        "outputs": {},
        "errors": [],
    }


def finalize_report(
    report: Dict[str, Any],
    status: str,
    outputs: Dict[str, Any] | None = None,
    errors: List[Any] | None = None,
) -> Dict[str, Any]:
    report["ended_at"] = utc_now_iso()
    report["status"] = status
    report["outputs"] = outputs or {}
    report["errors"] = errors or []
    # keep report schema stable
    for key in REPORT_KEYS:
        report.setdefault(key, [] if key == "errors" else {})
    return report


def stage_report_path(run_dir: Path, stage: str) -> Path:
    return run_dir / "reports" / f"{stage}_report.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def rel_or_abs(base: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (base / p).resolve()


def list_files_recursive(root: Path, contains_token: str) -> List[Path]:
    if not root.exists():
        return []
    out: List[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and contains_token in path.name:
            out.append(path)
    return sorted(out)


def apply_template(value: str, profile: str, run_dir: Path) -> str:
    return value.format(profile=profile, run_dir=str(run_dir).replace("\\", "/"))


def env_or_default(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)
