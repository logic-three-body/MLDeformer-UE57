#!/usr/bin/env python3
"""Helpers shared by UE Python stages."""

from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable


def utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_config_file(path: Path) -> Dict[str, Any]:
    raw = path.read_text(encoding="utf-8").lstrip("\ufeff")
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    try:
        import yaml  # type: ignore

        parsed = yaml.safe_load(raw)
        if isinstance(parsed, dict):
            return parsed
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Pipeline config is not JSON-compatible and PyYAML is not installed in UE Python."
        ) from exc

    raise RuntimeError(f"Unable to parse config file: {path}")


def _require_env(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


def get_context() -> Dict[str, Any]:
    config_path = Path(_require_env("HOU2UE_CONFIG"))
    run_dir = Path(_require_env("HOU2UE_RUN_DIR"))
    profile = _require_env("HOU2UE_PROFILE")

    config = _load_config_file(config_path)
    return {
        "config_path": config_path,
        "run_dir": run_dir,
        "profile": profile,
        "config": config,
    }


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
    errors: list[Any] | None = None,
) -> Dict[str, Any]:
    report["ended_at"] = utc_now_iso()
    report["status"] = status
    report["outputs"] = outputs or {}
    report["errors"] = errors or []
    return report


def write_stage_report(run_dir: Path, stage: str, report: Dict[str, Any]) -> Path:
    out_path = run_dir / "reports" / f"{stage}_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    return out_path


def get_nested(data: Dict[str, Any], keys: Iterable[str], default: Any = None) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def require_nested(data: Dict[str, Any], keys: Iterable[str]) -> Any:
    cur: Any = data
    path = []
    for key in keys:
        path.append(key)
        if not isinstance(cur, dict) or key not in cur:
            raise RuntimeError(f"Missing config key: {'.'.join(path)}")
        cur = cur[key]
    return cur


def apply_template(value: str, profile: str) -> str:
    return value.format(profile=profile)


def ensure_content_folder(folder: str) -> None:
    import unreal

    if not unreal.EditorAssetLibrary.does_directory_exist(folder):
        unreal.EditorAssetLibrary.make_directory(folder)


def asset_exists(asset_path: str) -> bool:
    import unreal

    return unreal.EditorAssetLibrary.does_asset_exist(asset_path)


def load_asset_checked(asset_path: str):
    import unreal

    asset = unreal.load_asset(asset_path)
    if asset is None:
        raise RuntimeError(f"Failed to load asset: {asset_path}")
    return asset


def split_asset_path(asset_path: str) -> tuple[str, str]:
    if "/" not in asset_path:
        raise RuntimeError(f"Invalid UE asset path: {asset_path}")
    folder, name = asset_path.rsplit("/", 1)
    return folder, name


def save_asset(asset_path: str) -> bool:
    import unreal

    return unreal.EditorAssetLibrary.save_asset(asset_path, only_if_is_dirty=False)
