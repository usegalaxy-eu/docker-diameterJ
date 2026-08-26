#!/usr/bin/env python3
"""Run the original DiameterJ v1.018 Fiji macro without interactive dialogs.

Input must be a directory containing only reviewed binary images (black fibers
on white background). DiameterJ writes its standard Summaries, Histograms,
Diameter Analysis Images, and *_Compare.png outputs beside those images.
"""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from collections.abc import Sequence

import numpy as np
import tifffile


PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_FIJI = PROJECT / "packages/fiji-2017/Fiji.app/ImageJ-linux64"
VENDOR_MACRO = (
    PROJECT / "packages/fiji-2017/Fiji.app/plugins/DiameterJ/DiameterJ_1-018.ijm"
)


def ij_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_macro(source: str, input_dir: Path, pixel_size_um: float | None) -> str:
    marker = 'if(Batch_analysis == "Yes") {'
    marker_at = source.find(marker)
    if marker_at < 0:
        raise RuntimeError("Unsupported DiameterJ macro: batch marker not found")

    scale = pixel_size_um if pixel_size_um is not None else 0.0
    prefix = f"""// Generated non-interactive options; vendor analysis follows.
choice_orien = "None";
unit_conv = "{"Yes" if pixel_size_um is not None else "No"}";
unit_pix = 1;
unit_real = {scale:.12g};
R_Loc = "No";
lowT = 1;
highT = 255;
Batch_analysis = "Yes";
batch_combo = "No";

"""
    generated = prefix + source[marker_at:]
    prompt = 'dir1 = getDirectory("Choose Source Directory");'
    directory = input_dir.resolve().as_posix().rstrip("/") + "/"
    if prompt not in generated:
        raise RuntimeError(
            "Unsupported DiameterJ macro: source-directory prompt not found"
        )
    generated = generated.replace(prompt, f'dir1 = "{ij_quote(directory)}";', 1)
    # v1.018 relies on GUI recorder interpolation for these strings. Explicit
    # concatenation and absolute reopening are required for headless execution.
    generated = generated.replace(
        'run("Set Scale...", "distance=scale_pix known=scale_unit pixel=1 unit=scale_meas");',
        'run("Set Scale...", "distance="+scale_pix+" known="+scale_unit+" pixel=1 unit="+scale_meas);',
    )
    generated = generated.replace("open(name0);", "open(dir1+name0);")
    # Newer AnalyzeSkeleton releases only publish the summary Results table
    # when `show` is explicit. DiameterJ reads that table immediately.
    generated = generated.replace(
        'run("Analyze Skeleton (2D/3D)", "prune=[shortest branch]");',
        'run("Analyze Skeleton (2D/3D)", "prune=[shortest branch] show");',
    )
    generated = generated.replace(
        'run("Analyze Skeleton (2D/3D)", "prune=[shortest branch] show");',
        'setBatchMode(false);\n\t\t\trun("Analyze Skeleton (2D/3D)", "prune=[shortest branch] show");',
    )
    pore_marker = "// Analyzes dark areas from B&W picture to get pores\n"
    if pore_marker not in generated:
        raise RuntimeError(
            "Unsupported DiameterJ macro: pore-analysis marker not found"
        )
    # Keep DiameterJ's inherited 1..255 threshold here. For its expected input
    # convention, the enclosed white components are the regions reported in
    # the pore panel. Inverting or forcing a black threshold instead selects
    # the continuous background and produces an empty-looking result.
    # If excluding edge-touching particles gives a NaN mean, DiameterJ reruns
    # particle analysis without `exclude`. The vendor macro then tries to save
    # the corrected outline over path9, but ImageJ's noninteractive save does
    # not overwrite the first file. That leaves a stale, nearly empty pore
    # panel even though the Results table contains the corrected pore count.
    fallback_save = '\t\t\t\t\tsaveAs("tiff",path9);'
    if fallback_save not in generated:
        raise RuntimeError("Unsupported DiameterJ macro: fallback pore save not found")
    generated = generated.replace(
        fallback_save,
        "\t\t\t\t\tFile.delete(path9);\n" + fallback_save,
        1,
    )
    return generated


