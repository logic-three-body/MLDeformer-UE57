#!/usr/bin/env python3
"""Summarize Phase W focus windows from a gt_compare report.

This script is intentionally lightweight and reusable for future reruns.
It reads the existing gt_compare report, recomputes exact metrics for the
windows and frames we care about in Phase W, and writes both JSON and
Markdown summaries for W-3 decision making.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import numpy as np

from compare_groundtruth import (
    _body_roi,
    _delta_e_2000_mean,
    _edge_iou,
    _load_gray,
    _load_rgb,
    _ms_ssim,
    _psnr,
    _psnr_color,
    _ssim_color,
    _ssim_global,
)


DEFAULT_FOCUS_RANGES = (
    (588, 597),
    (100, 199),
    (500, 599),
    (600, 699),
    (1000, 1099),
    (1200, 1299),
)
DEFAULT_FOCUS_FRAMES = (588, 589, 590, 591, 592, 593, 594, 595, 596, 597, 1054)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze Phase W focus windows from gt_compare output")
    parser.add_argument("--gt-compare-report", required=True)
    parser.add_argument("--out-json", default="")
    parser.add_argument("--out-md", default="")
    parser.add_argument(
        "--focus-ranges",
        nargs="*",
        default=[],
        help="Optional ranges like 588-597 100-199. Uses Phase W defaults when omitted.",
    )
    parser.add_argument(
        "--focus-frames",
        nargs="*",
        default=[],
        help="Optional frame indices like 1054 591. Uses Phase W defaults when omitted.",
    )
    return parser.parse_args()


def _parse_ranges(raw_values: Iterable[str]) -> List[Tuple[int, int]]:
    parsed: List[Tuple[int, int]] = []
    for raw in raw_values:
        value = str(raw).strip()
        if not value:
            continue
        if "-" not in value:
            frame = int(value)
            parsed.append((frame, frame))
            continue
        lhs, rhs = value.split("-", 1)
        start = int(lhs)
        end = int(rhs)
        if end < start:
            start, end = end, start
        parsed.append((start, end))
    return parsed


def _parse_frames(raw_values: Iterable[str]) -> List[int]:
    frames: List[int] = []
    for raw in raw_values:
        value = str(raw).strip()
        if not value:
            continue
        frames.append(int(value))
    return frames


def _load_report(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Invalid report payload: {path}")
    return payload


def _report_outputs(payload: Dict[str, Any]) -> Dict[str, Any]:
    outputs = payload.get("outputs", payload)
    if not isinstance(outputs, dict):
        raise RuntimeError("gt_compare report does not contain an outputs object")
    return outputs


def _find_frame_path(frames_dir: Path, frame_index: int) -> Path:
    candidates = sorted(frames_dir.rglob(f"*{frame_index:04d}.png"))
    if not candidates:
        raise FileNotFoundError(f"Frame {frame_index:04d} not found under {frames_dir}")
    return candidates[0]


def _compute_frame_metrics(ref_path: Path, src_path: Path) -> Dict[str, Any]:
    ref_gray = _load_gray(ref_path)
    src_gray = _load_gray(src_path)
    ref_rgb = _load_rgb(ref_path)
    src_rgb = _load_rgb(src_path)
    ref_roi = _body_roi(ref_gray)
    src_roi = _body_roi(src_gray)

    return {
        "reference": str(ref_path.resolve()),
        "source": str(src_path.resolve()),
        "ssim": float(_ssim_global(ref_gray, src_gray)),
        "psnr": float(_psnr(ref_gray, src_gray)),
        "edge_iou": float(_edge_iou(ref_gray, src_gray)),
        "body_roi_ssim": float(_ssim_global(ref_roi, src_roi)),
        "body_roi_psnr": float(_psnr(ref_roi, src_roi)),
        "color_ssim": float(_ssim_color(ref_rgb, src_rgb)),
        "color_psnr": float(_psnr_color(ref_rgb, src_rgb)),
        "ms_ssim": float(_ms_ssim(ref_rgb, src_rgb)),
        "de2000": float(_delta_e_2000_mean(ref_rgb, src_rgb)),
    }


def _aggregate_frame_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {"count": 0}

    def arr(key: str) -> np.ndarray:
        return np.asarray([float(row[key]) for row in rows], dtype=np.float64)

    ssim = arr("ssim")
    psnr = arr("psnr")
    edge = arr("edge_iou")
    roi_ssim = arr("body_roi_ssim")
    roi_psnr = arr("body_roi_psnr")
    color_ssim = arr("color_ssim")
    color_psnr = arr("color_psnr")
    ms_ssim = arr("ms_ssim")
    de2000 = arr("de2000")

    return {
        "count": len(rows),
        "ssim_mean": float(np.mean(ssim)),
        "ssim_min": float(np.min(ssim)),
        "psnr_mean": float(np.mean(psnr)),
        "psnr_min": float(np.min(psnr)),
        "edge_iou_mean": float(np.mean(edge)),
        "body_roi_ssim_mean": float(np.mean(roi_ssim)),
        "body_roi_ssim_min": float(np.min(roi_ssim)),
        "body_roi_psnr_mean": float(np.mean(roi_psnr)),
        "body_roi_psnr_min": float(np.min(roi_psnr)),
        "color_ssim_mean": float(np.mean(color_ssim)),
        "color_psnr_mean": float(np.mean(color_psnr)),
        "ms_ssim_mean": float(np.mean(ms_ssim)),
        "ms_ssim_min": float(np.min(ms_ssim)),
        "de2000_mean": float(np.mean(de2000)),
        "de2000_max": float(np.max(de2000)),
    }


def _cluster_worst_frames(worst_frames: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ordered = sorted(worst_frames, key=lambda row: int(row.get("frame_index", -1)))
    if not ordered:
        return []

    clusters: List[List[Dict[str, Any]]] = [[ordered[0]]]
    for row in ordered[1:]:
        frame_index = int(row["frame_index"])
        prev_index = int(clusters[-1][-1]["frame_index"])
        if frame_index == prev_index + 1:
            clusters[-1].append(row)
        else:
            clusters.append([row])

    out: List[Dict[str, Any]] = []
    for cluster in clusters:
        ssim = np.asarray([float(row["ssim"]) for row in cluster], dtype=np.float64)
        roi = np.asarray([float(row["body_roi_ssim"]) for row in cluster], dtype=np.float64)
        out.append(
            {
                "start_frame": int(cluster[0]["frame_index"]),
                "end_frame": int(cluster[-1]["frame_index"]),
                "count": len(cluster),
                "ssim_mean": float(np.mean(ssim)),
                "body_roi_ssim_mean": float(np.mean(roi)),
            }
        )
    return out


def _window_lookup(windows: List[Dict[str, Any]]) -> Dict[Tuple[int, int], Dict[str, Any]]:
    table: Dict[Tuple[int, int], Dict[str, Any]] = {}
    for row in windows:
        start = int(row.get("start_frame", -1))
        end = int(row.get("end_frame", -1))
        table[(start, end)] = row
    return table


def _top_windows(windows: List[Dict[str, Any]], top_k: int = 5) -> List[Dict[str, Any]]:
    return sorted(
        windows,
        key=lambda row: (
            float(row.get("ssim_mean", 999.0)),
            float(row.get("body_roi_ssim_mean", 999.0)),
            float(row.get("psnr_mean", 999.0)),
        ),
    )[:top_k]


def _make_recommendations(
    overall_metrics: Dict[str, Any],
    top_windows: List[Dict[str, Any]],
    focus_ranges: List[Dict[str, Any]],
    frame_metrics: Dict[str, Dict[str, Any]],
) -> List[str]:
    recommendations: List[str] = []
    ssim_mean = float(overall_metrics.get("ssim_mean", 0.0))
    if ssim_mean < 0.91:
        recommendations.append("Global NMM has not met the 0.91 SSIM gate; avoid another blind global capacity sweep.")

    if top_windows:
        worst = top_windows[0]
        worst_start = int(worst.get("start_frame", -1))
        worst_end = int(worst.get("end_frame", -1))
        recommendations.append(
            f"The lowest-quality region is localized to frames {worst_start:04d}-{worst_end:04d}; prioritize a localized strategy before more global tuning."
        )

    focus_1000 = next((row for row in focus_ranges if row["start_frame"] == 1000 and row["end_frame"] == 1099), None)
    focus_600 = next((row for row in focus_ranges if row["start_frame"] == 600 and row["end_frame"] == 699), None)
    if focus_1000 and focus_600:
        if float(focus_1000["metrics"].get("ssim_mean", 0.0)) > float(focus_600["metrics"].get("ssim_mean", 0.0)) + 0.05:
            recommendations.append(
                "Frame 1054 belongs to a materially better window than 0600-0699, so W-3 visual QC should stay centered on 0588-0597 and 0100-0199."
            )

    frame_1054 = frame_metrics.get("1054")
    if frame_1054:
        if float(frame_1054.get("ssim", 0.0)) >= 0.88:
            recommendations.append(
                "Frame 1054 is a known defect frame but not the dominant metric bottleneck; treat it as secondary visual QA rather than the primary optimization target."
            )

    recommendations.append(
        "Recommended W-3A next step: prepare a constrained Local-mode experiment with an explicit per-bone morph cap, or move to NNM, instead of another Global morph/neurons/iterations increase."
    )
    return recommendations


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _to_markdown(report_path: Path, analysis: Dict[str, Any]) -> str:
    overall = analysis["overall_metrics"]
    lines = [
        "# Phase W Focus Analysis",
        "",
        f"Source report: {report_path}",
        "",
        "## Overall",
        "",
        f"- ssim_mean: {overall.get('ssim_mean', 0.0):.4f}",
        f"- ssim_p05: {overall.get('ssim_p05', 0.0):.4f}",
        f"- body_roi_ssim_mean: {overall.get('body_roi_ssim_mean', 0.0):.4f}",
        f"- psnr_mean: {overall.get('psnr_mean', 0.0):.2f}",
        f"- de2000_mean: {overall.get('de2000_mean', 0.0):.3f}",
        "",
        "## Worst 100-Frame Windows",
        "",
        "| Range | SSIM | Body ROI SSIM | PSNR |",
        "|------|------|----------------|------|",
    ]
    for row in analysis["top_windows_100f"]:
        lines.append(
            f"| {int(row['start_frame']):04d}-{int(row['end_frame']):04d} | {float(row['ssim_mean']):.4f} | {float(row.get('body_roi_ssim_mean', 0.0)):.4f} | {float(row.get('psnr_mean', 0.0)):.2f} |"
        )

    lines.extend([
        "",
        "## Focus Ranges",
        "",
        "| Range | SSIM | Min SSIM | Body ROI SSIM | Min Body ROI SSIM |",
        "|------|------|----------|----------------|-------------------|",
    ])
    for row in analysis["focus_ranges"]:
        metrics = row["metrics"]
        lines.append(
            f"| {int(row['start_frame']):04d}-{int(row['end_frame']):04d} | {float(metrics.get('ssim_mean', 0.0)):.4f} | {float(metrics.get('ssim_min', 0.0)):.4f} | {float(metrics.get('body_roi_ssim_mean', 0.0)):.4f} | {float(metrics.get('body_roi_ssim_min', 0.0)):.4f} |"
        )

    lines.extend([
        "",
        "## Focus Frames",
        "",
        "| Frame | SSIM | Body ROI SSIM | PSNR |",
        "|------|------|----------------|------|",
    ])
    for key, row in analysis["focus_frames"].items():
        lines.append(
            f"| {int(key):04d} | {float(row.get('ssim', 0.0)):.4f} | {float(row.get('body_roi_ssim', 0.0)):.4f} | {float(row.get('psnr', 0.0)):.2f} |"
        )

    lines.extend([
        "",
        "## Worst-Frame Clusters",
        "",
        "| Range | Count | Mean SSIM | Mean Body ROI SSIM |",
        "|------|-------|-----------|--------------------|",
    ])
    for row in analysis["worst_frame_clusters"]:
        lines.append(
            f"| {int(row['start_frame']):04d}-{int(row['end_frame']):04d} | {int(row['count'])} | {float(row['ssim_mean']):.4f} | {float(row['body_roi_ssim_mean']):.4f} |"
        )

    lines.extend(["", "## Recommendations", ""])
    for item in analysis["recommendations"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    report_path = Path(args.gt_compare_report).resolve()
    payload = _load_report(report_path)
    outputs = _report_outputs(payload)

    ref_dir = Path(str(outputs["reference_frames_dir"]))
    src_dir = Path(str(outputs["source_frames_dir"]))
    windows = list(outputs.get("window_metrics_100f", []))
    worst_frames = list(outputs.get("worst_frames", []))
    overall_metrics = dict(outputs.get("metrics", {}))

    focus_ranges = _parse_ranges(args.focus_ranges) or list(DEFAULT_FOCUS_RANGES)
    focus_frames = _parse_frames(args.focus_frames) or list(DEFAULT_FOCUS_FRAMES)

    computed_focus_ranges: List[Dict[str, Any]] = []
    for start_frame, end_frame in focus_ranges:
        rows: List[Dict[str, Any]] = []
        for frame_index in range(start_frame, end_frame + 1):
            ref_path = _find_frame_path(ref_dir, frame_index)
            src_path = _find_frame_path(src_dir, frame_index)
            row = {"frame_index": frame_index}
            row.update(_compute_frame_metrics(ref_path, src_path))
            rows.append(row)
        computed_focus_ranges.append(
            {
                "start_frame": start_frame,
                "end_frame": end_frame,
                "metrics": _aggregate_frame_rows(rows),
            }
        )

    computed_focus_frames: Dict[str, Dict[str, Any]] = {}
    for frame_index in focus_frames:
        ref_path = _find_frame_path(ref_dir, frame_index)
        src_path = _find_frame_path(src_dir, frame_index)
        computed_focus_frames[str(frame_index)] = _compute_frame_metrics(ref_path, src_path)

    analysis = {
        "source_report": str(report_path),
        "overall_metrics": overall_metrics,
        "top_windows_100f": _top_windows(windows, top_k=5),
        "focus_ranges": computed_focus_ranges,
        "focus_frames": computed_focus_frames,
        "worst_frame_clusters": _cluster_worst_frames(worst_frames),
    }
    analysis["recommendations"] = _make_recommendations(
        overall_metrics=overall_metrics,
        top_windows=analysis["top_windows_100f"],
        focus_ranges=computed_focus_ranges,
        frame_metrics=computed_focus_frames,
    )

    out_json = Path(args.out_json) if args.out_json else report_path.with_name("phase_w_focus_analysis.json")
    out_md = Path(args.out_md) if args.out_md else report_path.with_name("phase_w_focus_analysis.md")
    _write_text(out_json, json.dumps(analysis, ensure_ascii=False, indent=2))
    _write_text(out_md, _to_markdown(report_path, analysis))

    print(json.dumps({"out_json": str(out_json.resolve()), "out_md": str(out_md.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())