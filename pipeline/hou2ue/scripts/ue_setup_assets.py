#!/usr/bin/env python3
"""Create/configure ML Deformer assets for NMM + NNM via C++ bridge."""

from __future__ import annotations

import csv
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Tuple

import unreal

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from ue_common import (
    apply_template,
    asset_exists,
    finalize_report,
    get_context,
    load_asset_checked,
    make_report,
    require_nested,
    save_asset,
    split_asset_path,
    write_stage_report,
)


def _apply_reference_override(root_cfg: Dict[str, Any], key: str, item_cfg: Dict[str, Any]) -> Dict[str, Any]:
    ref_cfg = root_cfg.get("reference_baseline", {})
    if not isinstance(ref_cfg, dict) or not bool(ref_cfg.get("enabled", False)):
        return item_cfg

    overrides = ref_cfg.get("deformer_assets_override", {})
    if not isinstance(overrides, dict):
        return item_cfg

    per_asset = overrides.get(key)
    if not isinstance(per_asset, dict):
        return item_cfg

    merged = dict(item_cfg)
    for override_key, override_value in per_asset.items():
        merged[override_key] = override_value
    return merged


def _dump_request_class():
    for name in ("MldDumpRequest", "FMldDumpRequest"):
        cls = getattr(unreal, name, None)
        if cls is not None:
            return cls
    raise RuntimeError("Cannot find MldDumpRequest struct in Unreal Python API")


def _call_dump(asset_path: str) -> Dict[str, Any]:
    lib = getattr(unreal, "MLDTrainAutomationLibrary", None)
    if lib is None:
        raise RuntimeError("MLDTrainAutomationLibrary class missing; cannot dump assets")
    fn = getattr(lib, "dump_deformer_setup", None)
    if fn is None:
        raise RuntimeError("dump_deformer_setup missing in MLDTrainAutomationLibrary")

    req = _dump_request_class()()
    _set_field_safe(req, "asset_path", asset_path)
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


def _safe_json_load(value: str, fallback: Any) -> Any:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


