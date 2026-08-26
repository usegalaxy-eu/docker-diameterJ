# SEM fiber diameter analysis with Fiji and DiameterJ

This project prepares SEM TIFF images for measurement with the DiameterJ plugin
in Fiji/ImageJ. It also writes an independent Python skeleton/distance-transform
estimate for quality control (QC). The QC estimate is **not** a replacement for
the validated DiameterJ result.

## Setup

Fiji 2017 and DiameterJ v1.018 are downloaded and checksum-verified while the
Docker image is built. They are deliberately not stored in this repository.
Build the image from this directory:

```bash
docker build -t sem_diameterj:0.1 .
```

The pinned Fiji Life-Line build provides ImageJ 1.51n, which is compatible with
the legacy DiameterJ macro. Current Fiji/ImageJ releases are not used because
their `ResultsTable` behavior differs during DiameterJ's `Summarize` step.

For local development outside Docker, install [Fiji](https://fiji.sc/) and
DiameterJ v1.018 following the
[DiameterJ installation page](https://imagej.net/plugins/diameterj), then
create a Python environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Run the complete analysis

The main script creates the mask and immediately runs the compatible Fiji and
DiameterJ analysis. From the project directory, run:

```bash
mkdir -p results
docker run --rm \
  -v "$PWD/data:/app/data:ro" \
  -v "$PWD/results:/app/results" \
  sem_diameterj:0.1 \
  --input /app/data \
  --output /app/results \
  --method otsu
```

The entrypoint detects the owner of the mounted `results/` directory, so
`PUID` and `PGID` are not required. The input mount is read-only, while the
output mount keeps generated files after the container exits.

To run every supported threshold method:

```bash
docker run --rm \
  -v "$PWD/data:/app/data:ro" \
  -v "$PWD/results:/app/results" \
  sem_diameterj:0.1 \
  --input /app/data \
  --output /app/results \
  --all-methods
```

All masks, overlays, QC tables, DiameterJ comparison images, histograms, and
summaries are written directly into `results/`. Use `--all-methods` only when
you intentionally want DiameterJ to analyze every threshold candidate. Use
`--skip-diameterj` to create masks and Python QC files without launching Fiji.

The combined workflow intentionally runs DiameterJ v1.018 in pixel units. Its
legacy particle filtering changes when calibration is applied internally. Use
the per-image `pixel_size_um` recorded in `results/python_qc_summary.csv` to
convert the reported DiameterJ pixel measurements to µm. Images with different
widths or calibrations can therefore be processed in the same batch.

The defaults match `data/PVA-A_004.tif`: 59 footer pixels are removed and the
27.04 µm horizontal field width over 1024 pixels gives 0.02640625 µm/px. For a
different acquisition, pass its own values, for example:

```bash
python src/analyze_sem.py --input data --crop-bottom 70 --hfw-um 50
```

If calibrated pixel size is known directly, prefer `--pixel-size-um`. Use
`--invert` only for dark fibers on a bright background. Never infer scale from
the TIFF's nominal X/Y resolution: SEM exporters often store a display value
rather than specimen calibration.

Inspect every `results/*_overlay.png` and select the mask whose red boundary
best follows real fiber edges, without joining nearby fibers or filling pores.
Do not select a threshold based on which one gives the desired diameter.

## Optional manual review and rerun

For each accepted binary TIFF:

1. Confirm under **Analyze > Set Scale** that distance in pixels is used. This
   preserves DiameterJ's native output and avoids plugin-version scale issues.
2. Run **Plugins > DiameterJ > DiameterJ** (the exact menu label can vary by
   DiameterJ package), choose the binary-image analysis path, and save its full
   output into `results/diameterj/<image-name>/`.
3. Convert reported pixel diameters to µm by multiplying by `pixel_size_um` in
   `results/python_qc_summary.csv`. For this sample, multiply by `0.02640625`.
4. Compare DiameterJ's distribution with `results/*_diameters.csv`. Large disagreement
   usually indicates poor segmentation, crossings, edge fibers, or scale error.

The standalone DiameterJ wrapper remains available when you want to review or
manually select masks before measurement:

```bash
python src/run_diameterj_batch.py \
  --input results/selected_masks \
  --pixel-size-um 0.02640625
```

DiameterJ writes its `*_Compare.png`, summary CSVs, and histogram files directly
inside the selected-mask directory. Fiji's window opens, but the
analysis itself needs no clicks. DiameterJ v1.018's legacy AnalyzeSkeleton
dependency does not reliably publish its Results table in true headless mode;
therefore GUI-backed execution is the default. The wrapper generates
`results/generated_diameterj_batch.ijm`; it does not edit the installed vendor
macro. It intentionally uses the preserved May 2017 Fiji Life-Line build,
matching ImageJ 1.51n used for the supplied reference outputs; current Fiji is
not table-compatible with DiameterJ v1.018.

DiameterJ documentation warns that fibers below 10 px or above 10% of the
smallest image dimension can exceed 10% measurement error. With this sample's
calibration, 10 px is 0.2641 µm. Report the segmentation method, calibration,
number of images/fields, exclusion rules, and distribution (median/IQR as well
as mean/SD), not only a single mean diameter.

## Outputs

- `results/*__<method>.tif`: binary inputs for DiameterJ
- `results/*_overlay.png`: segmentation boundary overlays for visual review
- `results/*_diameters.csv`: per-skeleton-pixel QC diameters
- `results/python_qc_summary.csv`: calibration and QC summary/audit trail
