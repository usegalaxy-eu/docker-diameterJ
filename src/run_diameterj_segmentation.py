#!/usr/bin/env python3
"""Run Fiji Auto Threshold workflows used by the DiameterJ container."""

import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

import numpy as np
import tifffile
from PIL import Image, ImageDraw, ImageFont, ImageOps

from run_diameterj_batch import DEFAULT_FIJI, ij_quote


AUTO_THRESHOLD_METHODS = (
    ("Default", "default"),
    ("Huang", "huang"),
    ("Huang2", "huang2"),
    ("Intermodes", "intermodes"),
    ("IsoData", "isodata"),
    ("Li", "li"),
    ("MaxEntropy", "maxentropy"),
    ("Mean", "mean"),
    ("MinError(I)", "minerror"),
    ("Minimum", "minimum"),
    ("Moments", "moments"),
    ("Otsu", "otsu"),
    ("Percentile", "percentile"),
    ("RenyiEntropy", "renyientropy"),
    ("Shanbhag", "shanbhag"),
    ("Triangle", "triangle"),
    ("Yen", "yen"),
)

FIJI_MODES = (
    "auto-thresholding",
    "recursive-srm",
    "srm-auto-thresholding",
    "all",
)


def workflow_candidates(mode: str, srm_q: int) -> list[dict[str, object]]:
    """Describe every output mask in deterministic montage/export order."""
    q_half = max(1, srm_q // 2)
    q_quarter = max(1, srm_q // 4)
    q_eighth = max(1, srm_q // 8)
    candidates: list[dict[str, object]] = []

    if mode in {"auto-thresholding", "all"}:
        for display, slug in AUTO_THRESHOLD_METHODS:
            candidates.append(
                {
                    "family": "auto_thresholding",
                    "method": slug,
                    "display": f"Auto Thresholding: {display}",
                    "srm": (),
                    "fiji_method": display,
                }
            )

    if mode in {"recursive-srm", "all"}:
        sequences = ((srm_q, q_half, q_quarter, q_eighth),)
        for sequence in sequences:
            levels = "_".join(str(q) for q in sequence)
            label_levels = " -> ".join(f"q={q}" for q in sequence)
            for display, slug in AUTO_THRESHOLD_METHODS:
                candidates.append(
                    {
                        "family": "recursive_srm",
                        "method": f"q{levels}_{slug}",
                        "display": f"Recursive SRM {label_levels}: {display}",
                        "srm": sequence,
                        "fiji_method": display,
                    }
                )

    if mode in {"srm-auto-thresholding", "all"}:
        for display, slug in AUTO_THRESHOLD_METHODS:
            candidates.append(
                {
                    "family": "srm_auto_thresholding",
                    "method": f"q{srm_q}_{slug}",
                    "display": f"SRM q={srm_q} + Auto Thresholding: {display}",
                    "srm": (srm_q,),
                    "fiji_method": display,
                }
            )

    return candidates


def build_segmentation_macro(
    image: Path,
    output_dir: Path,
    width: int,
    analysis_height: int,
    candidates: list[dict[str, object]],
) -> str:
    """Build a non-interactive Fiji macro for the selected workflows."""
    lines = [
        "setBatchMode(true);",
        f'input_path = "{ij_quote(image.resolve().as_posix())}";',
        "output_dir = \""
        + ij_quote(output_dir.resolve().as_posix().rstrip("/") + "/")
        + "\";",
        "File.makeDirectory(output_dir);",
    ]
    sequences = list(
        dict.fromkeys(
            tuple(candidate["srm"]) for candidate in candidates if candidate["srm"]
        )
    )
    sequence_paths: dict[tuple[object, ...], str] = {}
    for index, sequence in enumerate(sequences, start=1):
        path = f"srm_source_{index:02d}.tif"
        sequence_paths[sequence] = path
        lines.extend(
            [
                "open(input_path);",
                'run("Set Scale...", "distance=0 known=0 pixel=1 unit=pixels");',
                f"makeRectangle(0, 0, {width}, {analysis_height});",
                'run("Crop");',
            ]
        )
        for q_index, q in enumerate(sequence):
            lines.extend(
                [
                    f'run("Statistical Region Merging", "q={q} showaverages");',
                    'run("8-bit");',
                    f'File.delete(output_dir + "{path}");',
                    f'saveAs("Tiff", output_dir + "{path}");',
                    'run("Close All");',
                ]
            )
            if q_index < len(sequence) - 1:
                lines.append(f'open(output_dir + "{path}");')
    cleanup = [
        "getHistogram(values, counts, 256);",
        "previous = counts[255];",
        "do {",
        "    current = previous;",
        '    run("Despeckle");',
        "    getHistogram(values, counts, 256);",
        "    previous = counts[255];",
        "} while (previous != current);",
        'run("Remove Outliers...", "radius=3 threshold=50 which=Dark");',
        'run("Remove Outliers...", "radius=3 threshold=50 which=Bright");',
        'run("Remove Outliers...", "radius=3 threshold=50 which=Dark");',
        'run("Remove Outliers...", "radius=3 threshold=50 which=Bright");',
        'run("Erode");',
        'run("Dilate");',
        'run("Fill Holes");',
        "getHistogram(values, counts, 256);",
        "white_before = counts[255];",
        'run("Make Binary");',
        "getHistogram(values, counts, 256);",
        "white_after = counts[255];",
        'if (white_before == white_after) run("Invert");',
    ]

    for index, candidate in enumerate(candidates, start=1):
        sequence = tuple(candidate["srm"])
        source = (
            f'output_dir + "{sequence_paths[sequence]}"' if sequence else "input_path"
        )
        lines.extend(
            [
                f"open({source});",
                'run("Set Scale...", "distance=0 known=0 pixel=1 unit=pixels");',
            ]
        )
        if not sequence:
            lines.extend(
                [
                    f"makeRectangle(0, 0, {width}, {analysis_height});",
                    'run("Crop");',
                ]
            )
        method = candidate["fiji_method"]
        lines.append(
            f'run("Auto Threshold", "method={method} ignore_white white");'
        )
        lines.extend(cleanup)
        lines.extend(
            [
                f'saveAs("Tiff", output_dir + "mask_{index:02d}.tif");',
                'run("Close All");',
            ]
        )
    lines.extend(["setBatchMode(false);", 'eval("script", "System.exit(0);");'])
    return "\n".join(lines) + "\n"


def _original_panel(image: Path, analysis_height: int) -> Image.Image:
    pixels = tifffile.imread(image)[:analysis_height]
    if pixels.ndim == 3:
        pixels = pixels[..., :3].mean(axis=-1)
    pixels = pixels.astype(np.float32)
    low, high = float(np.min(pixels)), float(np.max(pixels))
    if high > low:
        pixels = (pixels - low) * (255.0 / (high - low))
    else:
        pixels = np.zeros_like(pixels)
    return Image.fromarray(np.round(pixels).astype(np.uint8))


def create_montage(
    original: Path,
    masks: list[Path],
    labels: list[str],
    destination: Path,
    analysis_height: int,
) -> None:
    """Write a labelled PNG review sheet containing the original and masks."""
    panels = [_original_panel(original, analysis_height)] + [
        Image.open(mask).convert("L") for mask in masks
    ]
    panels = [ImageOps.colorize(panel, "black", "white") for panel in panels]
    _write_montage(panels, ["Original"] + labels, destination)


def create_overlay_montage(
    original: Path,
    overlays: list[Path],
    labels: list[str],
    destination: Path,
    analysis_height: int,
) -> None:
    """Write a labelled PNG review sheet containing every boundary overlay."""
    original_panel = ImageOps.colorize(
        _original_panel(original, analysis_height), "black", "white"
    )
    panels = [original_panel] + [Image.open(path).convert("RGB") for path in overlays]
    _write_montage(panels, ["Original"] + labels, destination)


def _write_montage(
    panels: list[Image.Image], panel_labels: list[str], destination: Path
) -> None:
    """Lay out equally sized RGB panels with readable labels."""
    width, height = panels[0].size
    font_size = max(24, min(40, height // 20))
    font = ImageFont.load_default(size=font_size)
    label_height = font_size + 16
    columns = math.ceil(math.sqrt(len(panels)))
    rows = math.ceil(len(panels) / columns)
    montage_size = (columns * width, rows * (height + label_height))
    montage = Image.new("RGB", montage_size, "black")
    draw = ImageDraw.Draw(montage)
    for index, (panel, label) in enumerate(zip(panels, panel_labels)):
        x = (index % columns) * width
        y = (index // columns) * (height + label_height)
        montage.paste(panel, (x, y))
        label_box = (x, y + height, x + width, y + height + label_height)
        draw.rectangle(label_box, fill="black")
        label_font = font
        label_font_size = font_size
        while (
            draw.textbbox((0, 0), label, font=label_font)[2] > width - 16
            and label_font_size > 20
        ):
            label_font_size -= 2
            label_font = ImageFont.load_default(size=label_font_size)
        draw.text(
            (x + 8, y + height + 6),
            label,
            fill=(255, 64, 64),
            font=label_font,
            stroke_width=1,
            stroke_fill="black",
        )
    montage.save(destination)


def run_fiji_segmentation(
    image: Path,
    output_dir: Path,
    mode: str,
    crop_bottom: int,
    srm_q: int,
    fiji: Path = DEFAULT_FIJI,
) -> list[tuple[Path, str, str]]:
    """Return generated mask path, family, and method tuples."""
    pixels = tifffile.imread(image)
    height, width = pixels.shape[:2]
    if not 0 <= crop_bottom < height:
        raise SystemExit(
            "--crop-bottom must be non-negative and smaller than image height"
        )
    if srm_q <= 0:
        raise SystemExit("--srm-q must be positive")
    if mode not in FIJI_MODES:
        raise SystemExit(f"Unsupported Fiji segmentation mode: {mode}")
    if not fiji.is_file():
        raise SystemExit("Local Fiji executable not found")

    analysis_height = height - crop_bottom
    candidates = workflow_candidates(mode, srm_q)
    work_dir = Path(tempfile.mkdtemp(prefix=".diameterj_segment_", dir=output_dir))
    try:
        generated = work_dir / "generated_diameterj_segment.ijm"
        generated.write_text(
            build_segmentation_macro(
                image, work_dir, width, analysis_height, candidates
            )
        )
        expected = [
            work_dir / f"mask_{index:02d}.tif"
            for index in range(1, len(candidates) + 1)
        ]
        command = [str(fiji), "-macro", str(generated)]
        process = subprocess.Popen(command)
        deadline = time.monotonic() + float(
            os.environ.get("DIAMETERJ_TIMEOUT_SECONDS", "3600")
        )
        try:
            while not all(
                path.is_file() and path.stat().st_size > 0 for path in expected
            ):
                returncode = process.poll()
                if returncode is not None:
                    raise subprocess.CalledProcessError(returncode, command)
                if time.monotonic() >= deadline:
                    raise TimeoutError("Fiji segmentation timed out")
                time.sleep(0.5)
            time.sleep(1.0)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

        results = []
        png_masks = []
        labels = []
        for source_mask, candidate in zip(expected, candidates):
            family = str(candidate["family"])
            method = str(candidate["method"])
            destination = output_dir / f"{image.stem}__{family}_{method}.tif"
            shutil.copy2(source_mask, destination)
            mask_pixels = tifffile.imread(source_mask)
            png = destination.with_suffix(".png")
            Image.fromarray(255 - mask_pixels).save(png)
            results.append((destination, family, method))
            png_masks.append(png)
            labels.append(str(candidate["display"]))

        create_montage(
            image,
            png_masks,
            labels,
            output_dir / f"{image.stem}__{mode}_segmentation_montage.png",
            analysis_height,
        )
        return results
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
