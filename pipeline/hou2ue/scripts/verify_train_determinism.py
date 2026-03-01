#!/usr/bin/env python3
"""verify_train_determinism.py — Phase 3.4

Compare two training run directories and verify that the trained network
artifacts (.nmn / .ubnne) produced with the same seed are byte-identical.

Usage (standalone, outside Unreal):
    python verify_train_determinism.py \\
        --run-dir-a pipeline/hou2ue/workspace/runs/<run_a> \\
        --run-dir-b pipeline/hou2ue/workspace/runs/<run_b> \\
        [--out    pipeline/hou2ue/workspace/reports/train_determinism_diff.json]

The script:
1. Reads train_report.json from each run to locate .nmn / .ubnne files.
2. SHA-256 hashes each artifact.
3. Compares per-model hashes between run_a and run_b.
4. Writes a structured JSON report and exits non-zero if any hash differs.

Example successful output in report JSON:
    {
      "status": "success",
      "train_determinism_status": "success",
      "pairs_checked": 3,
      "pairs_matching": 3,
      ...
    }
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of a file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_train_report(run_dir: Path) -> Dict[str, Any]:
    p = run_dir / "reports" / "train_report.json"
    if not p.exists():
        raise FileNotFoundError(f"train_report.json not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _extract_network_paths(report: Dict[str, Any]) -> Dict[str, str]:
    """Return {asset_key: network_file_path} from a train_report."""
    outputs = report.get("outputs", {})
    results = outputs.get("results", [])
    out: Dict[str, str] = {}
    for item in results:
        if not isinstance(item, dict):
            continue
        model_type = str(item.get("model_type", "")).upper()
        asset_path = str(item.get("asset_path", ""))
        net_path = str(item.get("network_file_path", ""))
        # Use the UE asset path as key (last segment as short label).
        label = asset_path.split("/")[-1] if "/" in asset_path else asset_path
        if net_path and net_path != "None":
            out[label] = net_path
    return out


def _compare_runs(
    run_dir_a: Path,
    run_dir_b: Path,
) -> Dict[str, Any]:
    report_a = _load_train_report(run_dir_a)
    report_b = _load_train_report(run_dir_b)

    def _seed(r: Dict[str, Any]) -> int | None:
        outputs = r.get("outputs", {})
        det = outputs.get("determinism", {})
        if isinstance(det, dict):
            return int(det.get("seed", -1))
        return None

    seed_a = _seed(report_a)
    seed_b = _seed(report_b)

    pairs: List[Dict[str, Any]] = []
    mismatches: List[str] = []
    errors: List[str] = []

    nets_a = _extract_network_paths(report_a)
    nets_b = _extract_network_paths(report_b)

    # Check all keys present in run_a against run_b.
    all_labels = sorted(set(nets_a) | set(nets_b))
    for label in all_labels:
        path_a_str = nets_a.get(label, "")
        path_b_str = nets_b.get(label, "")

        if not path_a_str:
            errors.append(f"{label}: missing in run_a")
            continue
        if not path_b_str:
            errors.append(f"{label}: missing in run_b")
            continue

        path_a = Path(path_a_str)
        path_b = Path(path_b_str)

        if not path_a.exists():
            errors.append(f"{label}: run_a file not found: {path_a}")
            continue
        if not path_b.exists():
            errors.append(f"{label}: run_b file not found: {path_b}")
            continue

        hash_a = _sha256_file(path_a)
        hash_b = _sha256_file(path_b)
        match = hash_a == hash_b

        pair: Dict[str, Any] = {
            "label": label,
            "run_a": {"path": str(path_a), "sha256": hash_a},
            "run_b": {"path": str(path_b), "sha256": hash_b},
            "match": match,
        }
        pairs.append(pair)
        if not match:
            mismatches.append(label)

    pairs_checked = len(pairs)
    pairs_matching = sum(1 for p in pairs if p["match"])

    seed_ok = seed_a is not None and seed_a == seed_b
    overall_ok = seed_ok and not mismatches and not errors

    return {
        "status": "success" if overall_ok else "failed",
        "train_determinism_status": "success" if overall_ok else "failed",
        "seed_a": seed_a,
        "seed_b": seed_b,
        "seeds_match": seed_ok,
        "pairs_checked": pairs_checked,
        "pairs_matching": pairs_matching,
        "mismatches": mismatches,
        "errors": errors,
        "pairs": pairs,
        "run_dir_a": str(run_dir_a),
        "run_dir_b": str(run_dir_b),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify ML Deformer training determinism by comparing two run dirs.")
    ap.add_argument("--run-dir-a", required=True, help="First run directory")
    ap.add_argument("--run-dir-b", required=True, help="Second run directory (same seed)")
    ap.add_argument("--out", default="", help="Output report JSON path (optional)")
    args = ap.parse_args()

    run_a = Path(args.run_dir_a)
    run_b = Path(args.run_dir_b)

    try:
        result = _compare_runs(run_a, run_b)
    except Exception as exc:
        result = {
            "status": "failed",
            "train_determinism_status": "failed",
            "error": str(exc),
        }

    out_str = json.dumps(result, ensure_ascii=True, indent=2)
    print(out_str)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(out_str, encoding="utf-8")
        print(f"[determinism] report written: {out_path}", file=sys.stderr)

    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
