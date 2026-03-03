#!/usr/bin/env python3
"""Capture Main_Sequence image sequence for ground-truth comparison."""

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
    parser = argparse.ArgumentParser(description="Capture Main_Sequence image sequence")
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile", required=True, choices=["smoke", "full"])
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--capture-kind", required=True, choices=["reference", "source"])
    parser.add_argument("--resume", action="store_true",
                        help="Resume a partial capture: preserve existing frames, start UE from the existing frame count.")
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
    if candidate.exists():
        return candidate
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
            if not line or not pattern.search(line):
                continue
            counts[line] = counts.get(line, 0) + 1

    if not counts:
        return "", 0
    line, count = max(counts.items(), key=lambda kv: kv[1])
    if count >= threshold:
        return line, count
    return "", 0


def _kill_process_tree(pid: int) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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

    with stdout_path.open("w", encoding="utf-8", errors="ignore") as out_handle, stderr_path.open("w", encoding="utf-8", errors="ignore") as err_handle:
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
            if now - start > timeout_minutes * 60:
                abort_reason = "timeout"
                _kill_process_tree(proc.pid)
                break
            if now - last_activity > no_activity_minutes * 60:
                abort_reason = "no_activity"
                _kill_process_tree(proc.pid)
                break

        try:
            exit_code = proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc.pid)
            exit_code = -9

    return {
        "exit_code": int(exit_code),
        "duration_sec": round(time.monotonic() - start, 3),
        "abort_reason": abort_reason,
        "repeated_error_line": repeated_error_line,
        "stdout_path": str(stdout_path.resolve()),
        "stderr_path": str(stderr_path.resolve()),
        "stdout_tail": _tail_lines(stdout_path, 80),
        "stderr_tail": _tail_lines(stderr_path, 80),
    }


def _count_frames(frame_dir: Path, ext: str) -> Tuple[int, str, str]:
    files = sorted([p for p in frame_dir.rglob(f"*.{ext.lower()}") if p.is_file()])
    if not files:
        return 0, "", ""
    return len(files), str(files[0].resolve()), str(files[-1].resolve())


def _load_json(path: Path) -> Dict[str, Any]:
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


def _resolve_capture_uproject(cfg: Dict[str, Any], gt_cfg: Dict[str, Any], project_root: Path, capture_kind: str) -> Path:
    if capture_kind == "reference":
        capture_cfg = gt_cfg.get("capture", {}) if isinstance(gt_cfg.get("capture"), dict) else {}
        ref_value = str(capture_cfg.get("reference_uproject", "") or "")
        if not ref_value:
            ref_value = str(require_nested(cfg, ("reference_baseline", "reference_uproject")))
        path = _resolve_path(project_root, ref_value)
    else:
        path = _resolve_path(project_root, str(require_nested(cfg, ("paths", "uproject"))))

    if not path.exists():
        raise RuntimeError(f"uproject not found for capture kind '{capture_kind}': {path}")
    return path


