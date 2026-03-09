from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build side-by-side review sheets for selected frame windows.")
    parser.add_argument("--run-dir", required=True, help="Isolated run directory containing workspace/staging/smoke/gt")
    parser.add_argument(
        "--windows",
        nargs="+",
        required=True,
        help="Frame windows in start-end form, inclusive. Example: 588-597 100-199",
    )
    parser.add_argument(
        "--stride",
        type=int,
        default=1,
        help="Optional stride inside each window. Default keeps every frame.",
    )
    parser.add_argument(
        "--thumb-width",
        type=int,
        default=320,
        help="Thumbnail width for each panel.",
    )
    return parser.parse_args()


def frame_path(directory: Path, frame_index: int) -> Path:
    return directory / f".{frame_index:04d}.png"


def heatmap_path(directory: Path, frame_index: int) -> Path | None:
    candidates = [
        directory / f"frame_{frame_index:04d}.png",
        directory / f".{frame_index:04d}.png",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def parse_window(text: str) -> tuple[int, int]:
    start_text, end_text = text.split("-", 1)
    start = int(start_text)
    end = int(end_text)
    if end < start:
        raise ValueError(f"Invalid window: {text}")
    return start, end


def load_panel(path: Path, thumb_width: int) -> Image.Image:
    image = Image.open(path).convert("RGB")
    scale = thumb_width / image.width
    thumb_height = max(1, int(image.height * scale))
    return image.resize((thumb_width, thumb_height), Image.Resampling.LANCZOS)


def placeholder_panel(width: int, height: int, text: str) -> Image.Image:
    image = Image.new("RGB", (width, height), color=(36, 40, 48))
    draw = ImageDraw.Draw(image)
    draw.text((16, max(16, height // 2 - 8)), text, fill=(210, 214, 220))
    return image


def build_sheet(run_dir: Path, start: int, end: int, stride: int, thumb_width: int) -> Path:
    gt_root = run_dir / "workspace" / "staging" / "smoke" / "gt"
    reference_dir = gt_root / "reference" / "frames"
    source_dir = gt_root / "source" / "frames"
    heatmap_dir = gt_root / "compare" / "heatmaps"

    frames = list(range(start, end + 1, stride))
    rows: list[tuple[int, Image.Image, Image.Image, Image.Image]] = []

    for frame_index in frames:
        reference = frame_path(reference_dir, frame_index)
        source = frame_path(source_dir, frame_index)
        heatmap = heatmap_path(heatmap_dir, frame_index)
        if not (reference.exists() and source.exists()):
            continue
        reference_image = load_panel(reference, thumb_width)
        source_image = load_panel(source, thumb_width)
        heatmap_image = load_panel(heatmap, thumb_width) if heatmap else placeholder_panel(reference_image.width, reference_image.height, "heatmap not exported")
        rows.append(
            (
                frame_index,
                reference_image,
                source_image,
                heatmap_image,
            )
        )

    if not rows:
        raise FileNotFoundError(f"No complete frame triplets found for window {start}-{end}")

    label_width = 120
    gutter = 16
    row_height = rows[0][1].height
    title_height = 56
    sheet_width = label_width + (thumb_width * 3) + (gutter * 4)
    sheet_height = title_height + len(rows) * (row_height + gutter) + gutter

    sheet = Image.new("RGB", (sheet_width, sheet_height), color=(14, 16, 20))
    draw = ImageDraw.Draw(sheet)
    draw.text((gutter, 16), f"Frame review {start}-{end} | columns: reference / source / heatmap", fill=(235, 238, 242))

    column_x = [label_width + gutter, label_width + gutter * 2 + thumb_width, label_width + gutter * 3 + thumb_width * 2]
    column_labels = ["reference", "source", "heatmap"]
    for index, label in enumerate(column_labels):
        draw.text((column_x[index], 36), label, fill=(170, 176, 184))

    for row_index, (frame_index, reference, source, heatmap) in enumerate(rows):
        top = title_height + row_index * (row_height + gutter)
        draw.text((gutter, top + row_height // 2 - 8), f"{frame_index:04d}", fill=(235, 238, 242))
        for column_index, image in enumerate((reference, source, heatmap)):
            left = column_x[column_index]
            sheet.paste(image, (left, top))

    out_dir = run_dir / "reports" / "review_sheets"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"review_{start:04d}_{end:04d}.png"
    sheet.save(out_path)
    return out_path


def main() -> None:
    args = parse_args()
    run_dir = Path(args.run_dir)
    outputs = []
    for window_text in args.windows:
        start, end = parse_window(window_text)
        outputs.append(build_sheet(run_dir, start, end, args.stride, args.thumb_width))
    for output in outputs:
        print(output)


if __name__ == "__main__":
    main()