#!/usr/bin/env python3
"""Run Houdini REST + PDG cook for smoke/full profile.

This stage now supports two practical output modes:
1) Direct mesh outputs (`*_ML_PDG_tissue_mesh`, `*_ML_PDG_muscle_mesh`)
2) Sim caches (`*_ML_PDG_tissue_sim`, `*_ML_PDG_muscle_sim`)

For stability, if reusable outputs already exist in `$HIP/outputFiles`, the stage can skip
expensive recook and build a deterministic selected sample list for downstream conversion.
"""

from __future__ import annotations

import argparse
import re
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Tuple

from common import (
    ConfigError,
    finalize_report,
    load_config,
    make_report,
    profile_data,
    require_nested,
    stage_report_path,
    timestamp_compact,
    write_json,
)


def _log(msg: str) -> None:
    print(f"[houdini_cook] {msg}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cook Houdini pipeline")
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile", required=True, choices=["smoke", "full"])
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out-prefix", default="")
    parser.add_argument("--input-fbx", default="")
    return parser.parse_args()


def _require_node(hou_mod: Any, node_path: str):
    node = hou_mod.node(node_path)
    if node is None:
        raise RuntimeError(f"Missing HIP node: {node_path}")
    return node


def _set_pose_frames(pose_node: Any, pose_frames: List[int]) -> None:
    frame_parms = [p for p in pose_node.parms() if re.fullmatch(r"intvalue1_\d+", p.name())]
    frame_parms.sort(key=lambda p: int(p.name().split("_")[-1]))
    if not frame_parms:
        raise RuntimeError(f"No pose frame parms found on {pose_node.path()}")

    parent_multiparm = None
    try:
        parent_multiparm = frame_parms[0].parentMultiParm()
    except Exception:
        parent_multiparm = None

    if parent_multiparm is not None:
        parent_multiparm.set(len(pose_frames))

    for i, pose in enumerate(pose_frames, start=1):
        parm = pose_node.parm(f"intvalue1_{i}")
        if parm is None:
            raise RuntimeError(f"Cannot find parm intvalue1_{i} on {pose_node.path()}")
        parm.set(int(pose))


def _cook_pdg(node: Any) -> None:
    last_exc: Exception | None = None

    if hasattr(node, "dirtyAllTasks"):
        try:
            node.dirtyAllTasks(True)
        except Exception:
            pass

    for attempt in (
        lambda: node.cookWorkItems(block=True, tops_only=False),
        lambda: node.cookWorkItems(block=True),
        lambda: node.cookWorkItems(),
        lambda: node.cook(force=True),
    ):
        try:
            attempt()
            return
        except Exception as exc:
            last_exc = exc

    if last_exc is not None:
        raise last_exc


OUTPUT_TOKEN_MAP = {
    "tissue_mesh": "_ML_PDG_tissue_mesh",
    "tissue_sim": "_ML_PDG_tissue_sim",
    "muscle_mesh": "_ML_PDG_muscle_mesh",
    "muscle_sim": "_ML_PDG_muscle_sim",
}


def _read_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _path_sort_key(path: Path) -> Tuple[Any, ...]:
    nums = [int(x) for x in re.findall(r"\d+", path.name)]
    return tuple(nums + [path.name])


def _collect_output_groups(output_root: Path) -> Dict[str, List[Path]]:
    groups: Dict[str, List[Path]] = {key: [] for key in OUTPUT_TOKEN_MAP}

    if not output_root.exists():
        return groups

    for path in output_root.rglob("*"):
        if not path.is_file():
            continue
        haystack = f"{path.parent.as_posix()}/{path.name}"
        for key, token in OUTPUT_TOKEN_MAP.items():
            if token in haystack:
                groups[key].append(path)

    for key in groups:
        groups[key] = sorted(groups[key], key=_path_sort_key)
    return groups


def _filter_groups_by_prefix(groups: Dict[str, List[Path]], out_prefix: str) -> Dict[str, List[Path]]:
    if not out_prefix:
        return {k: list(v) for k, v in groups.items()}
    out: Dict[str, List[Path]] = {}
    for key, paths in groups.items():
        token = OUTPUT_TOKEN_MAP[key]
        out[key] = [p for p in paths if f"{out_prefix}{token}" in f"{p.parent.as_posix()}/{p.name}"]
    return out


