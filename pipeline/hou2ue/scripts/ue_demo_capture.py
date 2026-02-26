#!/usr/bin/env python3
# ARCHIVED: This script has been removed from the pipeline (2026-02-26).
# The ue_demo stage produced meaningless artifacts: wrong DemoRoom cameras, warmup_frames=0
# (ML Deformer inactive), anomalously fast renders (~3s/job), non-unique filenames (.0000.png),
# and was non-gating (excluded from build_report.py stages list).
# Quality is validated by gt_source_capture + gt_compare (SSIM=0.9997). See git history.
"""Capture UE runtime demo image sequences for infer-stage proof artifacts."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
import traceback
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Tuple

from common import finalize_report, load_config, make_report, require_nested, stage_report_path, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture UE infer demo image sequences")
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile", required=True, choices=["smoke", "full"])
    parser.add_argument("--run-dir", required=True)
    return parser.parse_args()


def _script_project_root() -> Path:
    # <project>/pipeline/hou2ue/scripts/ue_demo_capture.py
    return Path(__file__).resolve().parents[3]


def _resolve_path(base: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (base / path).resolve()


def _resolve_editor_cmd(ue_editor_exe: str) -> Path:
    exe_path = Path(ue_editor_exe)
    if not exe_path.exists():
        raise RuntimeError(f"UE editor executable not found: {exe_path}")

    lower_name = exe_path.name.lower()
    if lower_name == "unrealeditor-cmd.exe":
        return exe_path

    cmd_candidate = exe_path.with_name("UnrealEditor-Cmd.exe")
    if cmd_candidate.exists():
        return cmd_candidate

    return exe_path


def _tail_lines(path: Path, max_lines: int = 120) -> List[str]:
    if not path.exists():
        return []
    out: deque[str] = deque(maxlen=max_lines)
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            out.append(line.rstrip("\n"))
    return list(out)


def _detect_repeated_error_line(log_paths: List[Path], threshold: int) -> Tuple[str, int]:
    if threshold <= 0:
        return "", 0

    pattern = re.compile(r"(error|exception|traceback|fatal|failed|assert)", flags=re.IGNORECASE)
    counts: Dict[str, int] = {}
    for log_path in log_paths:
        for raw in _tail_lines(log_path, max_lines=500):
            line = raw.strip()
            if not line:
                continue
            if not pattern.search(line):
                continue
            counts[line] = counts.get(line, 0) + 1

    if not counts:
        return "", 0

    top_line, top_count = max(counts.items(), key=lambda kv: kv[1])
    if top_count >= threshold:
        return top_line, top_count
    return "", 0


def _kill_process_tree(pid: int) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    try:
        os.kill(pid, 9)
    except OSError:
        pass


def _run_guarded_process(
    cmd: List[str],
    stdout_path: Path,
    stderr_path: Path,
    timeout_minutes: int,
    no_activity_minutes: int,
    repeated_error_threshold: int,
) -> Dict[str, Any]:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_path.unlink(missing_ok=True)
    stderr_path.unlink(missing_ok=True)

    start = time.monotonic()
    last_activity = start
    last_sizes = (0, 0)
    abort_reason = ""
    repeated_error_line = ""

    with stdout_path.open("w", encoding="utf-8", errors="ignore") as out_handle, stderr_path.open(
        "w", encoding="utf-8", errors="ignore"
    ) as err_handle:
        proc = subprocess.Popen(cmd, stdout=out_handle, stderr=err_handle)

        while proc.poll() is None:
            time.sleep(5)

            std_size = stdout_path.stat().st_size if stdout_path.exists() else 0
            err_size = stderr_path.stat().st_size if stderr_path.exists() else 0
            if (std_size, err_size) != last_sizes:
                last_sizes = (std_size, err_size)
                last_activity = time.monotonic()

            line, count = _detect_repeated_error_line([stdout_path, stderr_path], repeated_error_threshold)
            if line:
                abort_reason = "repeated_error"
                repeated_error_line = f"{line} (x{count})"
                _kill_process_tree(proc.pid)
                break

            now = time.monotonic()
            if now - start > (timeout_minutes * 60):
                abort_reason = "timeout"
                _kill_process_tree(proc.pid)
                break
            if now - last_activity > (no_activity_minutes * 60):
                abort_reason = "no_activity"
                _kill_process_tree(proc.pid)
                break

        try:
            exit_code = proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc.pid)
            exit_code = -9

    duration_sec = round(time.monotonic() - start, 3)
    return {
        "exit_code": int(exit_code),
        "duration_sec": duration_sec,
        "abort_reason": abort_reason,
        "repeated_error_line": repeated_error_line,
        "stdout_path": str(stdout_path.resolve()),
        "stderr_path": str(stderr_path.resolve()),
        "stdout_tail": _tail_lines(stdout_path, max_lines=60),
        "stderr_tail": _tail_lines(stderr_path, max_lines=60),
    }


def _sanitize_name(asset_path: str) -> str:
    name = asset_path.rsplit("/", 1)[-1]
    name = name.split(".")[0]
    return re.sub(r"[^0-9A-Za-z_-]+", "_", name)


def _count_frames(frame_dir: Path, image_ext: str) -> Tuple[int, str, str]:
    pattern = f"*.{image_ext.lower()}"
    files = sorted(frame_dir.glob(pattern))
    if not files:
        return 0, "", ""
    return len(files), str(files[0].resolve()), str(files[-1].resolve())


def _load_json_if_exists(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _has_missing_module_error(process_result: Dict[str, Any]) -> bool:
    lines: List[str] = []
    for key in ("stdout_tail", "stderr_tail"):
        value = process_result.get(key, [])
        if isinstance(value, list):
            lines.extend(str(v) for v in value)
    blob = "\n".join(lines).lower()
    return ("game module" in blob and "could not be found" in blob) or ("module 'mldeformersample'" in blob)


def _default_demo_cfg(infer_map: str) -> Dict[str, Any]:
    return {
        "enabled": True,
        "driver": "runtime_mrq_python_executor",
        "output": {
            "format": "png",
            "width": 1280,
            "height": 720,
            "clip_frames": 120,
            "zero_pad": 4,
        },
        "timeout": {
            "per_job_minutes": 30,
            "no_activity_minutes": 8,
        },
        "guard": {
            "repeated_error_threshold": 6,
        },
        "routes": [
            {
                "name": "nmm_flesh",
                "level_sequence": "/Game/Global/DemoRoom/LevelSequences/LS_NMM_Local",
                "map": infer_map,
                "animation_source": "infer_test_animations",
            },
            {
                "name": "nnm_upper",
                "level_sequence": "/Game/Global/DemoRoom/LevelSequences/LS_NearestNeighbour",
                "map": infer_map,
                "animation_source": "infer_test_animations",
            },
        ],
    }


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir)
    report_path = stage_report_path(run_dir, "infer_demo")
    report = make_report(
        stage="infer_demo",
        profile=args.profile,
        inputs={
            "config": str(Path(args.config).resolve()),
            "run_dir": str(run_dir.resolve()),
            "profile": args.profile,
        },
    )

    try:
        cfg = load_config(args.config)
        project_root = _script_project_root()

        ue_cfg = require_nested(cfg, ("ue",))
        infer_cfg = require_nested(ue_cfg, ("infer",))
        infer_map = str(require_nested(infer_cfg, ("map",)))
        test_anims = [str(v) for v in require_nested(infer_cfg, ("test_animations",))]
        if not test_anims:
            raise RuntimeError("ue.infer.test_animations must not be empty")

        demo_cfg_raw = infer_cfg.get("demo", {})
        if not isinstance(demo_cfg_raw, dict):
            raise RuntimeError("ue.infer.demo must be an object")

        demo_cfg = _default_demo_cfg(infer_map)
        demo_cfg.update(demo_cfg_raw)
        if isinstance(demo_cfg_raw.get("output"), dict):
            demo_cfg["output"].update(demo_cfg_raw["output"])
        if isinstance(demo_cfg_raw.get("timeout"), dict):
            demo_cfg["timeout"].update(demo_cfg_raw["timeout"])
        if isinstance(demo_cfg_raw.get("guard"), dict):
            demo_cfg["guard"].update(demo_cfg_raw["guard"])

        enabled = bool(demo_cfg.get("enabled", False))
        if not enabled:
            finalize_report(
                report,
                status="success",
                outputs={
                    "enabled": False,
                    "skipped": True,
                    "reason": "ue.infer.demo.enabled=false",
                    "jobs": [],
                    "jobs_summary": {"total": 0, "success": 0, "failed": 0},
                },
                errors=[],
            )
            write_json(report_path, report)
            return 0

        driver = str(demo_cfg.get("driver", "runtime_mrq_python_executor"))
        if driver != "runtime_mrq_python_executor":
            raise RuntimeError(f"Unsupported ue.infer.demo.driver: {driver}")

        output_cfg = demo_cfg.get("output", {})
        if not isinstance(output_cfg, dict):
            raise RuntimeError("ue.infer.demo.output must be an object")

        image_format = str(output_cfg.get("format", "png")).lower()
        if image_format != "png":
            raise RuntimeError(f"Only PNG output is currently supported, got: {image_format}")
        width = int(output_cfg.get("width", 1280))
        height = int(output_cfg.get("height", 720))
        clip_frames = int(output_cfg.get("clip_frames", 120))
        zero_pad = int(output_cfg.get("zero_pad", 4))
        if clip_frames <= 0:
            raise RuntimeError("ue.infer.demo.output.clip_frames must be > 0")
        frame_start = 0
        # Runtime MRQ custom_end_frame behaves effectively as an exclusive bound in this setup.
        frame_end = frame_start + clip_frames

        timeout_cfg = demo_cfg.get("timeout", {})
        if not isinstance(timeout_cfg, dict):
            raise RuntimeError("ue.infer.demo.timeout must be an object")
        per_job_minutes = int(timeout_cfg.get("per_job_minutes", 30))
        no_activity_minutes = int(timeout_cfg.get("no_activity_minutes", 8))
        if per_job_minutes <= 0 or no_activity_minutes <= 0:
            raise RuntimeError("ue.infer.demo timeout values must be > 0")

        guard_cfg = demo_cfg.get("guard", {})
        if not isinstance(guard_cfg, dict):
            raise RuntimeError("ue.infer.demo.guard must be an object")
        repeated_error_threshold = int(guard_cfg.get("repeated_error_threshold", 6))
        if repeated_error_threshold <= 0:
            raise RuntimeError("ue.infer.demo.guard.repeated_error_threshold must be > 0")

        routes = demo_cfg.get("routes", [])
        if not isinstance(routes, list) or not routes:
            raise RuntimeError("ue.infer.demo.routes must be a non-empty array")

        content_python_dir = project_root / "Content" / "Python"
        init_unreal_py = content_python_dir / "init_unreal.py"
        executor_py = content_python_dir / "Hou2UeDemoRuntimeExecutor.py"
        if not init_unreal_py.exists() or not executor_py.exists():
            raise RuntimeError(
                "Runtime executor files missing. Expected files: "
                f"{init_unreal_py} and {executor_py}"
            )

        uproject_path = _resolve_path(project_root, str(require_nested(cfg, ("paths", "uproject"))))
        if not uproject_path.exists():
            raise RuntimeError(f"uproject not found: {uproject_path}")

        ue_editor_exe = str(require_nested(cfg, ("paths", "ue_editor_exe")))
        editor_cmd = _resolve_editor_cmd(ue_editor_exe)

        job_report_root = run_dir / "reports" / "infer_demo_jobs"
        log_root = run_dir / "reports" / "logs" / "infer_demo"
        demo_root = run_dir / "workspace" / "staging" / args.profile / "ue_demo"
        job_report_root.mkdir(parents=True, exist_ok=True)
        log_root.mkdir(parents=True, exist_ok=True)
        demo_root.mkdir(parents=True, exist_ok=True)

        jobs: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        sample_frames: List[str] = []

        for route_item in routes:
            if not isinstance(route_item, dict):
                raise RuntimeError("Each entry in ue.infer.demo.routes must be an object")

            route_name = str(require_nested(route_item, ("name",)))
            level_sequence = str(require_nested(route_item, ("level_sequence",)))
            route_map = str(route_item.get("map", infer_map) or infer_map)
            anim_source = str(route_item.get("animation_source", "infer_test_animations"))
            if anim_source != "infer_test_animations":
                raise RuntimeError(
                    f"Unsupported animation_source for route '{route_name}': {anim_source}"
                )

            for anim_asset in test_anims:
                anim_name = _sanitize_name(anim_asset)
                job_id = f"{route_name}__{anim_name}"
                frame_dir = demo_root / route_name / anim_name / "frames"
                job_json = job_report_root / f"{job_id}.json"
                stdout_path = log_root / f"{job_id}.stdout.log"
                stderr_path = log_root / f"{job_id}.stderr.log"

                if frame_dir.parent.exists():
                    shutil.rmtree(frame_dir.parent, ignore_errors=True)
                frame_dir.mkdir(parents=True, exist_ok=True)
                job_json.unlink(missing_ok=True)

                cmd = [
                    str(editor_cmd),
                    str(uproject_path),
                    route_map,
                    "-game",
                    "-MoviePipelineLocalExecutorClass=/Script/MovieRenderPipelineCore.MoviePipelinePythonHostExecutor",
                    "-ExecutorPythonClass=/Engine/PythonTypes.Hou2UeDemoRuntimeExecutor",
                    f"-DemoSequence={level_sequence}",
                    f"-DemoAnim={anim_asset}",
                    f"-DemoMap={route_map}",
                    f"-DemoOutputDir={frame_dir}",
                    f"-DemoResX={width}",
                    f"-DemoResY={height}",
                    f"-DemoStartFrame={frame_start}",
                    f"-DemoEndFrame={frame_end}",
                    f"-DemoZeroPad={zero_pad}",
                    f"-DemoReportJson={job_json}",
                    "-NoLoadingScreen",
                    "-NoSound",
                    "-unattended",
                    "-nop4",
                    "-nosplash",
                    "-stdout",
                    "-FullStdOutLogOutput",
                    "-log",
                ]

                process_result = _run_guarded_process(
                    cmd=cmd,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    timeout_minutes=per_job_minutes,
                    no_activity_minutes=no_activity_minutes,
                    repeated_error_threshold=repeated_error_threshold,
                )
                ue_job_report = _load_json_if_exists(job_json)
                frame_count, first_frame, last_frame = _count_frames(frame_dir, image_format)

                success = (
                    process_result["abort_reason"] == ""
                    and int(process_result["exit_code"]) == 0
                    and bool(ue_job_report)
                    and str(ue_job_report.get("status", "")).lower() == "success"
                    and frame_count >= clip_frames
                )
                module_fallback = False
                if not success and _has_missing_module_error(process_result) and "-game" in cmd:
                    module_fallback = True
                    for file in frame_dir.glob("*.png"):
                        file.unlink(missing_ok=True)
                    job_json.unlink(missing_ok=True)

                    cmd = [arg for arg in cmd if arg != "-game"]
                    process_result = _run_guarded_process(
                        cmd=cmd,
                        stdout_path=stdout_path,
                        stderr_path=stderr_path,
                        timeout_minutes=per_job_minutes,
                        no_activity_minutes=no_activity_minutes,
                        repeated_error_threshold=repeated_error_threshold,
                    )
                    ue_job_report = _load_json_if_exists(job_json)
                    frame_count, first_frame, last_frame = _count_frames(frame_dir, image_format)
                    success = (
                        process_result["abort_reason"] == ""
                        and int(process_result["exit_code"]) == 0
                        and bool(ue_job_report)
                        and str(ue_job_report.get("status", "")).lower() == "success"
                        and frame_count >= clip_frames
                    )

                if first_frame and len(sample_frames) < 6:
                    sample_frames.append(first_frame)

                job_entry = {
                    "job_id": job_id,
                    "route": route_name,
                    "map": route_map,
                    "level_sequence": level_sequence,
                    "animation": anim_asset,
                    "output_dir": str(frame_dir.resolve()),
                    "job_report_json": str(job_json.resolve()),
                    "status": "success" if success else "failed",
                    "frame_count": frame_count,
                    "first_frame": first_frame,
                    "last_frame": last_frame,
                    "expected_min_frames": clip_frames,
                    "guard": {
                        "timeout_minutes": per_job_minutes,
                        "no_activity_minutes": no_activity_minutes,
                        "repeated_error_threshold": repeated_error_threshold,
                    },
                    "fallback_retry_without_game": module_fallback,
                    "process": process_result,
                    "executor_report": ue_job_report,
                }
                jobs.append(job_entry)

                if not success:
                    errors.append(
                        {
                            "job_id": job_id,
                            "message": "Demo capture job failed",
                            "abort_reason": process_result.get("abort_reason", ""),
                            "exit_code": process_result.get("exit_code", -1),
                            "repeated_error_line": process_result.get("repeated_error_line", ""),
                            "stdout_tail": process_result.get("stdout_tail", []),
                            "stderr_tail": process_result.get("stderr_tail", []),
                            "executor_report": ue_job_report,
                            "frame_count": frame_count,
                            "expected_min_frames": clip_frames,
                        }
                    )

        total_jobs = len(jobs)
        success_jobs = len([j for j in jobs if j.get("status") == "success"])
        failed_jobs = total_jobs - success_jobs
        total_frames = sum(int(j.get("frame_count", 0)) for j in jobs)
        status = "success" if failed_jobs == 0 else "failed"

        finalize_report(
            report,
            status=status,
            outputs={
                "enabled": True,
                "driver": driver,
                "output": {
                    "format": image_format,
                    "width": width,
                    "height": height,
                    "clip_frames": clip_frames,
                    "zero_pad": zero_pad,
                    "frame_start": frame_start,
                    "frame_end": frame_end,
                },
                "jobs": jobs,
                "jobs_summary": {
                    "total": total_jobs,
                    "success": success_jobs,
                    "failed": failed_jobs,
                },
                "total_frames": total_frames,
                "sample_frames": sample_frames,
                "demo_root": str(demo_root.resolve()),
            },
            errors=errors,
        )
        write_json(report_path, report)
        return 0 if status == "success" else 1

    except Exception as exc:
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