def run_diameterj(
    input_dir: Path,
    pixel_size_um: float | None = None,
    fiji: Path = DEFAULT_FIJI,
    macro: Path = VENDOR_MACRO,
    headless: bool = False,
    images: Sequence[Path] | None = None,
) -> Path:
    """Run DiameterJ for binary TIFFs and return its comparison-image directory."""
    if not input_dir.is_dir():
        raise SystemExit(f"Input directory does not exist: {input_dir}")
    selected = (
        list(images)
        if images is not None
        else sorted((*input_dir.glob("*.tif"), *input_dir.glob("*.tiff")))
    )
    images = [Path(image) for image in selected]
    if not images:
        raise SystemExit(f"No TIFF files in {input_dir}")
    if not fiji.is_file() or not macro.is_file():
        raise SystemExit("Local Fiji or DiameterJ macro not found; see README.md")
    if pixel_size_um is not None and pixel_size_um <= 0:
        raise SystemExit("--pixel-size-um must be positive")
    for image in images:
        pixels = tifffile.imread(image)
        values = np.unique(pixels)
        if pixels.ndim != 2 or not set(values.tolist()).issubset({0, 1, 254, 255}):
            raise SystemExit(f"{image}: DiameterJ input must be a 2-D binary TIFF")
        black_fraction = float(np.mean(pixels == values.min()))
        if black_fraction > 0.80:
            raise SystemExit(
                f"{image}: {black_fraction:.1%} black pixels suggests reversed polarity; "
                "DiameterJ requires black fibers on white background"
            )

    # DiameterJ scans every TIFF in its source directory and always creates
    # category subdirectories. Isolate only the requested masks in a temporary
    # work directory, then flatten its result files into input_dir.
    work_dir = Path(tempfile.mkdtemp(prefix=".diameterj_work_", dir=input_dir))
    work_images = []
    for image in images:
        staged = work_dir / image.name
        shutil.copy2(image, staged)
        work_images.append(staged)

    generated = work_dir / "generated_diameterj_batch.ijm"
    generated.write_text(build_macro(macro.read_text(), work_dir, pixel_size_um))

    command = [str(fiji)]
    if headless:
        command += ["--headless", "--console"]
    command += ["-macro", str(generated)]
    print(f"Running DiameterJ on {len(images)} image(s) in {input_dir.resolve()}")
    output_dir = work_dir / "Diameter Analysis Images"
    try:
        if os.environ.get("DIAMETERJ_EXIT_AFTER_OUTPUT") == "1":
            expected = []
            for image in work_images:
                expected.extend(
                    [
                        output_dir / f"{image.stem}_Compare.png",
                        work_dir / "Summaries" / f"{image.stem}_Total Summary.csv",
                        work_dir / "Histograms" / f"{image.stem}_Pore Data.csv",
                    ]
                )
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
                        raise TimeoutError(
                            "DiameterJ timed out before all expected outputs were written"
                        )
                    time.sleep(0.5)
                time.sleep(2.0)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
        else:
            subprocess.run(command, check=True)
        missing = [
            image.stem
            for image in work_images
            if not (output_dir / f"{image.stem}_Compare.png").is_file()
        ]
        if missing:
            raise SystemExit(
                "DiameterJ did not create expected comparison output for: "
                + ", ".join(missing)
            )
        for category in ("Diameter Analysis Images", "Histograms", "Summaries"):
            category_dir = work_dir / category
            if category_dir.is_dir():
                for result in category_dir.iterdir():
                    if result.is_file():
                        result.replace(input_dir / result.name)
        print(f"DiameterJ results: {input_dir.resolve()}")
        return input_dir
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, default=Path("data"))
    p.add_argument(
        "--pixel-size-um", type=float, help="µm per pixel; omit for pixel output"
    )
    p.add_argument("--fiji", type=Path, default=DEFAULT_FIJI)
    p.add_argument("--macro", type=Path, default=VENDOR_MACRO)
    p.add_argument(
        "--headless",
        action="store_true",
        help="experimental: legacy AnalyzeSkeleton may not return results without a GUI",
    )
    args = p.parse_args()
    run_diameterj(args.input, args.pixel_size_um, args.fiji, args.macro, args.headless)


if __name__ == "__main__":
    main()