def _choose_primary(
    groups: Dict[str, List[Path]],
    preferred_keys: List[str],
) -> Tuple[List[Path], str]:
    for key in preferred_keys:
        items = groups.get(key, [])
        if items:
            return items, key
    return [], "none"


def _select_samples(paths: List[Path], expected_count: int, allow_padding: bool) -> Tuple[List[Path], int]:
    if expected_count <= 0:
        return [], 0
    ordered = sorted(paths, key=_path_sort_key)
    if not ordered:
        return [], 0
    if len(ordered) >= expected_count:
        return ordered[:expected_count], 0

    if not allow_padding:
        return ordered, 0

    selected = list(ordered)
    idx = 0
    while len(selected) < expected_count:
        selected.append(ordered[idx % len(ordered)])
        idx += 1
    padding_count = expected_count - len(ordered)
    return selected, padding_count


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir)
    report_path = stage_report_path(run_dir, "houdini")
    report = make_report(
        stage="houdini",
        profile=args.profile,
        inputs={
            "config": str(Path(args.config).resolve()),
            "run_dir": str(run_dir.resolve()),
            "profile": args.profile,
        },
    )

    try:
        _log(f"start profile={args.profile} run_dir={run_dir}")
        cfg = load_config(args.config)
        _log("config loaded")
        profile_cfg = profile_data(cfg, args.profile)

        pose_frames = [int(x) for x in require_nested(profile_cfg, ("pose_frames",))]
        maxprocs = int(require_nested(profile_cfg, ("maxprocs",)))
        houdini_cfg = dict(cfg.get("houdini", {}))
        reuse_existing_outputs = _read_bool(houdini_cfg.get("reuse_existing_outputs"), True)
        skip_rest_when_reusing = _read_bool(houdini_cfg.get("skip_rest_when_reusing_outputs"), True)
        skip_pdg_when_reusing = _read_bool(houdini_cfg.get("skip_pdg_when_reusing_outputs"), True)
        allow_sample_padding = _read_bool(houdini_cfg.get("allow_sample_padding"), False)
        require_exact_prefix_outputs = _read_bool(
            houdini_cfg.get("require_exact_prefix_outputs"),
            True,
        )

        hip_path = Path(require_nested(cfg, ("paths", "hip_file")))
        if not hip_path.exists():
            raise RuntimeError(f"HIP file is missing: {hip_path}")

        try:
            import hou  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "Cannot import 'hou'. Run this script with hython and configure paths.houdini.hython_exe."
            ) from exc
        _log("hou module imported")

        input_fbx = args.input_fbx or require_nested(cfg, ("defaults", "input_animation_fbx"))
        out_prefix = args.out_prefix or f"{args.profile}_{timestamp_compact()}"

        node_cfg = require_nested(cfg, ("houdini", "nodes"))
        pose_node_path = node_cfg["pose_range"]
        scheduler_node_path = node_cfg["local_scheduler"]
        pdg_anim_node_path = node_cfg["pdg_anim_input"]
        pdg_root_path = node_cfg["pdg_root"]
        rest_nodes = list(node_cfg["rest_caches"])

        _log(f"loading hip: {hip_path}")
        hou.hipFile.load(str(hip_path), suppress_save_prompt=True, ignore_load_warnings=True)
        _log("hip loaded")

        pose_node = _require_node(hou, pose_node_path)
        scheduler_node = _require_node(hou, scheduler_node_path)
        pdg_anim_node = _require_node(hou, pdg_anim_node_path)
        pdg_root_node = _require_node(hou, pdg_root_path)

        out_prefix_parm = pose_node.parm("outPrefix")
        if out_prefix_parm is None:
            raise RuntimeError(f"Missing parm {pose_node_path}.outPrefix")
        out_prefix_parm.set(out_prefix)

        maxproc_parm = scheduler_node.parm("maxprocs")
        if maxproc_parm is None:
            raise RuntimeError(f"Missing parm {scheduler_node_path}.maxprocs")
        maxproc_parm.set(maxprocs)

        fbx_parm = pdg_anim_node.parm("fbxfile")
        if fbx_parm is None:
            raise RuntimeError(f"Missing parm {pdg_anim_node_path}.fbxfile")
        fbx_parm.set(f"$HIP/inputFiles/skeleton_anim/{input_fbx}")

        output_root = Path(hou.expandString("$HIP")) / "outputFiles"
        pre_groups_all = _collect_output_groups(output_root)
        pre_tissue_any = len(pre_groups_all["tissue_mesh"]) + len(pre_groups_all["tissue_sim"])
        pre_muscle_any = len(pre_groups_all["muscle_mesh"]) + len(pre_groups_all["muscle_sim"])
        can_reuse = reuse_existing_outputs and pre_tissue_any > 0 and pre_muscle_any > 0

        _set_pose_frames(pose_node, pose_frames)

        errors: List[Dict[str, Any]] = []
        warnings: List[str] = []
        rest_durations: Dict[str, float] = {}
        pdg_duration = 0.0
        did_cook_pdg = False

        if can_reuse and skip_rest_when_reusing:
            warnings.append(
                "Reusing existing Houdini outputs. REST caches were skipped by configuration."
            )
            _log("rest cook skipped (reuse enabled)")
        else:
            for rest_path in rest_nodes:
                _log(f"rest cook start: {rest_path}")
                rest_node = _require_node(hou, rest_path)
                start = time.perf_counter()
                try:
                    rest_node.cook(force=True)
                    rest_durations[rest_path] = round(time.perf_counter() - start, 3)
                    _log(f"rest cook done: {rest_path} ({rest_durations[rest_path]}s)")
                except Exception as exc:
                    if can_reuse:
                        warnings.append(f"REST cook failed but reuse is enabled ({rest_path}): {exc}")
                        rest_durations[rest_path] = round(time.perf_counter() - start, 3)
                        _log(f"rest cook failed (reuse fallback): {rest_path} ({rest_durations[rest_path]}s) {exc}")
                    else:
                        raise

        if can_reuse and skip_pdg_when_reusing:
            warnings.append(
                "Reusing existing Houdini outputs. PDG cook was skipped by configuration."
            )
            _log("pdg cook skipped (reuse enabled)")
        else:
            _log("pdg cook start")
            pdg_start = time.perf_counter()
            try:
                _cook_pdg(pdg_root_node)
                pdg_duration = round(time.perf_counter() - pdg_start, 3)
                did_cook_pdg = True
                _log(f"pdg cook done ({pdg_duration}s)")
            except Exception as exc:
                pdg_duration = round(time.perf_counter() - pdg_start, 3)
                if can_reuse:
                    warnings.append(f"PDG cook failed but reuse is enabled: {exc}")
                    _log(f"pdg cook failed (reuse fallback) ({pdg_duration}s) {exc}")
                else:
                    raise

        output_groups_all = _collect_output_groups(output_root)
        output_groups_exact = _filter_groups_by_prefix(output_groups_all, out_prefix)

        tissue_exact, tissue_exact_kind = _choose_primary(
            output_groups_exact,
            ["tissue_mesh", "tissue_sim"],
        )
        muscle_exact, muscle_exact_kind = _choose_primary(
            output_groups_exact,
            ["muscle_mesh", "muscle_sim"],
        )
        tissue_any, tissue_any_kind = _choose_primary(
            output_groups_all,
            ["tissue_mesh", "tissue_sim"],
        )
        muscle_any, muscle_any_kind = _choose_primary(
            output_groups_all,
            ["muscle_mesh", "muscle_sim"],
        )

        if require_exact_prefix_outputs:
            tissue_source = tissue_exact
            tissue_source_kind = f"exact_prefix:{tissue_exact_kind}"
            muscle_source = muscle_exact
            muscle_source_kind = f"exact_prefix:{muscle_exact_kind}"
        else:
            if tissue_exact:
                tissue_source = tissue_exact
                tissue_source_kind = f"exact_prefix:{tissue_exact_kind}"
            else:
                tissue_source = tissue_any
                tissue_source_kind = f"fallback_any_prefix:{tissue_any_kind}"

            if muscle_exact:
                muscle_source = muscle_exact
                muscle_source_kind = f"exact_prefix:{muscle_exact_kind}"
            else:
                muscle_source = muscle_any
                muscle_source_kind = f"fallback_any_prefix:{muscle_any_kind}"

        expected_count = len(pose_frames)
        tissue_selected, tissue_padding = _select_samples(
            tissue_source,
            expected_count,
            allow_sample_padding,
        )
        muscle_selected, muscle_padding = _select_samples(
            muscle_source,
            expected_count,
            allow_sample_padding,
        )
        tissue_missing_before_padding = max(0, expected_count - len(tissue_source))
        muscle_missing_before_padding = max(0, expected_count - len(muscle_source))

        run_manifest = {
            "profile": args.profile,
            "hip_file": str(hip_path),
            "output_root": str(output_root.resolve()),
            "out_prefix": out_prefix,
            "input_animation_fbx": input_fbx,
            "pose_frames": pose_frames,
            "expected_samples": expected_count,
            "maxprocs": maxprocs,
            "cook": {
                "reuse_existing_outputs": can_reuse,
                "did_cook_pdg": did_cook_pdg,
                "skip_rest_when_reusing_outputs": skip_rest_when_reusing,
                "skip_pdg_when_reusing_outputs": skip_pdg_when_reusing,
                "allow_sample_padding": allow_sample_padding,
                "require_exact_prefix_outputs": require_exact_prefix_outputs,
            },
            "durations_sec": {
                "rest_nodes": rest_durations,
                "pdg_cook": pdg_duration,
            },
            "detected_outputs": {
                "exact_prefix": {
                    key: {
                        "count": len(output_groups_exact[key]),
                        "files": [str(p.resolve()) for p in output_groups_exact[key]],
                    }
                    for key in output_groups_exact
                },
                "all_prefixes": {
                    key: {
                        "count": len(output_groups_all[key]),
                        "files": [str(p.resolve()) for p in output_groups_all[key]],
                    }
                    for key in output_groups_all
                },
            },
            "selected_outputs": {
                "tissue_source_kind": tissue_source_kind,
                "muscle_source_kind": muscle_source_kind,
                "tissue_training_files": [str(p.resolve()) for p in tissue_selected],
                "muscle_debug_files": [str(p.resolve()) for p in muscle_selected],
                "tissue_selected_count": len(tissue_selected),
                "muscle_selected_count": len(muscle_selected),
                "tissue_padding_count": tissue_padding,
                "muscle_padding_count": muscle_padding,
            },
            "failed_frames": {
                "tissue_missing_before_padding": tissue_missing_before_padding,
                "muscle_missing_before_padding": muscle_missing_before_padding,
            },
        }

        manifest_path = run_dir / "manifests" / "run_manifest.json"
        write_json(manifest_path, run_manifest)

        status = "success"
        if len(tissue_selected) != expected_count or len(muscle_selected) != expected_count:
            status = "failed"
            errors.append(
                {
                    "message": "Unable to build selected output sample sets",
                    "expected_count": expected_count,
                    "tissue_selected_count": len(tissue_selected),
                    "muscle_selected_count": len(muscle_selected),
                    "tissue_detected_count": len(tissue_source),
                    "muscle_detected_count": len(muscle_source),
                    "tissue_source_kind": tissue_source_kind,
                    "muscle_source_kind": muscle_source_kind,
                    "allow_sample_padding": allow_sample_padding,
                    "require_exact_prefix_outputs": require_exact_prefix_outputs,
                }
            )

        for message in warnings:
            errors.append({"message": message, "severity": "warning"})

        finalize_report(
            report,
            status=status,
            outputs={
                "run_manifest": str(manifest_path.resolve()),
                "out_prefix": out_prefix,
                "expected_count": expected_count,
                "tissue_selected_count": len(tissue_selected),
                "muscle_selected_count": len(muscle_selected),
                "tissue_source_kind": tissue_source_kind,
                "muscle_source_kind": muscle_source_kind,
                "tissue_padding_count": tissue_padding,
                "muscle_padding_count": muscle_padding,
                "did_cook_pdg": did_cook_pdg,
                "output_root": str(output_root.resolve()),
            },
            errors=errors,
        )
        write_json(report_path, report)
        _log(f"done status={status} report={report_path}")
        return 0 if status == "success" else 1

    except (ConfigError, RuntimeError, Exception) as exc:
        _log(f"failed: {exc}")
        finalize_report(
            report,
            status="failed",
            outputs={},
            errors=[
                {
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                }
            ],
        )
        write_json(report_path, report)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
