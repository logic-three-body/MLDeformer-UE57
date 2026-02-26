#!/usr/bin/env python3
"""Trigger ML Deformer training via C++ bridge and write train_report.json."""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Tuple

import unreal

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from ue_common import (
    finalize_report,
    get_context,
    make_report,
    require_nested,
    save_asset,
    write_stage_report,
)


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


def _request_class():
    for name in ("MldTrainRequest", "FMldTrainRequest"):
        cls = getattr(unreal, name, None)
        if cls is not None:
            return cls
    raise RuntimeError("Cannot find MldTrainRequest struct in Unreal Python API")


def _snapshot_network_files(project_dir: Path) -> Dict[str, float]:
    suffixes = (".nmn", ".ubnne")
    roots = [project_dir / "Intermediate", project_dir / "Saved", project_dir / "Content"]

    snap: Dict[str, float] = {}
    for root in roots:
        if not root.exists():
            continue
        for dirpath, _, filenames in os.walk(root):
            for name in filenames:
                lower = name.lower()
                if not lower.endswith(suffixes):
                    continue
                p = Path(dirpath) / name
                try:
                    snap[str(p)] = p.stat().st_mtime
                except OSError:
                    continue
    return snap


def _latest_network_path(
    before: Dict[str, float],
    after: Dict[str, float],
    model_type: str,
) -> str:
    target_ext = ".nmn" if model_type.upper() == "NMM" else ".ubnne"

    changed: List[Tuple[str, float]] = []
    for path, mtime in after.items():
        if not path.lower().endswith(target_ext):
            continue
        old = before.get(path)
        if old is None or mtime > old:
            changed.append((path, mtime))

    if changed:
        changed.sort(key=lambda item: item[1], reverse=True)
        return changed[0][0]

    all_candidates = [(p, t) for p, t in after.items() if p.lower().endswith(target_ext)]
    if all_candidates:
        all_candidates.sort(key=lambda item: item[1], reverse=True)
        return all_candidates[0][0]

    return ""


def _build_request(asset_path: str, model_type: str):
    req = _request_class()()

    for key, value in (
        ("asset_path", asset_path),
        ("model_type", model_type),
        ("suppress_dialogs", True),
        ("force_switch", True),
    ):
        if not _set_field_safe(req, key, value):
            # Fallback in case reflected name casing changed.
            _set_field_safe(req, key.lower(), value)

    return req


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        if v in ("0", "false", "no", "off"):
            return False
    return default


def _env_or_default(name: str, default: Any) -> Any:
    value = os.environ.get(name, "")
    if value == "":
        return default
    return value


def _resolve_determinism(cfg: Dict[str, Any]) -> Dict[str, Any]:
    ue_cfg = cfg.get("ue", {}) if isinstance(cfg.get("ue"), dict) else {}
    training_cfg = ue_cfg.get("training", {}) if isinstance(ue_cfg.get("training"), dict) else {}
    det_cfg = training_cfg.get("determinism", {}) if isinstance(training_cfg.get("determinism"), dict) else {}

    enabled = _as_bool(det_cfg.get("enabled", True), True)
    seed = int(det_cfg.get("seed", 3407))
    torch_deterministic = _as_bool(det_cfg.get("torch_deterministic", True), True)
    cudnn_deterministic = _as_bool(det_cfg.get("cudnn_deterministic", True), True)
    cudnn_benchmark = _as_bool(det_cfg.get("cudnn_benchmark", False), False)

    enabled = _as_bool(_env_or_default("HOU2UE_TRAIN_DETERMINISM_ENABLED", enabled), enabled)
    seed = int(_env_or_default("HOU2UE_TRAIN_SEED", seed))
    torch_deterministic = _as_bool(_env_or_default("HOU2UE_TORCH_DETERMINISTIC", torch_deterministic), torch_deterministic)
    cudnn_deterministic = _as_bool(_env_or_default("HOU2UE_CUDNN_DETERMINISTIC", cudnn_deterministic), cudnn_deterministic)
    cudnn_benchmark = _as_bool(_env_or_default("HOU2UE_CUDNN_BENCHMARK", cudnn_benchmark), cudnn_benchmark)

    return {
        "enabled": enabled,
        "seed": seed,
        "torch_deterministic": torch_deterministic,
        "cudnn_deterministic": cudnn_deterministic,
        "cudnn_benchmark": cudnn_benchmark,
    }


