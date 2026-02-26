#!/usr/bin/env python3
"""Synchronize reference baseline assets into current source project (two-phase)."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from common import (
    ConfigError,
    finalize_report,
    load_config,
    make_report,
    require_nested,
    stage_report_path,
    timestamp_compact,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync reference baseline assets")
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile", required=True, choices=["smoke", "full"])
    parser.add_argument("--run-dir", required=True)
    return parser.parse_args()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_path(base: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _game_path_to_uasset_rel(game_path: str) -> Path:
    path = game_path.strip()
    if not path.startswith("/Game/"):
        raise RuntimeError(f"rollback map path must start with /Game/: {game_path}")
    rel = path[len("/Game/") :]
    return Path("Content") / f"{rel}.umap"


def _collect_files(root: Path, globs: Iterable[str]) -> List[Path]:
    found: set[Path] = set()
    for pattern in globs:
        pattern = str(pattern or "").strip()
        if not pattern:
            continue

        has_wildcard = any(token in pattern for token in ("*", "?", "["))
        if has_wildcard:
            for match in root.glob(pattern):
                if match.is_file():
                    found.add(match.resolve())
            continue

        direct = (root / pattern).resolve()
        if direct.is_file():
            found.add(direct)

    return sorted(found)


def _copy_with_backup(
    src: Path,
    dst: Path,
    backup_root: Path,
    verify_hash: bool,
    backup_before_overwrite: bool,
) -> Dict[str, Any]:
    src = src.resolve()
    status = "create"
    copied = True
    backup_path = ""

    src_hash = ""
    dst_hash_before = ""

    if dst.exists() and dst.is_file():
        status = "update"
        if verify_hash:
            src_hash = _sha256(src)
            dst_hash_before = _sha256(dst)
            if src_hash == dst_hash_before:
                copied = False
                status = "unchanged"

    if copied:
        if dst.exists() and dst.is_file() and backup_before_overwrite:
            rel = dst.relative_to(_project_root()) if dst.is_relative_to(_project_root()) else Path(dst.name)
            backup_target = backup_root / rel
            backup_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, backup_target)
            backup_path = str(backup_target.resolve())

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    verify_ok = True
    dst_hash_after = ""
    if verify_hash:
        if not src_hash:
            src_hash = _sha256(src)
        dst_hash_after = _sha256(dst)
        verify_ok = src_hash == dst_hash_after

    return {
        "source": str(src),
        "destination": str(dst),
        "status": status,
        "copied": copied,
        "backup_path": backup_path,
        "verify_ok": verify_ok,
        "src_hash": src_hash,
        "dst_hash_before": dst_hash_before,
        "dst_hash_after": dst_hash_after,
    }


def _phase_sync(
    phase_name: str,
    patterns: List[str],
    reference_root: Path,
    project_root: Path,
    backup_root: Path,
    verify_hash: bool,
    backup_before_overwrite: bool,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    files = _collect_files(reference_root, patterns)
    details: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    created_count = 0
    updated_count = 0
    unchanged_count = 0
    copied_count = 0
    verified_count = 0

    for src in files:
        rel = src.relative_to(reference_root)
        dst = (project_root / rel).resolve()

        try:
            result = _copy_with_backup(
                src=src,
                dst=dst,
                backup_root=backup_root / phase_name,
                verify_hash=verify_hash,
                backup_before_overwrite=backup_before_overwrite,
            )
        except Exception as exc:
            errors.append(
                {
                    "phase": phase_name,
                    "source": str(src),
                    "destination": str(dst),
                    "message": str(exc),
                }
            )
            continue

        status = str(result["status"])
        if status == "create":
            created_count += 1
        elif status == "update":
            updated_count += 1
        elif status == "unchanged":
            unchanged_count += 1

        if bool(result.get("copied", False)):
            copied_count += 1
        if bool(result.get("verify_ok", False)):
            verified_count += 1
        else:
            errors.append(
                {
                    "phase": phase_name,
                    "source": result.get("source", ""),
                    "destination": result.get("destination", ""),
                    "message": "hash verification mismatch",
                }
            )

        # keep report bounded; retain concise entries only
        details.append(
            {
                "source": result["source"],
                "destination": result["destination"],
                "status": status,
                "copied": bool(result["copied"]),
                "verify_ok": bool(result["verify_ok"]),
                "backup_path": result["backup_path"],
            }
        )

    summary = {
        "phase": phase_name,
        "patterns": patterns,
        "matched_file_count": len(files),
        "create_count": created_count,
        "update_count": updated_count,
        "unchanged_count": unchanged_count,
        "copied_count": copied_count,
        "verified_count": verified_count,
        "error_count": len(errors),
        "files": details,
    }
    return summary, errors


def _sync_rollback_maps(
    rollback_maps: List[str],
    reference_root: Path,
    project_root: Path,
    backup_root: Path,
    verify_hash: bool,
    backup_before_overwrite: bool,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for game_path in rollback_maps:
        try:
            rel = _game_path_to_uasset_rel(game_path)
        except Exception as exc:
            errors.append({"map": game_path, "message": str(exc)})
            continue

        src = (reference_root / rel).resolve()
        dst = (project_root / rel).resolve()
        if not src.exists():
            errors.append({"map": game_path, "source": str(src), "message": "source map missing in reference"})
            continue

        try:
            result = _copy_with_backup(
                src=src,
                dst=dst,
                backup_root=backup_root / "rollback_maps",
                verify_hash=verify_hash,
                backup_before_overwrite=backup_before_overwrite,
            )
        except Exception as exc:
            errors.append(
                {
                    "map": game_path,
                    "source": str(src),
                    "destination": str(dst),
                    "message": str(exc),
                }
            )
            continue

        rows.append(
            {
                "map": game_path,
                "source": str(src),
                "destination": str(dst),
                "status": result.get("status", ""),
                "copied": bool(result.get("copied", False)),
                "verify_ok": bool(result.get("verify_ok", False)),
                "backup_path": result.get("backup_path", ""),
            }
        )

        if not bool(result.get("verify_ok", False)):
            errors.append(
                {
                    "map": game_path,
                    "source": str(src),
                    "destination": str(dst),
                    "message": "rollback map hash verification mismatch",
                }
            )

    return rows, errors


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir)
    report_path = stage_report_path(run_dir, "baseline_sync")
    report = make_report(
        stage="baseline_sync",
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

        enabled = bool(baseline_cfg.get("enabled", False))
        if not enabled:
            finalize_report(
                report,
                status="success",
                outputs={"enabled": False, "skipped": True, "reason": "reference_baseline.enabled=false"},
                errors=[],
            )
            write_json(report_path, report)
            return 0

        project_root = _project_root()
        reference_uproject = _resolve_path(project_root, str(require_nested(baseline_cfg, ("reference_uproject",))))
        if not reference_uproject.exists():
            raise RuntimeError(f"reference uproject not found: {reference_uproject}")
        reference_root = reference_uproject.parent

        sync_cfg = require_nested(baseline_cfg, ("sync",))
        strategy = str(sync_cfg.get("strategy", "two_phase") or "two_phase").strip().lower()
        if strategy != "two_phase":
            raise RuntimeError(f"Unsupported reference_baseline.sync.strategy: {strategy}")

        phase1_patterns = [str(v) for v in sync_cfg.get("phase1_include_globs", [])]
        phase2_patterns = [str(v) for v in sync_cfg.get("phase2_include_globs", [])]
        verify_hash = bool(sync_cfg.get("verify_hash", True))
        backup_before_overwrite = bool(sync_cfg.get("backup_before_overwrite", True))
        rollback_maps = [str(v) for v in sync_cfg.get("rollback_maps", [])]

        backup_root = run_dir / "workspace" / "backups" / "baseline_sync" / timestamp_compact()
        backup_root.mkdir(parents=True, exist_ok=True)

        phase1, phase1_errors = _phase_sync(
            phase_name="phase1",
            patterns=phase1_patterns,
            reference_root=reference_root,
            project_root=project_root,
            backup_root=backup_root,
            verify_hash=verify_hash,
            backup_before_overwrite=backup_before_overwrite,
        )
        phase2, phase2_errors = _phase_sync(
            phase_name="phase2",
            patterns=phase2_patterns,
            reference_root=reference_root,
            project_root=project_root,
            backup_root=backup_root,
            verify_hash=verify_hash,
            backup_before_overwrite=backup_before_overwrite,
        )

        rollback_rows, rollback_errors = _sync_rollback_maps(
            rollback_maps=rollback_maps,
            reference_root=reference_root,
            project_root=project_root,
            backup_root=backup_root,
            verify_hash=verify_hash,
            backup_before_overwrite=backup_before_overwrite,
        )

        errors = phase1_errors + phase2_errors + rollback_errors
        status = "success" if not errors else "failed"

        finalize_report(
            report,
            status=status,
            outputs={
                "enabled": True,
                "strategy": strategy,
                "reference_uproject": str(reference_uproject.resolve()),
                "reference_root": str(reference_root.resolve()),
                "project_root": str(project_root.resolve()),
                "backup_root": str(backup_root.resolve()),
                "verify_hash": verify_hash,
                "backup_before_overwrite": backup_before_overwrite,
                "phases": [phase1, phase2],
                "rollback_maps": rollback_rows,
            },
            errors=errors,
        )
        write_json(report_path, report)
        return 0 if status == "success" else 1

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
