#!/usr/bin/env python3
"""Segment SEM micrographs with Fiji and run DiameterJ with independent QC.

Fiji generates binary TIFF candidates using the selected segmentation family.
DiameterJ remains the primary measurement workflow.
"""

import argparse
import csv
from pathlib import Path

import numpy as np
import pandas as pd
import tifffile
from PIL import Image
from scipy import ndimage as ndi
from skimage import exposure, morphology

from run_diameterj_batch import DEFAULT_FIJI, VENDOR_MACRO, run_diameterj
from run_diameterj_segmentation import (
    AUTO_THRESHOLD_METHODS,
    create_overlay_montage,
    run_fiji_segmentation,
    workflow_candidates,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--input", type=Path, default=Path("data"), help="TIFF file or directory"
    )
    p.add_argument("--output", type=Path, default=Path("results"))
    p.add_argument(
        "--segmentation",
        choices=(
            "auto-thresholding",
            "recursive-srm",
            "srm-auto-thresholding",
            "all",
        ),
        default="auto-thresholding",
        help="Fiji segmentation workflow",
    )
    p.add_argument(
        "--threshold-methods",
        action="append",
        metavar="METHOD[,METHOD...]",
        help=(
            "threshold method slug(s) to run; repeat the option or provide a "
            "comma-separated Galaxy multi-select value (default: all 17). "
            "Available: " + ", ".join(slug for _, slug in AUTO_THRESHOLD_METHODS)
        ),
    )
    p.add_argument(
        "--crop-bottom", type=int, default=59, help="instrument footer height in pixels"
    )
    p.add_argument(
        "--hfw-um",
        type=float,
        default=27.04,
        help="horizontal field width in micrometres",
    )
    p.add_argument(
        "--pixel-size-um", type=float, help="override HFW-derived calibration"
    )
    p.add_argument(
        "--srm-q",
        type=int,
        default=100,
        help=(
            "SRM granularity for Recursive SRM and SRM with Auto Thresholding; "
            "default 100"
        ),
    )
    p.add_argument("--skip-diameterj", action="store_true", help="create masks/QC only")
    p.add_argument("--fiji", type=Path, default=DEFAULT_FIJI)
    p.add_argument("--diameterj-macro", type=Path, default=VENDOR_MACRO)
    p.add_argument(
        "--headless",
        action="store_true",
        help="experimental: legacy AnalyzeSkeleton may fail without a GUI",
    )
    return p.parse_args()


def input_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(
        {
            *path.glob("*.tif"),
            *path.glob("*.tiff"),
            *path.glob("*.TIF"),
            *path.glob("*.TIFF"),
        }
    )


def overlay(gray: np.ndarray, mask: np.ndarray) -> np.ndarray:
    base = np.round(255 * exposure.rescale_intensity(gray, out_range=(0, 1))).astype(
        np.uint8
    )
    rgb = np.repeat(base[..., None], 3, axis=2)
    edge = mask ^ morphology.binary_erosion(mask)
    rgb[edge] = (255, 32, 32)
    return rgb


def summarize_fiji_mask(
    source: Path, mask_path: Path, family: str, method: str, args: argparse.Namespace
) -> dict[str, object]:
    raw = tifffile.imread(source)
    if raw.ndim == 3:
        raw = raw[..., :3].mean(axis=-1)
    image = raw[: raw.shape[0] - args.crop_bottom or None].astype(np.float32)
    image = exposure.rescale_intensity(image, out_range=(0.0, 1.0))
    with tifffile.TiffFile(mask_path) as tif:
        pixels = tif.asarray()
        photometric = tif.pages[0].photometric
    fiber_value = (
        np.max(pixels)
        if photometric == tifffile.PHOTOMETRIC.MINISWHITE
        else np.min(pixels)
    )
    mask = pixels == fiber_value
    px_um = args.pixel_size_um if args.pixel_size_um else args.hfw_um / raw.shape[1]
    skeleton = morphology.skeletonize(mask)
    distance = ndi.distance_transform_edt(mask)
    diam_px = 2.0 * distance[skeleton]
    diam_um = diam_px * px_um
    stem = mask_path.stem
    Image.fromarray(overlay(image, mask)).save(args.output / f"{stem}_overlay.png")
    pd.DataFrame({"diameter_px": diam_px, "diameter_um": diam_um}).to_csv(
        args.output / f"{stem}_diameters.csv", index=False
    )
    return {
        "source": str(source),
        "method": f"{family}:{method}",
        "width_px": raw.shape[1],
        "analysis_height_px": image.shape[0],
        "crop_bottom_px": args.crop_bottom,
        "pixel_size_um": px_um,
        "threshold": np.nan,
        "fiber_area_fraction": float(mask.mean()),
        "skeleton_samples": int(diam_um.size),
        "qc_mean_diameter_um": float(np.mean(diam_um)) if diam_um.size else np.nan,
        "qc_median_diameter_um": float(np.median(diam_um)) if diam_um.size else np.nan,
        "qc_std_diameter_um": (
            float(np.std(diam_um, ddof=1)) if diam_um.size > 1 else np.nan
        ),
        "mask_path": str(mask_path),
    }


def main() -> None:
    args = parse_args()
    files = input_files(args.input)
    if not files:
        raise SystemExit(f"No TIFF images found at {args.input}")
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in files:
        masks = run_fiji_segmentation(
            path,
            args.output,
            args.segmentation,
            args.crop_bottom,
            args.srm_q,
            args.fiji,
            args.threshold_methods,
        )
        image_rows = [
            summarize_fiji_mask(path, mask_path, family, method, args)
            for mask_path, family, method in masks
        ]
        rows.extend(image_rows)
        overlays = [
            args.output / f"{mask_path.stem}_overlay.png"
            for mask_path, _, _ in masks
        ]
        labels = [
            str(candidate["display"])
            for candidate in workflow_candidates(
                args.segmentation, args.srm_q, args.threshold_methods
            )
        ]
        source_pixels = tifffile.imread(path)
        create_overlay_montage(
            path,
            overlays,
            labels,
            args.output / f"{path.stem}__{args.segmentation}_overlay_montage.png",
            source_pixels.shape[0] - args.crop_bottom,
        )
    with (args.output / "qc_summary.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Prepared {len(rows)} mask(s) in {args.output.resolve()}")
    if not args.skip_diameterj:
        run_diameterj(
            args.output,
            # DiameterJ v1.018 is validated in native pixel mode. Applying a
            # physical scale before its particle analysis changes legacy size
            # filtering and can collapse the pore result. Calibration remains
            # recorded in qc_summary.csv for post-analysis conversion.
            pixel_size_um=None,
            fiji=args.fiji,
            macro=args.diameterj_macro,
            headless=args.headless,
            images=[Path(row["mask_path"]) for row in rows],
        )


if __name__ == "__main__":
    main()