def _normalize_for_compare(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _normalize_for_compare(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, list):
        return [_normalize_for_compare(v) for v in value]
    if isinstance(value, float):
        return round(value, 8)
    return value


def _load_reference_dump(run_dir: Path) -> Dict[str, Any]:
    path = run_dir / "reports" / "reference_setup_dump.json"
    if not path.exists():
        raise RuntimeError(f"Missing reference setup dump: {path}")

    payload = _safe_json_load(path.read_text(encoding="utf-8"), {})
    if not isinstance(payload, dict):
        raise RuntimeError("Invalid reference setup dump payload")

    status = str(payload.get("status", ""))
    if status != "success":
        raise RuntimeError(f"reference_setup_dump status is not success: {status}")

    outputs = payload.get("outputs", {})
    if not isinstance(outputs, dict):
        raise RuntimeError("reference_setup_dump outputs missing")

    rows = outputs.get("assets", [])
    if not isinstance(rows, list):
        raise RuntimeError("reference_setup_dump outputs.assets must be a list")

    by_key: Dict[str, Dict[str, Any]] = {}
    by_path: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key", ""))
        asset_path = str(row.get("asset_path", ""))
        if key:
            by_key[key] = row
        if asset_path:
            by_path[asset_path] = row

    return {
        "path": str(path.resolve()),
        "raw": payload,
        "by_key": by_key,
        "by_path": by_path,
    }


def _resolve_clone_entry(reference_dump: Dict[str, Any], key: str, asset_path: str) -> Dict[str, Any]:
    by_key = reference_dump.get("by_key", {})
    by_path = reference_dump.get("by_path", {})
    entry = None
    if isinstance(by_key, dict):
        entry = by_key.get(key)
    if entry is None and isinstance(by_path, dict):
        entry = by_path.get(asset_path)
    if not isinstance(entry, dict):
        raise RuntimeError(f"Missing strict_clone dump entry for key={key} asset={asset_path}")
    if not bool(entry.get("success", False)):
        raise RuntimeError(f"strict_clone dump entry failed for key={key}: {entry.get('message', '')}")
    return entry


def _cfg_from_dump(base_cfg: Dict[str, Any], dump_entry: Dict[str, Any]) -> Dict[str, Any]:
    cfg = dict(base_cfg)
    cfg["model_type"] = str(dump_entry.get("model_type", cfg.get("model_type", "")))
    cfg["skeletal_mesh"] = str(dump_entry.get("skeletal_mesh", cfg.get("skeletal_mesh", "")))
    cfg["deformer_graph"] = str(dump_entry.get("deformer_graph", cfg.get("deformer_graph", "")))
    cfg["test_anim_sequence"] = str(dump_entry.get("test_anim", cfg.get("test_anim_sequence", "")))
    cfg["training_input_anims"] = _safe_json_load(str(dump_entry.get("training_input_anims_json", "[]")), [])
    cfg["nnm_section_overrides"] = _safe_json_load(str(dump_entry.get("nnm_sections_json", "[]")), [])
    cfg["model_overrides"] = _safe_json_load(str(dump_entry.get("model_overrides_json", "{}")), {})
    return cfg


def _cfg_from_dump_structural_only(base_cfg: Dict[str, Any], dump_entry: Dict[str, Any]) -> Dict[str, Any]:
    """Apply only structural fields from reference dump, keeping training data paths from base config.

    This is used when ``training_data_source == "pipeline"`` so that structural
    properties (model type, skeletal mesh, deformer graph, test anim, hyper-
    parameters) match the reference, while training_input_anims and
    nnm_section_overrides stay from the pipeline's own config (with {profile}
    templates pointing to pipeline-produced GeomCaches).
    """
    cfg = dict(base_cfg)
    cfg["model_type"] = str(dump_entry.get("model_type", cfg.get("model_type", "")))
    cfg["skeletal_mesh"] = str(dump_entry.get("skeletal_mesh", cfg.get("skeletal_mesh", "")))
    cfg["deformer_graph"] = str(dump_entry.get("deformer_graph", cfg.get("deformer_graph", "")))
    cfg["test_anim_sequence"] = str(dump_entry.get("test_anim", cfg.get("test_anim_sequence", "")))
    # training_input_anims  — intentionally kept from base_cfg (pipeline paths)
    # nnm_section_overrides — intentionally kept from base_cfg (pipeline paths)
    cfg["model_overrides"] = _safe_json_load(str(dump_entry.get("model_overrides_json", "{}")), {})
    return cfg


def _compute_setup_diff(
    reference_row: Dict[str, Any],
    current_row: Dict[str, Any],
    allowed_mismatch_fields: List[str] | None = None,
) -> Dict[str, Any]:
    checks = {
        "model_type": (reference_row.get("model_type", ""), current_row.get("model_type", "")),
        "skeletal_mesh": (reference_row.get("skeletal_mesh", ""), current_row.get("skeletal_mesh", "")),
        "deformer_graph": (reference_row.get("deformer_graph", ""), current_row.get("deformer_graph", "")),
        "test_anim": (reference_row.get("test_anim", ""), current_row.get("test_anim", "")),
        "training_input_anims": (
            _normalize_for_compare(_safe_json_load(str(reference_row.get("training_input_anims_json", "[]")), [])),
            _normalize_for_compare(_safe_json_load(str(current_row.get("training_input_anims_json", "[]")), [])),
        ),
        "nnm_sections": (
            _normalize_for_compare(_safe_json_load(str(reference_row.get("nnm_sections_json", "[]")), [])),
            _normalize_for_compare(_safe_json_load(str(current_row.get("nnm_sections_json", "[]")), [])),
        ),
        "model_overrides": (
            _normalize_for_compare(_safe_json_load(str(reference_row.get("model_overrides_json", "{}")), {})),
            _normalize_for_compare(_safe_json_load(str(current_row.get("model_overrides_json", "{}")), {})),
        ),
    }

    field_results: Dict[str, Dict[str, Any]] = {}
    mismatch_fields: List[str] = []
    expected_mismatch_fields: List[str] = []
    _allowed = set(allowed_mismatch_fields or [])
    for field_name, (lhs, rhs) in checks.items():
        same = lhs == rhs
        field_results[field_name] = {"same": same}
        if not same:
            if field_name in _allowed:
                expected_mismatch_fields.append(field_name)
                field_results[field_name]["allowed_mismatch"] = True
            else:
                mismatch_fields.append(field_name)
            field_results[field_name]["expected"] = lhs
            field_results[field_name]["actual"] = rhs

    return {
        "all_match": len(mismatch_fields) == 0,
        "mismatch_fields": mismatch_fields,
        "expected_mismatch_fields": expected_mismatch_fields,
        "fields": field_results,
    }


def _setup_request_class():
    for name in ("MldSetupRequest", "FMldSetupRequest"):
        cls = getattr(unreal, name, None)
        if cls is not None:
            return cls
    raise RuntimeError("Cannot find MldSetupRequest struct in Unreal Python API")


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


def _ensure_asset(asset_path: str) -> Tuple[Any, str]:
    if asset_exists(asset_path):
        return load_asset_checked(asset_path), "update"

    folder, name = split_asset_path(asset_path)
    if not unreal.EditorAssetLibrary.does_directory_exist(folder):
        unreal.EditorAssetLibrary.make_directory(folder)

    factory = unreal.MLDeformerFactory()
    created = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        asset_name=name,
        package_path=folder,
        asset_class=unreal.MLDeformerAsset,
        factory=factory,
    )
    if created is None:
        raise RuntimeError(f"Failed to create ML Deformer asset: {asset_path}")
    return created, "create"


