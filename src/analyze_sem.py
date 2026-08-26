#!/usr/bin/env python3
"""Prepare SEM micrographs for DiameterJ and create an independent diameter QC.

The generated binary TIFFs (black fibers on a white background) can be opened
directly by DiameterJ.  The Python diameter estimate is deliberately labelled
as QC; report DiameterJ's output as the primary result.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np
import pandas as pd
import tifffile
from PIL import Image
from scipy import ndimage as ndi
from skimage import exposure, filters, morphology

from run_diameterj_batch import DEFAULT_FIJI, VENDOR_MACRO, run_diameterj
from run_diameterj_segmentation import run_fiji_segmentation


METHODS = ("otsu", "li", "yen", "triangle")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, default=Path("data"), help="TIFF file or directory")
    p.add_argument("--output", type=Path, default=Path("results"))
    p.add_argument("--method", choices=METHODS, default="otsu")
    p.add_argument("--all-methods", action="store_true", help="write one candidate per global threshold")
    p.add_argument(
        "--segmentation",
        choices=("python", "traditional", "mixed", "srm", "all"),
        default="python",
        help="segmentation workflow; Fiji modes generate all methods in that family",
    )
    p.add_argument("--crop-bottom", type=int, default=59, help="instrument footer height in pixels")
    p.add_argument("--hfw-um", type=float, default=27.04, help="horizontal field width in micrometres")
    p.add_argument("--pixel-size-um", type=float, help="override HFW-derived calibration")
    p.add_argument("--sigma", type=float, default=1.0, help="Gaussian denoising sigma")
    p.add_argument("--min-object-px", type=int, default=25)
    p.add_argument("--min-hole-px", type=int, default=25)
    p.add_argument(
        "--srm-q", type=int, default=100,
        help="SRM granularity for Mixed and SRM segmentation; default 100",
    )
    p.add_argument("--invert", action="store_true", help="use when fibers are darker than background")
    p.add_argument("--skip-diameterj", action="store_true", help="create masks/QC only")
    p.add_argument("--fiji", type=Path, default=DEFAULT_FIJI)
    p.add_argument("--diameterj-macro", type=Path, default=VENDOR_MACRO)
    p.add_argument(
        "--headless", action="store_true",
        help="experimental: legacy AnalyzeSkeleton may fail without a GUI",
    )
    return p.parse_args()


def input_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted({*path.glob("*.tif"), *path.glob("*.tiff"), *path.glob("*.TIF"), *path.glob("*.TIFF")})


def threshold_value(image: np.ndarray, method: str) -> float:
    return {
        "otsu": filters.threshold_otsu,
        "li": filters.threshold_li,
        "yen": filters.threshold_yen,
        "triangle": filters.threshold_triangle,
    }[method](image)


def overlay(gray: np.ndarray, mask: np.ndarray) -> np.ndarray:
    base = np.round(255 * exposure.rescale_intensity(gray, out_range=(0, 1))).astype(np.uint8)
    rgb = np.repeat(base[..., None], 3, axis=2)
    edge = mask ^ morphology.binary_erosion(mask)
    rgb[edge] = (255, 32, 32)
    return rgb


def process(path: Path, args: argparse.Namespace, method: str) -> dict[str, object]:
    raw = tifffile.imread(path)
    if raw.ndim == 3:
        raw = raw[..., :3].mean(axis=-1)
    if raw.ndim != 2:
        raise ValueError(f"{path}: expected a 2-D image, got shape {raw.shape}")
    if not 0 <= args.crop_bottom < raw.shape[0]:
        raise ValueError("--crop-bottom must be non-negative and smaller than image height")

    image = raw[: raw.shape[0] - args.crop_bottom or None].astype(np.float32)
    image = exposure.rescale_intensity(image, out_range=(0.0, 1.0))
    enhanced = exposure.equalize_adapthist(image, clip_limit=0.01)
    smooth = filters.gaussian(enhanced, sigma=args.sigma, preserve_range=True)
    threshold = float(threshold_value(smooth, method))
    mask = smooth < threshold if args.invert else smooth > threshold
    mask = morphology.remove_small_objects(mask, min_size=args.min_object_px)
    mask = morphology.remove_small_holes(mask, area_threshold=args.min_hole_px)

    px_um = args.pixel_size_um if args.pixel_size_um else args.hfw_um / raw.shape[1]
    skeleton = morphology.skeletonize(mask)
    distance = ndi.distance_transform_edt(mask)
    diam_px = 2.0 * distance[skeleton]
    diam_um = diam_px * px_um

    stem = f"{path.stem}__{method}"
    args.output.mkdir(parents=True, exist_ok=True)
    # DiameterJ v1.018 counts zero-valued pixels as fiber area and performs its
    # own inversion before skeletonization.
    mask_path = args.output / f"{stem}.tif"
    # DiameterJ v1.018/ImageJ 1.51w interprets the TIFF photometric tag when it
    # restores the threshold used by particle analysis. WhiteIsZero matches
    # the validated DiameterJ mask convention and produces the full pore map.
    tifffile.imwrite(mask_path, (~mask).astype(np.uint8) * 255, photometric="miniswhite")
    Image.fromarray(overlay(image, mask)).save(args.output / f"{stem}_overlay.png")
    pd.DataFrame({"diameter_px": diam_px, "diameter_um": diam_um}).to_csv(
        args.output / f"{stem}_diameters.csv", index=False
    )

    return {
        "source": str(path), "method": method, "width_px": raw.shape[1],
        "analysis_height_px": image.shape[0], "crop_bottom_px": args.crop_bottom,
        "pixel_size_um": px_um, "threshold": threshold,
        "fiber_area_fraction": float(mask.mean()), "skeleton_samples": int(diam_um.size),
        "qc_mean_diameter_um": float(np.mean(diam_um)) if diam_um.size else np.nan,
        "qc_median_diameter_um": float(np.median(diam_um)) if diam_um.size else np.nan,
        "qc_std_diameter_um": float(np.std(diam_um, ddof=1)) if diam_um.size > 1 else np.nan,
        "mask_path": str(mask_path),
    }


def summarize_fiji_mask(
    source: Path, mask_path: Path, family: str, method: str, args: argparse.Namespace
) -> dict[str, object]:
    raw = tifffile.imread(source)
    if raw.ndim == 3:
        raw = raw[..., :3].mean(axis=-1)
    image = raw[: raw.shape[0] - args.crop_bottom or None].astype(np.float32)
    image = exposure.rescale_intensity(image, out_range=(0.0, 1.0))
    pixels = tifffile.imread(mask_path)
    mask = pixels == np.min(pixels)
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
        "source": str(source), "method": f"{family}:{method}", "width_px": raw.shape[1],
        "analysis_height_px": image.shape[0], "crop_bottom_px": args.crop_bottom,
        "pixel_size_um": px_um, "threshold": np.nan,
        "fiber_area_fraction": float(mask.mean()), "skeleton_samples": int(diam_um.size),
        "qc_mean_diameter_um": float(np.mean(diam_um)) if diam_um.size else np.nan,
        "qc_median_diameter_um": float(np.median(diam_um)) if diam_um.size else np.nan,
        "qc_std_diameter_um": float(np.std(diam_um, ddof=1)) if diam_um.size > 1 else np.nan,
        "mask_path": str(mask_path),
    }


def main() -> None:
    args = parse_args()
    files = input_files(args.input)
    if not files:
        raise SystemExit(f"No TIFF images found at {args.input}")
    args.output.mkdir(parents=True, exist_ok=True)
    if args.segmentation == "python":
        methods = METHODS if args.all_methods else (args.method,)
        rows = [process(path, args, method) for path in files for method in methods]
    else:
        if args.all_methods:
            raise SystemExit("--all-methods applies only to --segmentation python")
        rows = []
        for path in files:
            masks = run_fiji_segmentation(
                path, args.output, args.segmentation, args.crop_bottom, args.srm_q, args.fiji
            )
            rows.extend(
                summarize_fiji_mask(path, mask_path, family, method, args)
                for mask_path, family, method in masks
            )
    with (args.output / "python_qc_summary.csv").open("w", newline="", encoding="utf-8") as handle:
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
            # recorded in python_qc_summary.csv for post-analysis conversion.
            pixel_size_um=None,
            fiji=args.fiji,
            macro=args.diameterj_macro,
            headless=args.headless,
            images=[Path(row["mask_path"]) for row in rows],
        )


if __name__ == "__main__":
    main()
