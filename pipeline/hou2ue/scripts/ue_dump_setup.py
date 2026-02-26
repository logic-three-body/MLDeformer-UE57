#!/usr/bin/env python3
"""Dump ML Deformer setup payloads through C++ bridge inside UE process."""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List

import unreal

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from ue_common import finalize_report, get_context, make_report, require_nested


def _request_class():
    for name in ("MldDumpRequest", "FMldDumpRequest"):
        cls = getattr(unreal, name, None)
        if cls is not None:
            return cls
    raise RuntimeError("Cannot find MldDumpRequest struct in Unreal Python API")


def _set_field_safe(obj: Any, key: str, value: Any) -> bool:
    try:
        obj.set_editor_property(key, value)
        return True
    except Exception:
        return False


def _get_field_safe(obj: Any, key: str, default: Any = None) -> Any:
    try:
        return obj.get_editor_property(key)
    except Exception:
        return default


def _dump_asset(asset_path: str) -> Dict[str, Any]:
    lib = getattr(unreal, "MLDTrainAutomationLibrary", None)
    if lib is None:
        raise RuntimeError("MLDTrainAutomationLibrary class missing")
    fn = getattr(lib, "dump_deformer_setup", None)
    if fn is None:
        raise RuntimeError("dump_deformer_setup function missing on MLDTrainAutomationLibrary")

    req = _request_class()()
    if not _set_field_safe(req, "asset_path", asset_path):
        _set_field_safe(req, "assetpath", asset_path)

    result = fn(req)
    return {
        "asset_path": asset_path,
        "success": bool(_get_field_safe(result, "success", False)),
        "message": str(_get_field_safe(result, "message", "")),
        "model_type": str(_get_field_safe(result, "model_type", "")),
        "skeletal_mesh": str(_get_field_safe(result, "skeletal_mesh", "")),
        "deformer_graph": str(_get_field_safe(result, "deformer_graph", "")),
        "test_anim": str(_get_field_safe(result, "test_anim", "")),
        "training_input_anims_json": str(_get_field_safe(result, "training_input_anims_json", "[]")),
        "nnm_sections_json": str(_get_field_safe(result, "nnm_sections_json", "[]")),
        "model_overrides_json": str(_get_field_safe(result, "model_overrides_json", "{}")),
    }


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def main() -> int:
    ctx = get_context()
    cfg = ctx["config"]
    profile = ctx["profile"]

    dump_kind = str(os.environ.get("HOU2UE_DUMP_KIND", "source") or "source").strip().lower()
    output_raw = str(os.environ.get("HOU2UE_DUMP_OUTPUT", "") or "").strip()
    if not output_raw:
        raise RuntimeError("HOU2UE_DUMP_OUTPUT is required")
    output_path = Path(output_raw).resolve()

    report = make_report(
        stage=f"{dump_kind}_setup_dump",
        profile=profile,
        inputs={
            "config": str(ctx["config_path"]),
            "run_dir": str(ctx["run_dir"]),
            "profile": profile,
            "dump_kind": dump_kind,
            "output_path": str(output_path),
            "project_dir": str(unreal.Paths.project_dir()),
        },
    )

    try:
        assets_cfg = require_nested(cfg, ("ue", "deformer_assets"))
        order = list(require_nested(cfg, ("ue", "training_order")))

        rows: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        for key in order:
            item = assets_cfg.get(key)
            if not isinstance(item, dict):
                errors.append({"message": f"Missing deformer_assets entry: {key}"})
                continue
            asset_path = str(require_nested(item, ("asset_path",)))
            dumped = _dump_asset(asset_path)
            dumped["key"] = key
            rows.append(dumped)
            if not dumped["success"]:
                errors.append(
                    {
                        "message": f"Dump failed for {asset_path}",
                        "key": key,
                        "detail": dumped.get("message", ""),
                    }
                )

        status = "success" if not errors else "failed"
        finalize_report(
            report,
            status=status,
            outputs={
                "dump_kind": dump_kind,
                "asset_count": len(rows),
                "assets": rows,
            },
            errors=errors,
        )
        _write_json(output_path, report)
        return 0 if status == "success" else 1

    except Exception as exc:
        finalize_report(
            report,
            status="failed",
            outputs={},
            errors=[{"message": str(exc), "traceback": traceback.format_exc()}],
        )
        _write_json(output_path, report)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