def _infer_frame_range_from_pose_map(run_dir: Path, profile: str) -> Tuple[int, int] | None:
    pose_map = run_dir / "workspace" / "staging" / profile / "houdini_exports" / "pose_frame_map.csv"
    if not pose_map.exists():
        return None

    sample_count = 0
    with pose_map.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        for row in reader:
            if row:
                sample_count += 1

    if sample_count <= 0:
        return None
    return (0, sample_count - 1)


def _resolve_training_inputs(
    items: List[Dict[str, Any]],
    profile: str,
    inferred_range: Tuple[int, int] | None = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for raw in items:
        item = dict(raw)
        if "geometry_cache_template" in item and not item.get("geometry_cache"):
            item["geometry_cache"] = apply_template(str(item.get("geometry_cache_template") or ""), profile)

        explicit_range = any(k in item for k in ("use_custom_range", "start_frame", "end_frame"))
        if not explicit_range and inferred_range is not None:
            item["use_custom_range"] = True
            item["start_frame"] = int(inferred_range[0])
            item["end_frame"] = int(inferred_range[1])

        out.append(item)
    return out


def _resolve_nnm_sections(items: List[Dict[str, Any]], profile: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for raw in items:
        item = dict(raw)
        if "neighbor_meshes_template" in item and not item.get("neighbor_meshes"):
            item["neighbor_meshes"] = apply_template(str(item.get("neighbor_meshes_template") or ""), profile)
        out.append(item)
    return out


def _build_setup_request(
    cfg: Dict[str, Any],
    profile: str,
    run_dir: Path,
    key: str,
    training_data_source: str = "reference",
):
    req = _setup_request_class()()

    asset_path = str(require_nested(cfg, ("asset_path",)))
    model_type = str(require_nested(cfg, ("model_type",)))
    skeletal_mesh = str(require_nested(cfg, ("skeletal_mesh",)))
    deformer_graph = str(cfg.get("deformer_graph", "") or "")
    test_anim_sequence = str(cfg.get("test_anim_sequence", "") or "")
    raw_overrides = cfg.get("model_overrides", {})
    model_overrides = dict(raw_overrides) if isinstance(raw_overrides, dict) else {}

    # When training_data_source=="pipeline", the GeomCache frame count may differ
    # from the Houdini pose_map sample count (FBX exports use their own frame_end).
    # Skip pose_map inference and let the training use the full GeomCache range.
    if key == "flesh" and training_data_source != "pipeline":
        inferred_range = _infer_frame_range_from_pose_map(run_dir, profile)
    else:
        inferred_range = None
    raw_inputs = cfg.get("training_input_anims", [])
    if not isinstance(raw_inputs, list):
        raw_inputs = []
    raw_sections = cfg.get("nnm_section_overrides", [])
    if not isinstance(raw_sections, list):
        raw_sections = []
    resolved_inputs = _resolve_training_inputs(raw_inputs, profile, inferred_range)
    resolved_sections = _resolve_nnm_sections(raw_sections, profile)

    _set_field_safe(req, "asset_path", asset_path)
    _set_field_safe(req, "model_type", model_type)
    _set_field_safe(req, "skeletal_mesh", skeletal_mesh)
    _set_field_safe(req, "deformer_graph", deformer_graph)
    _set_field_safe(req, "test_anim_sequence", test_anim_sequence)
    _set_field_safe(req, "training_input_anims_json", json.dumps(resolved_inputs, ensure_ascii=True))
    _set_field_safe(req, "model_overrides_json", json.dumps(model_overrides, ensure_ascii=True))
    _set_field_safe(req, "nnm_sections_json", json.dumps(resolved_sections, ensure_ascii=True))
    _set_field_safe(req, "force_switch", True)

    return req, resolved_inputs


def _configure_single_asset(
    name: str,
    cfg: Dict[str, Any],
    profile: str,
    run_dir: Path,
    root_cfg: Dict[str, Any],
    strict_clone_entry: Dict[str, Any] | None = None,
    training_data_source: str = "reference",
) -> Dict[str, Any]:
    applied_source = "reference_override"
    is_pipeline_source = training_data_source == "pipeline"
    if strict_clone_entry is not None:
        if is_pipeline_source:
            cfg = _cfg_from_dump_structural_only(cfg, strict_clone_entry)
            applied_source = "strict_clone_structural_only"
        else:
            cfg = _cfg_from_dump(cfg, strict_clone_entry)
            applied_source = "strict_clone_dump"
    else:
        if is_pipeline_source:
            # Pipeline mode: use base config directly (training inputs already
            # point to pipeline-produced GeomCaches via {profile} templates).
            applied_source = "pipeline_base_config"
        else:
            cfg = _apply_reference_override(root_cfg, name, cfg)
            applied_source = "reference_override"

    asset_path = str(require_nested(cfg, ("asset_path",)))
    model_type = str(require_nested(cfg, ("model_type",)))
    _, lifecycle = _ensure_asset(asset_path)

    lib = getattr(unreal, "MLDTrainAutomationLibrary", None)
    if lib is None:
        raise RuntimeError("MLDTrainAutomationLibrary class missing; cannot configure assets")

    fn = getattr(lib, "setup_deformer_asset", None)
    if fn is None:
        raise RuntimeError("setup_deformer_asset missing in MLDTrainAutomationLibrary")

    req, resolved_inputs = _build_setup_request(cfg, profile, run_dir, name, training_data_source=training_data_source)
    result = fn(req)

    success = bool(_get_field_safe(result, "success", False))
    message = str(_get_field_safe(result, "message", ""))
    warnings = list(_get_field_safe(result, "warnings", []) or [])

    save_asset(asset_path)
    status = "success" if success else "failed"
    return {
        "name": name,
        "asset_path": asset_path,
        "model_type": model_type,
        "lifecycle": lifecycle,
        "applied_source": applied_source,
        "status": status,
        "message": message,
        "warnings": [str(w) for w in warnings],
        "resolved_training_input_anims": resolved_inputs,
    }


def main() -> int:
    ctx = get_context()
    cfg = ctx["config"]
    run_dir = ctx["run_dir"]
    profile = ctx["profile"]

    report = make_report(
        "ue_setup",
        profile,
        {
            "config": str(ctx["config_path"]),
            "run_dir": str(run_dir),
            "profile": profile,
        },
    )

    try:
        assets_cfg = require_nested(cfg, ("ue", "deformer_assets"))
        ordered_keys = list(require_nested(cfg, ("ue", "training_order")))
        baseline_cfg = cfg.get("reference_baseline", {}) if isinstance(cfg.get("reference_baseline"), dict) else {}
        strict_clone_cfg = baseline_cfg.get("strict_clone", {}) if isinstance(baseline_cfg.get("strict_clone"), dict) else {}
        strict_clone_enabled = bool(strict_clone_cfg.get("enabled", False))
        strict_clone_source = str(strict_clone_cfg.get("source", "") or "").strip().lower()

        training_cfg = cfg.get("ue", {}).get("training", {}) if isinstance(cfg.get("ue"), dict) else {}
        if not isinstance(training_cfg, dict):
            training_cfg = {}
        training_data_source = str(training_cfg.get("training_data_source", "reference") or "reference").strip().lower()
        is_pipeline_source = training_data_source == "pipeline"
        # When training uses pipeline-produced data, training_input_anims and
        # nnm_sections may legitimately differ from the reference dump.
        _pipeline_allowed_mismatch = ["training_input_anims", "nnm_sections"] if is_pipeline_source else []

        reference_dump: Dict[str, Any] | None = None
        if strict_clone_enabled:
            if strict_clone_source and strict_clone_source != "refference_deformer_dump":
                raise RuntimeError(f"Unsupported reference_baseline.strict_clone.source: {strict_clone_source}")
            reference_dump = _load_reference_dump(run_dir)

        results: List[Dict[str, Any]] = []
        setup_diffs: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []

        for key in ordered_keys:
            item_cfg = assets_cfg.get(key)
            if not isinstance(item_cfg, dict):
                errors.append({"message": f"Missing deformer_assets entry for '{key}'"})
                continue

            try:
                strict_clone_entry = None
                if strict_clone_enabled and reference_dump is not None:
                    strict_clone_entry = _resolve_clone_entry(
                        reference_dump,
                        key=key,
                        asset_path=str(require_nested(item_cfg, ("asset_path",))),
                    )

                res = _configure_single_asset(key, item_cfg, profile, run_dir, cfg, strict_clone_entry=strict_clone_entry, training_data_source=training_data_source)
                results.append(res)
                if res["status"] != "success":
                    errors.append({"message": f"Asset setup failed: {key}", "detail": res.get("message", "")})
                    continue

                if strict_clone_enabled and strict_clone_entry is not None:
                    current_dump = _call_dump(str(res.get("asset_path", "")))
                    diff = _compute_setup_diff(strict_clone_entry, current_dump, allowed_mismatch_fields=_pipeline_allowed_mismatch)
                    setup_diffs.append(
                        {
                            "key": key,
                            "asset_path": str(res.get("asset_path", "")),
                            "reference": strict_clone_entry,
                            "current": current_dump,
                            "diff": diff,
                        }
                    )

                    if not current_dump.get("success", False):
                        errors.append(
                            {
                                "message": f"strict_clone validation dump failed for {key}",
                                "detail": current_dump.get("message", ""),
                            }
                        )
                    elif not diff.get("all_match", False):
                        errors.append(
                            {
                                "message": f"strict_clone mismatch for {key}",
                                "mismatch_fields": diff.get("mismatch_fields", []),
                            }
                        )
            except Exception as exc:
                errors.append(
                    {
                        "message": f"Exception while configuring asset '{key}': {exc}",
                        "traceback": traceback.format_exc(),
                    }
                )

        setup_diff_report = make_report(
            "setup_diff",
            profile,
            {
                "config": str(ctx["config_path"]),
                "run_dir": str(run_dir),
                "profile": profile,
                "strict_clone_enabled": strict_clone_enabled,
            },
        )
        setup_diff_errors: List[Dict[str, Any]] = []
        if strict_clone_enabled:
            for row in setup_diffs:
                diff = row.get("diff", {})
                if not isinstance(diff, dict):
                    continue
                if not bool(diff.get("all_match", False)):
                    setup_diff_errors.append(
                        {
                            "message": f"strict_clone mismatch: {row.get('key', '')}",
                            "asset_path": row.get("asset_path", ""),
                            "mismatch_fields": diff.get("mismatch_fields", []),
                        }
                    )
        finalize_report(
            setup_diff_report,
            status="success" if not setup_diff_errors else "failed",
            outputs={
                "strict_clone_enabled": strict_clone_enabled,
                "strict_clone_source": strict_clone_source,
                "training_data_source": training_data_source,
                "reference_setup_dump": (
                    str(reference_dump.get("path", "")) if isinstance(reference_dump, dict) else ""
                ),
                "rows": setup_diffs,
            },
            errors=setup_diff_errors,
        )
        write_stage_report(run_dir, "setup_diff", setup_diff_report)

        status = "success" if not errors else "failed"
        finalize_report(
            report,
            status=status,
            outputs={
                "asset_results": results,
                "success_count": len([r for r in results if r.get("status") == "success"]),
                "failure_count": len(errors),
                "training_data_source": training_data_source,
                "strict_clone_enabled": strict_clone_enabled,
                "strict_clone_source": strict_clone_source,
                "reference_setup_dump": (
                    str(reference_dump.get("path", "")) if isinstance(reference_dump, dict) else ""
                ),
                "setup_diff_report": str((run_dir / "reports" / "setup_diff_report.json").resolve()),
            },
            errors=errors,
        )
        write_stage_report(run_dir, "ue_setup", report)
        return 0 if status == "success" else 1

    except Exception as exc:
        finalize_report(
            report,
            status="failed",
            outputs={},
            errors=[{"message": str(exc), "traceback": traceback.format_exc()}],
        )
        write_stage_report(run_dir, "ue_setup", report)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
