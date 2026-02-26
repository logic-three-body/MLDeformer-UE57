#!/usr/bin/env python3
"""Run UE in reference project and dump deformer setup JSON via C++ bridge."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import traceback
from pathlib import Path
from typing import Any, Dict, List

from common import finalize_report, load_config, make_report, require_nested, stage_report_path, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dump reference deformer setup")
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile", required=True, choices=["smoke", "full"])
    parser.add_argument("--run-dir", required=True)
    return parser.parse_args()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_path(base: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def _resolve_editor_cmd(ue_editor_exe: str) -> Path:
    exe_path = Path(ue_editor_exe)
    if not exe_path.exists():
        raise RuntimeError(f"UE editor executable not found: {exe_path}")
    if exe_path.name.lower() == "unrealeditor-cmd.exe":
        return exe_path
    candidate = exe_path.with_name("UnrealEditor-Cmd.exe")
    return candidate if candidate.exists() else exe_path


def _tail(path: Path, lines: int = 120) -> List[str]:
    if not path.exists():
        return []
    data = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return data[-lines:]


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir)
    stage_name = "reference_setup_dump"
    stage_report = stage_report_path(run_dir, stage_name)
    report = make_report(
        stage=stage_name,
        profile=args.profile,
        inputs={
            "config": str(Path(args.config).resolve()),
            "run_dir": str(run_dir.resolve()),
            "profile": args.profile,
        },
    )

    try:
        cfg = load_config(args.config)
        baseline_cfg = require_nested(cfg, ("reference_baseline",))
        strict_clone_cfg = baseline_cfg.get("strict_clone", {}) if isinstance(baseline_cfg.get("strict_clone"), dict) else {}
        enabled = bool(strict_clone_cfg.get("enabled", False))
        source = str(strict_clone_cfg.get("source", "") or "").strip().lower()

        if not enabled:
            finalize_report(
                report,
                status="success",
                outputs={"enabled": False, "skipped": True, "reason": "reference_baseline.strict_clone.enabled=false"},
                errors=[],
            )
            write_json(stage_report, report)
            return 0

        if source and source != "refference_deformer_dump":
            raise RuntimeError(f"Unsupported reference_baseline.strict_clone.source: {source}")

        project_root = _project_root()
        editor_cmd = _resolve_editor_cmd(str(require_nested(cfg, ("paths", "ue_editor_exe"))))
        reference_uproject = _resolve_path(project_root, str(require_nested(baseline_cfg, ("reference_uproject",))))
        source_uproject = _resolve_path(project_root, str(require_nested(cfg, ("paths", "uproject"))))
        if not reference_uproject.exists():
            raise RuntimeError(f"reference uproject not found: {reference_uproject}")

        ue_dump_script = (Path(__file__).resolve().parent / "ue_dump_setup.py").resolve()
        if not ue_dump_script.exists():
            raise RuntimeError(f"UE dump script missing: {ue_dump_script}")

        dump_out = (run_dir / "reports" / "reference_setup_dump.json").resolve()
        stdout_path = run_dir / "reports" / "logs" / "reference_setup_dump.stdout.log"
        stderr_path = run_dir / "reports" / "logs" / "reference_setup_dump.stderr.log"
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        dump_out.parent.mkdir(parents=True, exist_ok=True)
        dump_out.unlink(missing_ok=True)

        env = os.environ.copy()
        env["HOU2UE_CONFIG"] = str(Path(args.config).resolve())
        env["HOU2UE_PROFILE"] = args.profile
        env["HOU2UE_RUN_DIR"] = str(run_dir.resolve())
        env["HOU2UE_DUMP_KIND"] = "reference"
        env["HOU2UE_DUMP_OUTPUT"] = str(dump_out)

        def _run_dump(target_uproject: Path) -> Dict[str, Any]:
            cmd = [
                str(editor_cmd),
                str(target_uproject),
                f"-ExecutePythonScript={ue_dump_script.as_posix()}",
                "-unattended",
                "-nop4",
                "-nosplash",
                "-NoSound",
                "-stdout",
                "-FullStdOutLogOutput",
                "-log",
            ]

            with stdout_path.open("w", encoding="utf-8", errors="ignore") as out_handle, stderr_path.open(
                "w", encoding="utf-8", errors="ignore"
            ) as err_handle:
                proc = subprocess.run(
                    cmd,
                    env=env,
                    stdout=out_handle,
                    stderr=err_handle,
                    cwd=str(project_root),
                    timeout=60 * 60,
                    check=False,
                )

            dump_payload: Dict[str, Any] = {}
            if dump_out.exists():
                try:
                    dump_payload = json.loads(dump_out.read_text(encoding="utf-8"))
                except Exception:
                    dump_payload = {}
            dump_status = str(dump_payload.get("status", "missing")) if isinstance(dump_payload, dict) else "missing"
            return {
                "cmd": cmd,
                "returncode": int(proc.returncode),
                "dump_payload": dump_payload,
                "dump_status": dump_status,
                "success": int(proc.returncode) == 0 and dump_status == "success",
                "uproject": str(target_uproject.resolve()),
            }

        run_result = _run_dump(reference_uproject)
        fallback_used = False
        fallback_reason = ""
        if (
            not run_result["success"]
            and source_uproject.exists()
            and source_uproject.resolve() != reference_uproject.resolve()
        ):
            fallback_used = True
            fallback_reason = "reference_project_missing_editor_tools_module_fallback_to_source_project"
            run_result = _run_dump(source_uproject)

        dump_status = str(run_result.get("dump_status", "missing"))
        success = bool(run_result.get("success", False))

        errors: List[Dict[str, Any]] = []
        if not success:
            errors.append(
                {
                    "message": "reference setup dump failed",
                    "exit_code": int(run_result.get("returncode", -1)),
                    "dump_status": dump_status,
                    "stdout_tail": _tail(stdout_path, 80),
                    "stderr_tail": _tail(stderr_path, 80),
                }
            )

        finalize_report(
            report,
            status="success" if success else "failed",
            outputs={
                "enabled": True,
                "source": "refference_deformer_dump",
                "reference_uproject": str(reference_uproject.resolve()),
                "capture_uproject": str(run_result.get("uproject", "")),
                "dump_output": str(dump_out),
                "dump_status": dump_status,
                "fallback_used": fallback_used,
                "fallback_reason": fallback_reason,
                "stdout_log": str(stdout_path.resolve()),
                "stderr_log": str(stderr_path.resolve()),
                "command": run_result.get("cmd", []),
            },
            errors=errors,
        )
        write_json(stage_report, report)
        return 0 if success else 1

    except Exception as exc:
        finalize_report(
            report,
            status="failed",
            outputs={},
            errors=[{"message": str(exc), "traceback": traceback.format_exc()}],
        )
        write_json(stage_report, report)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
