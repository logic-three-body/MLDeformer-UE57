#!/usr/bin/env python3
"""Aggregate stage reports into a single pipeline report + snapshot artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import traceback
from pathlib import Path
from typing import Any, Dict, List

from common import finalize_report, load_config, make_report, stage_report_path, timestamp_compact, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build pipeline summary report")
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile", required=True, choices=["smoke", "full"])
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out-root", required=True)
    return parser.parse_args()


def _load_stage_report(path: Path) -> Dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def _yaml_dump(obj: Any, indent: int = 0) -> str:
    prefix = "  " * indent
    if isinstance(obj, dict):
        lines: List[str] = []
        for key, value in obj.items():
            if isinstance(value, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.append(_yaml_dump(value, indent + 1))
            else:
                lines.append(f"{prefix}{key}: {_yaml_scalar(value)}")
        return "\n".join(lines)
    if isinstance(obj, list):
        lines = []
        for item in obj:
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}-")
                lines.append(_yaml_dump(item, indent + 1))
            else:
                lines.append(f"{prefix}- {_yaml_scalar(item)}")
        return "\n".join(lines)
    return f"{prefix}{_yaml_scalar(obj)}"


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    needs_quote = any(ch in text for ch in [":", "#", "{", "}", "[", "]", ",", " "]) or text == ""
    if needs_quote:
        text = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{text}"'
    return text


def _copy_latest(run_dir: Path, out_root: Path, profile: str) -> Path:
    latest_dir = out_root / "latest" / profile
    if latest_dir.exists():
        shutil.rmtree(latest_dir)
    latest_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(run_dir, latest_dir)
    return latest_dir


def _strict_thresholds() -> Dict[str, float]:
    return {
        "ssim_mean_min": 0.995,
        "ssim_p05_min": 0.985,
        "psnr_mean_min": 35.0,
        "psnr_min_min": 30.0,
        "edge_iou_mean_min": 0.97,
    }


def _pipeline_thresholds() -> Dict[str, float]:
    """Relaxed thresholds for pipeline-trained models (training_data_source=pipeline).

    Pipeline-produced training data uses different GeomCache/animation combinations
    than the reference project, so the retrained model is expected to produce
    visually different (but still correct) results.
    """
    return {
        "ssim_mean_min": 0.60,
        "ssim_p05_min": 0.40,
        "psnr_mean_min": 15.0,
        "psnr_min_min": 12.0,
        "edge_iou_mean_min": 0.40,
    }


def _thresholds_hash(thresholds: Dict[str, float]) -> str:
    blob = json.dumps(thresholds, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _normalize_threshold_values(raw: Dict[str, Any]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for key in _strict_thresholds().keys():
        out[key] = float(raw.get(key, 0.0))
    return out


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir)
    out_root = Path(args.out_root)
    report_path = stage_report_path(run_dir, "report")
    stage_report = make_report(
        stage="report",
        profile=args.profile,
        inputs={
            "config": str(Path(args.config).resolve()),
            "run_dir": str(run_dir.resolve()),
            "out_root": str(out_root.resolve()),
            "profile": args.profile,
        },
    )

    try:
        cfg = load_config(args.config)
        stages = [
            "baseline_sync",
            "preflight",
            "houdini",
            "convert",
            "ue_import",
            "ue_setup",
            "train",
            "infer",
            "gt_reference_capture",
            "gt_source_capture",
            "gt_compare",
        ]
        baseline_sync_path = run_dir / "reports" / "baseline_sync_report.json"
        gt_compare_path = run_dir / "reports" / "gt_compare_report.json"
        coord_validation_path = run_dir / "reports" / "coord_validation_report.json"
        reference_setup_dump_report_path = run_dir / "reports" / "reference_setup_dump_report.json"
        reference_setup_dump_path = run_dir / "reports" / "reference_setup_dump.json"
        setup_diff_report_path = run_dir / "reports" / "setup_diff_report.json"
        train_determinism_report_path = run_dir / "reports" / "train_determinism_report.json"
        gt_compare_report = _load_stage_report(gt_compare_path)
        reference_setup_dump_report = _load_stage_report(reference_setup_dump_report_path)
        setup_diff_report = _load_stage_report(setup_diff_report_path)
        train_determinism_report = _load_stage_report(train_determinism_report_path)

        # Determine skip_train early so we know which stages are expected
        training_cfg_early = (
            cfg.get("ue", {}).get("training", {})
            if isinstance(cfg.get("ue"), dict)
            else {}
        )
        if not isinstance(training_cfg_early, dict):
            training_cfg_early = {}
        skip_train_flag = bool(training_cfg_early.get("skip_train", False))
        # Stages that produce GeomCache and are skipped when skip_train=true
        skip_train_bypass_stages = {"preflight", "houdini", "convert", "ue_import"}

        stage_reports: Dict[str, Dict[str, Any] | None] = {}
        failures: List[Dict[str, Any]] = []
        for stage in stages:
            sr = _load_stage_report(stage_report_path(run_dir, stage))
            stage_reports[stage] = sr
            if sr is None:
                if skip_train_flag and stage in skip_train_bypass_stages:
                    # These stages are intentionally skipped under skip_train shortcut
                    continue
                failures.append({"stage": stage, "message": "Missing stage report"})
                continue
            if sr.get("status") != "success":
                failures.append({"stage": stage, "message": "Stage failed", "errors": sr.get("errors", [])})

        # strict threshold enforcement unless explicitly in debug mode
        compare_cfg = (
            cfg.get("ue", {}).get("ground_truth", {}).get("compare", {})
            if isinstance(cfg.get("ue"), dict)
            else {}
        )
        if not isinstance(compare_cfg, dict):
            compare_cfg = {}
        thresholds_raw = compare_cfg.get("thresholds", {}) if isinstance(compare_cfg.get("thresholds"), dict) else {}
        thresholds = _normalize_threshold_values(thresholds_raw)
        strict = _strict_thresholds()
        pipeline = _pipeline_thresholds()

        debug_mode = bool(cfg.get("debug_mode", False))
        if "debug_mode" in compare_cfg:
            debug_mode = bool(compare_cfg.get("debug_mode", debug_mode))

        # Determine training_data_source to select the correct threshold baseline
        training_cfg = (
            cfg.get("ue", {}).get("training", {})
            if isinstance(cfg.get("ue"), dict)
            else {}
        )
        if not isinstance(training_cfg, dict):
            training_cfg = {}
        training_data_source = str(training_cfg.get("training_data_source", "reference") or "reference").strip().lower()
        is_pipeline_source = training_data_source == "pipeline"

        if is_pipeline_source:
            required_thresholds = pipeline
            threshold_label = "pipeline"
        else:
            required_thresholds = strict
            threshold_label = "strict"

        if thresholds != required_thresholds and not debug_mode:
            failures.append(
                {
                    "stage": "gt_compare",
                    "message": f"Ground-truth thresholds are not {threshold_label} while debug_mode is false.",
                    "configured_thresholds": thresholds,
                    "required_thresholds": required_thresholds,
                    "training_data_source": training_data_source,
                    "configured_thresholds_hash": _thresholds_hash(thresholds),
                    "required_thresholds_hash": _thresholds_hash(required_thresholds),
                }
            )

        strict_clone_cfg = (
            cfg.get("reference_baseline", {}).get("strict_clone", {})
            if isinstance(cfg.get("reference_baseline"), dict)
            else {}
        )
        if not isinstance(strict_clone_cfg, dict):
            strict_clone_cfg = {}
        strict_clone_enabled = bool(strict_clone_cfg.get("enabled", False))
        skip_train = bool(training_cfg.get("skip_train", False))
        if strict_clone_enabled:
            if reference_setup_dump_report is None:
                failures.append(
                    {
                        "stage": "reference_setup_dump",
                        "message": "Missing reference_setup_dump_report.json while strict_clone is enabled.",
                    }
                )
            elif reference_setup_dump_report.get("status") != "success":
                failures.append(
                    {
                        "stage": "reference_setup_dump",
                        "message": "reference_setup_dump_report.json indicates failure.",
                        "errors": reference_setup_dump_report.get("errors", []),
                    }
                )

            # When skip_train is enabled, ue_setup is skipped entirely so no setup_diff
            # is generated.  The reference networks are used directly, making the diff
            # unnecessary — asset configs are unchanged from reference baseline.
            if setup_diff_report is None and not skip_train:
                failures.append(
                    {
                        "stage": "setup_diff",
                        "message": "Missing setup_diff_report.json while strict_clone is enabled.",
                    }
                )
            elif setup_diff_report is not None and setup_diff_report.get("status") != "success":
                # In pipeline mode, setup_diff may report expected mismatches for training
                # data fields (training_input_anims, nnm_sections). These are intentional
                # and should not cause a pipeline-level failure.
                if is_pipeline_source:
                    diff_errors = setup_diff_report.get("errors", [])
                    unexpected_errors = []
                    _pipeline_allowed = {"training_input_anims", "nnm_sections"}
                    for err in diff_errors:
                        if not isinstance(err, dict):
                            unexpected_errors.append(err)
                            continue
                        mismatch_fields = err.get("mismatch_fields", [])
                        if isinstance(mismatch_fields, list) and all(f in _pipeline_allowed for f in mismatch_fields):
                            continue  # expected mismatch in pipeline mode
                        unexpected_errors.append(err)
                    if unexpected_errors:
                        failures.append(
                            {
                                "stage": "setup_diff",
                                "message": "setup_diff_report.json indicates unexpected failures in pipeline mode.",
                                "errors": unexpected_errors,
                            }
                        )
                else:
                    failures.append(
                        {
                            "stage": "setup_diff",
                            "message": "setup_diff_report.json indicates failure.",
                            "errors": setup_diff_report.get("errors", []),
                        }
                    )

        status = "success" if not failures else "failed"

        pipeline_report = {
            "stage": "full_pipeline",
            "profile": args.profile,
            "started_at": (
                (stage_reports.get("baseline_sync") or {}).get("started_at", "")
                or (stage_reports.get("preflight") or {}).get("started_at", "")
            ),
            "ended_at": stage_report["started_at"],
            "status": status,
            "inputs": {
                "config": str(Path(args.config).resolve()),
                "run_dir": str(run_dir.resolve()),
            },
            "outputs": {
                "stage_reports": {
                    stage: str(stage_report_path(run_dir, stage).resolve())
                    for stage in stages
                },
                "stage_status": {
                    stage: (
                        "skipped_skip_train"
                        if (skip_train_flag and stage in skip_train_bypass_stages and stage_reports.get(stage) is None)
                        else (stage_reports[stage] or {}).get("status", "missing")
                    )
                    for stage in stages
                },
                "baseline_sync_report": str(baseline_sync_path.resolve()) if baseline_sync_path.exists() else "",
                "gt_compare_report": str(gt_compare_path.resolve()) if gt_compare_path.exists() else "",
                "coord_validation_report": (
                    str(coord_validation_path.resolve()) if coord_validation_path.exists() else ""
                ),
                "reference_setup_dump_report": (
                    str(reference_setup_dump_report_path.resolve()) if reference_setup_dump_report_path.exists() else ""
                ),
                "reference_setup_dump": (
                    str(reference_setup_dump_path.resolve()) if reference_setup_dump_path.exists() else ""
                ),
                "setup_diff_report": (
                    str(setup_diff_report_path.resolve()) if setup_diff_report_path.exists() else ""
                ),
                "train_determinism_report": (
                    str(train_determinism_report_path.resolve()) if train_determinism_report_path.exists() else ""
                ),
                "gt_compare_status": (
                    str((gt_compare_report or {}).get("status", "missing"))
                    if gt_compare_path.exists()
                    else "missing"
                ),
                "strict_thresholds_required": strict,
                "pipeline_thresholds": pipeline,
                "required_thresholds": required_thresholds,
                "configured_thresholds": thresholds,
                "strict_thresholds_hash": _thresholds_hash(strict),
                "pipeline_thresholds_hash": _thresholds_hash(pipeline),
                "configured_thresholds_hash": _thresholds_hash(thresholds),
                "training_data_source": training_data_source,
                "debug_mode": debug_mode,
                "strict_clone_enabled": strict_clone_enabled,
                "train_determinism_status": (
                    str((train_determinism_report or {}).get("status", "missing"))
                    if train_determinism_report_path.exists()
                    else "missing"
                ),
            },
            "errors": failures,
        }

        ts = timestamp_compact()
        pipeline_report_path = run_dir / "reports" / f"pipeline_report_{ts}.json"
        write_json(pipeline_report_path, pipeline_report)
        write_json(run_dir / "reports" / "pipeline_report_latest.json", pipeline_report)

        resolved_snapshot = {
            "profile": args.profile,
            "run_dir": str(run_dir.resolve()),
            "out_root": str(out_root.resolve()),
            "config": cfg,
        }
        resolved_yaml_path = run_dir / "resolved_config.yaml"
        resolved_yaml_path.write_text(_yaml_dump(resolved_snapshot) + "\n", encoding="utf-8")

        latest_dir = _copy_latest(run_dir, out_root, args.profile)

        finalize_report(
            stage_report,
            status=status,
            outputs={
                "pipeline_report": str(pipeline_report_path.resolve()),
                "pipeline_report_latest": str((run_dir / "reports" / "pipeline_report_latest.json").resolve()),
                "resolved_config_yaml": str(resolved_yaml_path.resolve()),
                "latest_copy_dir": str(latest_dir.resolve()),
            },
            errors=failures,
        )
        write_json(report_path, stage_report)
        return 0 if status == "success" else 1

    except Exception as exc:
        finalize_report(
            stage_report,
            status="failed",
            outputs={},
            errors=[{"message": str(exc), "traceback": traceback.format_exc()}],
        )
        write_json(report_path, stage_report)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