def _ensure_runtime_executor_available(target_uproject: Path, source_project_root: Path) -> List[str]:
    copied: List[str] = []
    source_py = source_project_root / "Content" / "Python"
    target_py = target_uproject.parent / "Content" / "Python"
    files = ["init_unreal.py", "Hou2UeDemoRuntimeExecutor.py"]

    target_py.mkdir(parents=True, exist_ok=True)
    for name in files:
        src = source_py / name
        dst = target_py / name
        if not src.exists():
            continue
        if dst.exists():
            try:
                if src.read_bytes() == dst.read_bytes():
                    continue
            except Exception:
                pass
        shutil.copy2(src, dst)
        copied.append(str(dst.resolve()))
    return copied


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir)
    stage_name = "gt_reference_capture" if args.capture_kind == "reference" else "gt_source_capture"
    report_path = stage_report_path(run_dir, stage_name)

    report = make_report(
        stage=stage_name,
        profile=args.profile,
        inputs={
            "config": str(Path(args.config).resolve()),
            "run_dir": str(run_dir.resolve()),
            "profile": args.profile,
            "capture_kind": args.capture_kind,
        },
    )

    try:
        cfg = load_config(args.config)
        ue_cfg = require_nested(cfg, ("ue",))
        gt_cfg = require_nested(ue_cfg, ("ground_truth",))

        enabled = bool(gt_cfg.get("enabled", False))
        if not enabled:
            finalize_report(
                report,
                status="success",
                outputs={"enabled": False, "skipped": True, "reason": "ue.ground_truth.enabled=false"},
                errors=[],
            )
            write_json(report_path, report)
            return 0

        driver = str(gt_cfg.get("driver", "main_sequence_direct") or "main_sequence_direct")
        if driver != "main_sequence_direct":
            raise RuntimeError(f"Unsupported ue.ground_truth.driver: {driver}")

        map_path = str(require_nested(gt_cfg, ("map",)))
        sequence_path = str(require_nested(gt_cfg, ("level_sequence",)))

        capture_cfg = gt_cfg.get("capture", {}) if isinstance(gt_cfg.get("capture"), dict) else {}
        fmt = str(capture_cfg.get("output_format", "png") or "png").lower()
        if fmt != "png":
            raise RuntimeError(f"Only png output_format is supported, got: {fmt}")

        width = int(capture_cfg.get("width", 1280))
        height = int(capture_cfg.get("height", 720))
        frame_window = str(capture_cfg.get("frame_window", "full_sequence") or "full_sequence")
        warmup_frames = int(capture_cfg.get("warmup_frames", 0))
        render_mode = str(capture_cfg.get("render_mode", "lit") or "lit").lower()

        # ── UE57 static reference frames bypass ───────────────────────────────
        # When ue.ground_truth.capture.static_reference_frames_dir is set and
        # capture_kind == "reference", skip the UE Editor render entirely and
        # populate the frames directory from the pre-rendered UE5.5 frames.
        # This enables cross-version GT comparison without re-rendering.
        static_ref_dir_str = str(capture_cfg.get("static_reference_frames_dir", "") or "")
        if args.capture_kind == "reference" and static_ref_dir_str:
            static_ref_dir = Path(static_ref_dir_str)
            if not static_ref_dir.exists():
                raise RuntimeError(
                    f"static_reference_frames_dir does not exist: {static_ref_dir}"
                )

            gt_root = run_dir / "workspace" / "staging" / args.profile / "gt" / args.capture_kind
            frame_dir = gt_root / "frames"
            report_json = run_dir / "reports" / f"{stage_name}_job.json"

            frame_dir.mkdir(parents=True, exist_ok=True)
            report_json.parent.mkdir(parents=True, exist_ok=True)

            # Clean previous output for deterministic compare
            for _f in frame_dir.glob("*.png"):
                _f.unlink(missing_ok=True)
            report_json.unlink(missing_ok=True)

            src_files = sorted(p for p in static_ref_dir.rglob("*.png") if p.is_file())
            if not src_files:
                raise RuntimeError(
                    f"No PNG files found in static_reference_frames_dir: {static_ref_dir}"
                )
            for _src in src_files:
                shutil.copy2(_src, frame_dir / _src.name)

            frame_count, first_frame, last_frame = _count_frames(frame_dir, "png")
            write_json(report_json, {
                "status": "success",
                "source": "static_reference_frames_dir",
                "static_reference_frames_dir": str(static_ref_dir.resolve()),
                "frame_count": frame_count,
            })

            finalize_report(
                report,
                status="success",
                outputs={
                    "enabled": True,
                    "capture_kind": args.capture_kind,
                    "uproject": "N/A (static_reference_frames_dir mode)",
                    "map": map_path,
                    "level_sequence": sequence_path,
                    "output_format": fmt,
                    "width": width,
                    "height": height,
                    "frame_window": frame_window,
                    "warmup_frames": warmup_frames,
                    "frame_count": frame_count,
                    "first_frame": first_frame,
                    "last_frame": last_frame,
                    "output_dir": str(frame_dir.resolve()),
                    "executor_report_json": str(report_json.resolve()),
                    "fallback_used": False,
                    "fallback_reason": "",
                    "executor_sync_files": [],
                    "command": [],
                    "process": {"static_bypass": True},
                    "static_reference_frames_dir": str(static_ref_dir.resolve()),
                },
                errors=[],
            )
            write_json(report_path, report)
            return 0
        # ── end static reference frames bypass ────────────────────────────────

        # ── static source frames bypass ───────────────────────────────────────
        # When ue.ground_truth.capture.static_source_frames_dir is set and
        # capture_kind == "source", skip the UE Editor render entirely and
        # populate the frames directory from the pre-rendered source frames.
        # Useful when Lumen GI convergence issues prevent reliable re-capture.
        static_src_dir_str = str(capture_cfg.get("static_source_frames_dir", "") or "")
        if args.capture_kind == "source" and static_src_dir_str:
            static_src_dir = Path(static_src_dir_str)
            if not static_src_dir.exists():
                raise RuntimeError(
                    f"static_source_frames_dir does not exist: {static_src_dir}"
                )

            gt_root = run_dir / "workspace" / "staging" / args.profile / "gt" / args.capture_kind
            frame_dir = gt_root / "frames"
            report_json = run_dir / "reports" / f"{stage_name}_job.json"

            frame_dir.mkdir(parents=True, exist_ok=True)
            report_json.parent.mkdir(parents=True, exist_ok=True)

            for _f in frame_dir.glob("*.png"):
                _f.unlink(missing_ok=True)
            report_json.unlink(missing_ok=True)

            src_files = sorted(p for p in static_src_dir.rglob("*.png") if p.is_file())
            if not src_files:
                raise RuntimeError(
                    f"No PNG files found in static_source_frames_dir: {static_src_dir}"
                )
            for _src in src_files:
                shutil.copy2(_src, frame_dir / _src.name)

            frame_count, first_frame, last_frame = _count_frames(frame_dir, "png")
            write_json(report_json, {
                "status": "success",
                "source": "static_source_frames_dir",
                "static_source_frames_dir": str(static_src_dir.resolve()),
                "frame_count": frame_count,
            })

            finalize_report(
                report,
                status="success",
                outputs={
                    "enabled": True,
                    "capture_kind": args.capture_kind,
                    "uproject": "N/A (static_source_frames_dir mode)",
                    "map": map_path,
                    "level_sequence": sequence_path,
                    "output_format": fmt,
                    "width": width,
                    "height": height,
                    "frame_window": frame_window,
                    "warmup_frames": warmup_frames,
                    "frame_count": frame_count,
                    "first_frame": first_frame,
                    "last_frame": last_frame,
                    "output_dir": str(frame_dir.resolve()),
                    "executor_report_json": str(report_json.resolve()),
                    "fallback_used": False,
                    "fallback_reason": "",
                    "executor_sync_files": [],
                    "command": [],
                    "process": {"static_bypass": True},
                    "static_source_frames_dir": str(static_src_dir.resolve()),
                },
                errors=[],
            )
            write_json(report_path, report)
            return 0
        # ── end static source frames bypass ──────────────────────────────────

        infer_cfg = ue_cfg.get("infer", {}) if isinstance(ue_cfg.get("infer"), dict) else {}
        demo_cfg = infer_cfg.get("demo", {}) if isinstance(infer_cfg.get("demo"), dict) else {}
        demo_timeout = demo_cfg.get("timeout", {}) if isinstance(demo_cfg.get("timeout"), dict) else {}
        demo_guard = demo_cfg.get("guard", {}) if isinstance(demo_cfg.get("guard"), dict) else {}
        timeout_minutes = int(demo_timeout.get("per_job_minutes", 90))
        no_activity_minutes = int(demo_timeout.get("no_activity_minutes", 20))
        repeated_error_threshold = int(demo_guard.get("repeated_error_threshold", 8))

        project_root = _project_root()
        uproject_path = _resolve_capture_uproject(cfg, gt_cfg, project_root, args.capture_kind)
        source_uproject = _resolve_path(project_root, str(require_nested(cfg, ("paths", "uproject"))))
        executor_sync_files: List[str] = []
        if args.capture_kind == "reference":
            executor_sync_files = _ensure_runtime_executor_available(uproject_path, project_root)
        editor_cmd = _resolve_editor_cmd(str(require_nested(cfg, ("paths", "ue_editor_exe"))))

        gt_root = run_dir / "workspace" / "staging" / args.profile / "gt" / args.capture_kind
        frame_dir = gt_root / "frames"
        report_json = run_dir / "reports" / f"{stage_name}_job.json"
        stdout_path = run_dir / "reports" / "logs" / f"{stage_name}.stdout.log"
        stderr_path = run_dir / "reports" / "logs" / f"{stage_name}.stderr.log"

        frame_dir.mkdir(parents=True, exist_ok=True)
        report_json.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.parent.mkdir(parents=True, exist_ok=True)

        # Determine resume offset before any cleanup
        resume_start_frame: int = 0
        if args.resume:
            resume_start_frame, _, _ = _count_frames(frame_dir, fmt)
            print(f"[ue_capture] Resume mode: {resume_start_frame} existing frames found, starting from frame {resume_start_frame}")
        else:
            # clean previous output for deterministic compare
            for file in frame_dir.glob("*.png"):
                file.unlink(missing_ok=True)
        report_json.unlink(missing_ok=True)

        cmd = [
            str(editor_cmd),
            str(uproject_path),
            map_path,
            "-game",
            "-MoviePipelineLocalExecutorClass=/Script/MovieRenderPipelineCore.MoviePipelinePythonHostExecutor",
            "-ExecutorPythonClass=/Engine/PythonTypes.Hou2UeDemoRuntimeExecutor",
            f"-DemoSequence={sequence_path}",
            f"-DemoMap={map_path}",
            f"-DemoOutputDir={frame_dir}",
            f"-DemoResX={width}",
            f"-DemoResY={height}",
            f"-DemoWarmupFrames={warmup_frames}",
            f"-DemoRenderMode={render_mode}",
            f"-DemoReportJson={report_json}",
            "-NoLoadingScreen",
            "-NoSound",
            "-unattended",
            "-nop4",
            "-nosplash",
            "-stdout",
            "-FullStdOutLogOutput",
            "-log",
        ]

        # In resume mode, tell the UE executor to skip already-captured frames.
        if resume_start_frame > 0:
            cmd.append(f"-DemoStartFrame={resume_start_frame}")

        # full-sequence mode lets runtime executor derive range from sequence playback range.
        if frame_window != "full_sequence":
            raise RuntimeError(f"Unsupported frame_window mode: {frame_window}")

        process_result = _run_guarded_process(
            cmd=cmd,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timeout_minutes=timeout_minutes,
            no_activity_minutes=no_activity_minutes,
            repeated_error_threshold=repeated_error_threshold,
        )

        executor_report = _load_json(report_json)
        frame_count, first_frame, last_frame = _count_frames(frame_dir, fmt)

        success = (
            process_result.get("abort_reason", "") == ""
            and int(process_result.get("exit_code", -1)) == 0
            and bool(executor_report)
            and str(executor_report.get("status", "")).lower() == "success"
            and frame_count > 0
        )

        fallback_used = False
        fallback_reason = ""
        if (
            not success
            and args.capture_kind == "reference"
            and source_uproject.exists()
            and source_uproject.resolve() != uproject_path.resolve()
            and _has_missing_module_error(process_result)
        ):
            fallback_used = True
            fallback_reason = "reference_uproject_missing_module_fallback_to_source_project"

            for file in frame_dir.glob("*.png"):
                file.unlink(missing_ok=True)
            report_json.unlink(missing_ok=True)

            cmd = list(cmd)
            cmd[1] = str(source_uproject)
            process_result = _run_guarded_process(
                cmd=cmd,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                timeout_minutes=timeout_minutes,
                no_activity_minutes=no_activity_minutes,
                repeated_error_threshold=repeated_error_threshold,
            )
            executor_report = _load_json(report_json)
            frame_count, first_frame, last_frame = _count_frames(frame_dir, fmt)
            success = (
                process_result.get("abort_reason", "") == ""
                and int(process_result.get("exit_code", -1)) == 0
                and bool(executor_report)
                and str(executor_report.get("status", "")).lower() == "success"
                and frame_count > 0
            )
            uproject_path = source_uproject
        if not success and _has_missing_module_error(process_result) and "-game" in cmd:
            fallback_used = True
            if fallback_reason:
                fallback_reason += ";"
            fallback_reason += "retry_without_game_flag"

            for file in frame_dir.glob("*.png"):
                file.unlink(missing_ok=True)
            report_json.unlink(missing_ok=True)

            cmd = [arg for arg in cmd if arg != "-game"]
            process_result = _run_guarded_process(
                cmd=cmd,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                timeout_minutes=timeout_minutes,
                no_activity_minutes=no_activity_minutes,
                repeated_error_threshold=repeated_error_threshold,
            )
            executor_report = _load_json(report_json)
            frame_count, first_frame, last_frame = _count_frames(frame_dir, fmt)
            success = (
                process_result.get("abort_reason", "") == ""
                and int(process_result.get("exit_code", -1)) == 0
                and bool(executor_report)
                and str(executor_report.get("status", "")).lower() == "success"
                and frame_count > 0
            )

        errors: List[Dict[str, Any]] = []
        if not success:
            errors.append(
                {
                    "message": "ground-truth capture failed",
                    "abort_reason": process_result.get("abort_reason", ""),
                    "exit_code": process_result.get("exit_code", -1),
                    "repeated_error_line": process_result.get("repeated_error_line", ""),
                    "stdout_tail": process_result.get("stdout_tail", []),
                    "stderr_tail": process_result.get("stderr_tail", []),
                    "executor_report": executor_report,
                    "frame_count": frame_count,
                }
            )

        finalize_report(
            report,
            status="success" if success else "failed",
            outputs={
                "enabled": True,
                "capture_kind": args.capture_kind,
                "uproject": str(uproject_path.resolve()),
                "map": map_path,
                "level_sequence": sequence_path,
                "output_format": fmt,
                "width": width,
                "height": height,
                "frame_window": frame_window,
                "warmup_frames": warmup_frames,
                "frame_count": frame_count,
                "first_frame": first_frame,
                "last_frame": last_frame,
                "output_dir": str(frame_dir.resolve()),
                "executor_report_json": str(report_json.resolve()),
                "fallback_used": fallback_used,
                "fallback_reason": fallback_reason,
                "executor_sync_files": executor_sync_files,
                "command": cmd,
                "process": process_result,
            },
            errors=errors,
        )
        write_json(report_path, report)
        return 0 if success else 1

    except Exception as exc:
        finalize_report(
            report,
            status="failed",
            outputs={},
            errors=[{"message": str(exc), "traceback": traceback.format_exc()}],
        )
        write_json(report_path, report)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
