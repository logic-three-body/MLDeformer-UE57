#!/usr/bin/env python3
"""Preflight checks + HIP structure extraction."""

from __future__ import annotations

import argparse
import re
import traceback
from pathlib import Path
from typing import Any, Dict, List

from common import (
    ConfigError,
    finalize_report,
    load_config,
    make_report,
    require_nested,
    stage_report_path,
    write_json,
)


def _require_node(hou_mod: Any, node_path: str):
    node = hou_mod.node(node_path)
    if node is None:
        raise RuntimeError(f"Missing HIP node: {node_path}")
    return node


def _require_parm(node: Any, parm_name: str):
    parm = node.parm(parm_name)
    if parm is None:
        raise RuntimeError(f"Missing HIP parm: {node.path()}.{parm_name}")
    return parm


def _parm_to_string(parm: Any) -> str:
    try:
        return parm.unexpandedString()
    except Exception:
        pass
    try:
        return parm.evalAsString()
    except Exception:
        pass
    return str(parm.eval())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse HIP structure and emit hip_manifest.json")
    parser.add_argument("--config", required=True, help="Path to pipeline config (JSON-compatible YAML)")
    parser.add_argument("--profile", required=True, choices=["smoke", "full"])
    parser.add_argument("--run-dir", required=True, help="Run output directory")
    parser.add_argument("--manifest-path", default="", help="Optional override for hip_manifest.json path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir)
    report_path = stage_report_path(run_dir, "preflight")
    report = make_report(
        stage="preflight",
        profile=args.profile,
        inputs={
            "config": str(Path(args.config).resolve()),
            "run_dir": str(run_dir.resolve()),
        },
    )

    try:
        cfg = load_config(args.config)
        hip_path = Path(require_nested(cfg, ("paths", "hip_file")))
        if not hip_path.exists():
            raise RuntimeError(f"HIP file is missing: {hip_path}")

        try:
            import hou  # type: ignore
        except Exception as exc:  # pragma: no cover - only when not in hython
            raise RuntimeError(
                "Cannot import 'hou'. Run this script with hython and configure paths.houdini.hython_exe."
            ) from exc

        hou.hipFile.load(str(hip_path), suppress_save_prompt=True, ignore_load_warnings=True)

        node_cfg = require_nested(cfg, ("houdini", "nodes"))
        pose_node = _require_node(hou, node_cfg["pose_range"])
        scheduler_node = _require_node(hou, node_cfg["local_scheduler"])
        pdg_anim_node = _require_node(hou, node_cfg["pdg_anim_input"])
        pdg_root_node = _require_node(hou, node_cfg["pdg_root"])

        fbx_parm = _require_parm(pdg_anim_node, "fbxfile")
        out_prefix_parm = _require_parm(pose_node, "outPrefix")
        maxprocs_parm = _require_parm(scheduler_node, "maxprocs")

        pose_parms = [
            parm for parm in pose_node.parms() if re.fullmatch(r"intvalue1_\d+", parm.name())
        ]
        if not pose_parms:
            raise RuntimeError(
                f"No pose parm found on {pose_node.path()}. Expected intvalue1_<index> parms."
            )
        pose_parms.sort(key=lambda p: int(p.name().split("_")[-1]))
        pose_values = [int(parm.eval()) for parm in pose_parms]

        mesh_outputs: Dict[str, str] = {}
        all_nodes = [pdg_root_node] + list(pdg_root_node.allSubChildren())
        for node in all_nodes:
            sop_parm = node.parm("sopoutput")
            if sop_parm is None:
                continue
            if "_mesh" in node.path() or node.path().endswith("mesh"):
                mesh_outputs[node.path()] = _parm_to_string(sop_parm)

        if not mesh_outputs:
            raise RuntimeError(
                "Missing required tasks/pdg_sim/*_mesh.sopoutput parameters (no *_mesh node with sopoutput found)."
            )

        manifest = {
            "hip_file": str(hip_path),
            "houdini_version": str(hou.applicationVersionString()),
            "required": {
                "obj/import_geo/pdg_anim_for_training.fbxfile": _parm_to_string(fbx_parm),
                "tasks/pdg_sim/pose_range.outPrefix": _parm_to_string(out_prefix_parm),
                "tasks/pdg_sim/pose_range.intvalue1_*": pose_values,
                "tasks/pdg_sim/localscheduler.maxprocs": int(maxprocs_parm.eval()),
                "tasks/pdg_sim/*_mesh.sopoutput": mesh_outputs,
            },
            "summary": {
                "pose_count": len(pose_values),
                "pose_frames": pose_values,
                "pdg_mesh_nodes": sorted(mesh_outputs.keys()),
            },
        }

        manifest_path = (
            Path(args.manifest_path)
            if args.manifest_path
            else (run_dir / "manifests" / "hip_manifest.json")
        )
        write_json(manifest_path, manifest)

        finalize_report(
            report,
            status="success",
            outputs={
                "hip_manifest": str(manifest_path.resolve()),
                "pose_count": len(pose_values),
                "default_out_prefix": _parm_to_string(out_prefix_parm),
                "default_maxprocs": int(maxprocs_parm.eval()),
                "default_anim_fbx": _parm_to_string(fbx_parm),
                "mesh_output_nodes": sorted(mesh_outputs.keys()),
            },
            errors=[],
        )
        write_json(report_path, report)
        return 0

    except (ConfigError, RuntimeError, Exception) as exc:
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
