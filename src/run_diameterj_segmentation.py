#!/usr/bin/env python3
"""Run DiameterJ's original Traditional and Mixed segmentation workflows."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

import tifffile
from PIL import Image

from run_diameterj_batch import DEFAULT_FIJI, ij_quote


VENDOR_SEGMENT_MACRO = DEFAULT_FIJI.parent / "plugins/DiameterJ/DiameterJ_Segment.ijm"

TRADITIONAL_METHODS = (
    ("T1", "huang"),
    ("T2", "percentile"),
    ("T3", "minerror"),
    ("T4", "triangle"),
    ("T5", "li"),
    ("T6", "otsu"),
    ("T7", "maxentropy"),
    ("T8", "renyientropy"),
)
THRESHOLD_METHODS = ("huang", "minerror", "percentile", "triangle")
MIXED_SRM_METHODS = (
    ("M1", "huang"),
    ("M2", "minerror"),
    ("M3", "percentile"),
    ("M4", "triangle"),
)
MIXED_DIRECT_METHODS = (
    ("M5", "huang"),
    ("M6", "minerror"),
    ("M7", "percentile"),
    ("M8", "triangle"),
)


def build_segmentation_macro(
    source: str,
    input_dir: Path,
    width: int,
    height: int,
    crop_bottom: int,
    traditional: bool,
    mixed: bool,
    srm: bool,
    srm_q: int,
) -> str:
    marker = 'if(Batch_analysis == "Yes") {'
    marker_at = source.find(marker)
    if marker_at < 0:
        raise RuntimeError(
            "Unsupported DiameterJ segmentation macro: batch marker not found"
        )

    analysis_height = height - crop_bottom
    q_half = max(1, srm_q // 2)
    q_quarter = max(1, srm_q // 4)
    q_eighth = max(1, srm_q // 8)
    q_tenth = max(1, srm_q // 10)
    prefix = f"""// Generated non-interactive segmentation options.
crop_outcome = "Yes";
iw = {width};
ih = {height};
crop_tlx = 0;
crop_tly = 0;
crop_brx = {width};
crop_bry = {analysis_height};
TLCB_None = 0;
TRCB_Trad = {1 if traditional else 0};
BLCB_SRM = {1 if srm else 0};
BRCB_Mix = {1 if mixed else 0};
Batch_analysis = "Yes";
IJorFIJI = getVersion();
thresh_dots = "Auto Threshold";
srm_q = {srm_q};
srm_q_half = {q_half};
srm_q_quarter = {q_quarter};
srm_q_eighth = {q_eighth};
srm_q_tenth = {q_tenth};