def _apply_determinism_env(settings: Dict[str, Any]) -> Dict[str, str]:
    seed = int(settings.get("seed", 3407))
    applied = {
        "PYTHONHASHSEED": str(seed),
        "HOU2UE_TRAIN_SEED": str(seed),
        "HOU2UE_TRAIN_DETERMINISM_ENABLED": "1" if bool(settings.get("enabled", True)) else "0",
        "HOU2UE_TORCH_DETERMINISTIC": "1" if bool(settings.get("torch_deterministic", True)) else "0",
        "HOU2UE_CUDNN_DETERMINISTIC": "1" if bool(settings.get("cudnn_deterministic", True)) else "0",
        "HOU2UE_CUDNN_BENCHMARK": "1" if bool(settings.get("cudnn_benchmark", False)) else "0",
    }
    for key, value in applied.items():
        os.environ[key] = value
    return applied


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def _train_single_asset(asset_path: str, model_type: str, project_dir: Path) -> Dict[str, Any]:
    train_lib = getattr(unreal, "MLDTrainAutomationLibrary", None)
    if train_lib is None:
        raise RuntimeError("MLDTrainAutomationLibrary is not available")

    train_fn = getattr(train_lib, "train_deformer_asset", None)
    if train_fn is None:
        raise RuntimeError("train_deformer_asset function missing on MLDTrainAutomationLibrary")

    before = _snapshot_network_files(project_dir)
    req = _build_request(asset_path, model_type)
    result = train_fn(req)
    after = _snapshot_network_files(project_dir)

    network_path = _latest_network_path(before, after, model_type)

    success = bool(_get_field_safe(result, "success", False))
    result_code = int(_get_field_safe(result, "training_result_code", -1))
    duration_sec = float(_get_field_safe(result, "duration_sec", 0.0))
    network_loaded = bool(_get_field_safe(result, "network_loaded", False))
    message = str(_get_field_safe(result, "message", ""))

    save_asset(asset_path)

    return {
        "asset_path": asset_path,
        "model_type": model_type,
        "success": success,
        "training_result_code": result_code,
        "duration_sec": duration_sec,
        "network_loaded": network_loaded,
        "network_file_path": network_path,
        "message": message,
    }


def main() -> int:
    ctx = get_context()
    cfg = ctx["config"]
    run_dir: Path = ctx["run_dir"]
    profile: str = ctx["profile"]

    report = make_report(
        "train",
        profile,
        {
            "config": str(ctx["config_path"]),
            "run_dir": str(run_dir),
            "profile": profile,
        },
    )

    try:
        project_dir = Path(unreal.Paths.project_dir())
        deformer_cfg = require_nested(cfg, ("ue", "deformer_assets"))
        order = list(require_nested(cfg, ("ue", "training_order")))
        determinism = _resolve_determinism(cfg)
        applied_env = _apply_determinism_env(determinism)

        results: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []

        for key in order:
            item = deformer_cfg.get(key)
            if not isinstance(item, dict):
                errors.append({"message": f"Missing deformer_assets entry: {key}"})
                continue

            asset_path = str(require_nested(item, ("asset_path",)))
            model_type = str(require_nested(item, ("model_type",)))

            try:
                train_result = _train_single_asset(asset_path, model_type, project_dir)
                train_result["determinism"] = determinism
                results.append(train_result)

                if not train_result["success"]:
                    errors.append(
                        {
                            "message": f"Training failed for {asset_path}",
                            "training_result_code": train_result["training_result_code"],
                            "detail": train_result["message"],
                        }
                    )
                elif not train_result["network_loaded"]:
                    errors.append(
                        {
                            "message": f"Training finished but network not loaded for {asset_path}",
                            "training_result_code": train_result["training_result_code"],
                        }
                    )
            except Exception as exc:
                errors.append(
                    {
                        "message": f"Exception while training {asset_path}: {exc}",
                        "traceback": traceback.format_exc(),
                    }
                )

        status = "success" if not errors else "failed"
        determinism_report = make_report(
            "train_determinism",
            profile,
            {
                "config": str(ctx["config_path"]),
                "run_dir": str(run_dir),
                "profile": profile,
            },
        )
        finalize_report(
            determinism_report,
            status="success",
            outputs={
                "settings": determinism,
                "applied_env": applied_env,
            },
            errors=[],
        )
        _write_json(run_dir / "reports" / "train_determinism_report.json", determinism_report)

        finalize_report(
            report,
            status=status,
            outputs={
                "results": results,
                "trained_count": len([r for r in results if r.get("success")]),
                "failed_count": len(errors),
                "determinism": determinism,
                "train_determinism_report": str((run_dir / "reports" / "train_determinism_report.json").resolve()),
            },
            errors=errors,
        )
        write_stage_report(run_dir, "train", report)
        return 0 if status == "success" else 1

    except Exception as exc:
        finalize_report(
            report,
            status="failed",
            outputs={},
            errors=[{"message": str(exc), "traceback": traceback.format_exc()}],
        )
        write_stage_report(run_dir, "train", report)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