"""
    generated = prefix + source[marker_at:]
    prompt = 'dir1 = getDirectory("Choose Source Directory ");'
    directory = input_dir.resolve().as_posix().rstrip("/") + "/"
    if prompt not in generated:
        raise RuntimeError(
            "Unsupported DiameterJ segmentation macro: directory prompt not found"
        )
    generated = generated.replace(prompt, f'dir1 = "{ij_quote(directory)}";', 1)
    generated = generated.replace("open(name0);", "open(dir1+name0);")
    # Mixed uses one SRM pass at the requested q. Restrict this replacement to
    # Mixed blocks before replacing the fixed values in the SRM branch.
    parts = generated.split("// Runs Mixed Segmentation Algorithms")
    for index in range(1, len(parts)):
        mixed_part, separator, remainder = parts[index].partition(
            "// Runs Statistical Region Merging Segmentation Techniques"
        )
        mixed_part = mixed_part.replace("q=25 showaverages", 'q="+srm_q+" showaverages')
        parts[index] = mixed_part + separator + remainder
    generated = "// Runs Mixed Segmentation Algorithms".join(parts)
    generated = generated.replace("q=100 showaverages", 'q="+srm_q+" showaverages')
    generated = generated.replace("q=50 showaverages", 'q="+srm_q_half+" showaverages')
    generated = generated.replace(
        "q=25 showaverages", 'q="+srm_q_quarter+" showaverages'
    )
    generated = generated.replace(
        "q=12 showaverages", 'q="+srm_q_eighth+" showaverages'
    )
    generated = generated.replace("q=10 showaverages", 'q="+srm_q_tenth+" showaverages')
    # Fiji uses the opened filename as each montage label. Replace DiameterJ's
    # opaque T/M/S codes with the actual segmentation method names.
    generated = generated.replace(
        'open(dir1+name0);\n\t\t\trun("Invert");',
        'open(dir1+name0);\n\t\t\trename("Original");\n\t\t\trun("Invert");',
    )
    montage_labels = {
        1: 'Mixed SRM q="+srm_q+" Huang',
        3: 'Mixed SRM q="+srm_q+" MinError',
        4: 'Mixed SRM q="+srm_q+" Percentile',
        5: 'Mixed SRM q="+srm_q+" Triangle',
        6: "Mixed Direct Huang",
        7: "Mixed Direct MinError",
        8: "Mixed Direct Percentile",
        9: "Mixed Direct Triangle",
        13: 'SRM q="+srm_q+"-"+srm_q_half+"-"+srm_q_quarter+"-"+srm_q_eighth+" Huang',
        14: 'SRM q="+srm_q+"-"+srm_q_half+"-"+srm_q_quarter+"-"+srm_q_eighth+" MinError',
        15: 'SRM q="+srm_q+"-"+srm_q_half+"-"+srm_q_quarter+"-"+srm_q_eighth+" Percentile',
        16: 'SRM q="+srm_q+"-"+srm_q_half+"-"+srm_q_quarter+"-"+srm_q_eighth+" Triangle',
        17: 'SRM q="+srm_q_half+"-"+srm_q_tenth+" Huang',
        18: 'SRM q="+srm_q_half+"-"+srm_q_tenth+" MinError',
        19: 'SRM q="+srm_q_half+"-"+srm_q_tenth+" Percentile',
        20: 'SRM q="+srm_q_half+"-"+srm_q_tenth+" Triangle',
        23: "Traditional Huang",
        24: "Traditional Percentile",
        25: "Traditional MinError",
        26: "Traditional Triangle",
        27: "Traditional Li",
        28: "Traditional Otsu",
        29: "Traditional MaxEntropy",
        30: "Traditional RenyiEntropy",
    }
    for path_number, label in montage_labels.items():
        generated = generated.replace(
            f'open(path{path_number}+".tif");',
            f'open(path{path_number}+".tif"); rename("{label}");',
        )
    # The SRM branch repeatedly saves intermediate images to the same path.
    # ImageJ's unattended save does not reliably overwrite, so delete the old
    # intermediate before each save.
    generated = generated.replace(
        'saveAs("Tiff", path11);',
        'File.delete(path11+".tif");\n\t\t\t\t\t\tsaveAs("Tiff", path11);',
    )
    generated = generated.replace(
        'saveAs("Tiff", path12);',
        'File.delete(path12+".tif");\n\t\t\t\t\t\tsaveAs("Tiff", path12);',
    )
    return generated


def run_fiji_segmentation(
    image: Path,
    output_dir: Path,
    mode: str,
    crop_bottom: int,
    srm_q: int,
    fiji: Path = DEFAULT_FIJI,
    macro: Path = VENDOR_SEGMENT_MACRO,
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
    if not fiji.is_file() or not macro.is_file():
        raise SystemExit("Local Fiji or DiameterJ segmentation macro not found")

    traditional = mode in {"traditional", "all"}
    mixed = mode in {"mixed", "all"}
    srm = mode in {"srm", "all"}
    methods = []
    if traditional:
        methods.extend(
            (code, "traditional", name) for code, name in TRADITIONAL_METHODS
        )
    if mixed:
        methods.extend(
            (code, "mixed", f"srm_q{srm_q}_{name}")
            for code, name in MIXED_SRM_METHODS
        )
        methods.extend(
            (code, "mixed", f"direct_{name}")
            for code, name in MIXED_DIRECT_METHODS
        )
    if srm:
        q_half = max(1, srm_q // 2)
        q_quarter = max(1, srm_q // 4)
        q_eighth = max(1, srm_q // 8)
        q_tenth = max(1, srm_q // 10)
        first = f"q{srm_q}_{q_half}_{q_quarter}_{q_eighth}"
        second = f"q{q_half}_{q_tenth}"
        for index, name in enumerate(THRESHOLD_METHODS, start=1):
            methods.append((f"S{index}", "srm", f"{first}_{name}"))
            methods.append((f"S{index + 4}", "srm", f"{second}_{name}"))
        methods.sort(key=lambda item: (item[1], item[0]))

    work_dir = Path(tempfile.mkdtemp(prefix=".diameterj_segment_", dir=output_dir))
    try:
        staged = work_dir / image.name
        shutil.copy2(image, staged)
        generated = work_dir / "generated_diameterj_segment.ijm"
        generated.write_text(
            build_segmentation_macro(
                macro.read_text(),
                work_dir,
                width,
                height,
                crop_bottom,
                traditional,
                mixed,
                srm,
                srm_q,
            )
        )
        segmented = work_dir / "Segmented Images"
        expected = [segmented / f"{image.stem}_{code}.tif" for code, _, _ in methods]
        montage_names = {
            "traditional": "Trad Montage",
            "mixed": "Mix Montage",
            "srm": "SRM Montage",
            "all": "Trad&Mix&SRM Montage",
        }
        montage = work_dir / "Montage Images" / f"{image.stem}_{montage_names[mode]}.png"
        expected.append(montage)
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
                    raise TimeoutError("DiameterJ segmentation timed out")
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
        for source_mask, (_, family, method) in zip(expected[:-1], methods):
            destination = output_dir / f"{image.stem}__{family}_{method}.tif"
            shutil.copy2(source_mask, destination)
            mask_pixels = tifffile.imread(source_mask)
            Image.fromarray(255 - mask_pixels).save(destination.with_suffix(".png"))
            results.append((destination, family, method))
        shutil.copy2(montage, output_dir / f"{image.stem}__{mode}_montage.png")
        return results
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
