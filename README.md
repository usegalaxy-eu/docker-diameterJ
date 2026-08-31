# DiameterJ container

This container prepares scanning electron microscopy (SEM) TIFF images,
creates binary fibre masks, runs DiameterJ v1.018, and writes DiameterJ
measurements together with independent quality-control (QC) results.
It runs the legacy Fiji GUI workflow on a virtual X server, so no display is
required on the host.

## Included software

The Ubuntu 22.04 image downloads these pinned, SHA-256-verified packages:

- Fiji Life-Line for Linux (2017-05-30), with ImageJ 1.51n and Java 8
- DiameterJ for Fiji v1.018
- Fiji Auto Threshold v1.18.0

Python dependencies come from `requirements.txt`. The downloaded packages do
not need to be stored in this repository.

## Build

From the directory containing this README and the `Dockerfile`:

```bash
docker build -t sem_diameterj:0.1 .
```

## Quick start

Put one or more `.tif` or `.tiff` files in `data/`, then run:

```bash
mkdir -p results
docker run --rm \
  -v "$PWD/data:/app/data:ro" \
  -v "$PWD/results:/app/results" \
  sem_diameterj:0.1 \
  --input /app/data \
  --output /app/results
```

The default workflow uses Fiji Auto Thresholding to generate all 17 threshold
candidates and then runs DiameterJ. Use `--threshold-methods` to process only
the methods selected in a UI or on the command line. TIFF extension matching is
case-insensitive, but directory scanning is not recursive.

To process one image, pass its path inside the container:

```bash
docker run --rm \
  -v "$PWD/data:/app/data:ro" \
  -v "$PWD/results:/app/results" \
  sem_diameterj:0.1 \
  --input /app/data/image.tif \
  --output /app/results
```

When started as root and the output directory exists, the entrypoint runs the
analysis as that directory's owner. This prevents root-owned results without
requiring UID or GID environment variables.

Show every option with:

```bash
docker run --rm sem_diameterj:0.1 --help
```

## Segmentation workflows

Select a workflow with `--segmentation`:

| Value | Processing | Masks per image |
| --- | --- | ---: |
| `auto-thresholding` (default) | All Fiji Auto Threshold methods on the cropped image | 17 |
| `recursive-srm` | Four successive SRM passes, then all Fiji thresholds | 17 |
| `srm-auto-thresholding` | One SRM pass, then all Fiji thresholds | 17 |
| `all` | All three Fiji workflows | 51 |

### Fiji Auto Thresholding

The Fiji workflows use 17 methods: Default, Huang, Huang2, Intermodes, IsoData,
Li, MaxEntropy, Mean, MinError(I), Minimum, Moments, Otsu, Percentile,
RenyiEntropy, Shanbhag, Triangle, and Yen. `Try all` is an interactive command,
not an additional threshold method.

Choose one or more methods with their lowercase slugs. A comma-separated value
is accepted so a Galaxy multi-select can be passed directly:

```bash
docker run --rm \
  -v "$PWD/data:/app/data:ro" \
  -v "$PWD/results:/app/results" \
  sem_diameterj:0.1 \
  --input /app/data \
  --output /app/results \
  --segmentation recursive-srm \
  --threshold-methods default,otsu,triangle
```

The option can instead be repeated, for example
`--threshold-methods otsu --threshold-methods yen`. If it is omitted, all 17
methods are run. The selected methods apply to each workflow when
`--segmentation all` is used.

```bash
docker run --rm \
  -v "$PWD/data:/app/data:ro" \
  -v "$PWD/results:/app/results" \
  sem_diameterj:0.1 \
  --input /app/data \
  --output /app/results \
  --segmentation auto-thresholding
```

### SRM workflows

`srm-auto-thresholding` applies one Statistical Region Merging (SRM) pass and
then all 17 thresholds. `recursive-srm` applies four successive SRM passes. At
the default `--srm-q 100`, the recursive sequence is:

```text
original -> q=100 -> q=50 -> q=25 -> q=12 -> threshold
```

For another positive starting value, the levels are `q`, `q/2`, `q/4`, and
`q/8`, using integer division with a minimum of 1. For example:

```bash
docker run --rm \
  -v "$PWD/data:/app/data:ro" \
  -v "$PWD/results:/app/results" \
  sem_diameterj:0.1 \
  --input /app/data \
  --output /app/results \
  --segmentation recursive-srm \
  --srm-q 50
```

Use `--segmentation all` to run direct Auto Thresholding, recursive SRM, and
one-pass SRM Auto Thresholding together.

## Calibration and common options

- `--crop-bottom N` removes an instrument footer; default: `59` pixels.
- `--hfw-um N` sets the horizontal field width; default: `27.04` micrometres.
- `--pixel-size-um N` supplies micrometres per pixel instead of deriving it
  from the field width and original image width.
- `--skip-diameterj` creates masks and QC outputs without DiameterJ.
- `--headless` uses Fiji's experimental native headless mode. Normally the
  virtual display should be used because legacy AnalyzeSkeleton may fail
  without a GUI.

The Fiji/DiameterJ safety timeout defaults to 600 seconds (10 minutes) per
segmentation image. Each mask is analyzed in an isolated Fiji process so legacy
DiameterJ state from one threshold candidate cannot stall a later candidate.
Completed results are retained as the batch progresses, while a candidate that
times out or produces incomplete DiameterJ output is skipped with a warning. The
job fails only if every selected candidate fails. Override the per-image budget
with the `DIAMETERJ_TIMEOUT_SECONDS` container environment variable when
unusually large images require more time.

Calibration is recorded in `qc_summary.csv` and used for QC
diameters. DiameterJ v1.018 runs in its validated native-pixel mode; use the
recorded calibration to convert its results.

```bash
docker run --rm \
  -v "$PWD/data:/app/data:ro" \
  -v "$PWD/results:/app/results" \
  sem_diameterj:0.1 \
  --input /app/data \
  --output /app/results \
  --crop-bottom 70 \
  --hfw-um 50 \
  --skip-diameterj
```

## Outputs

All outputs are flattened into the selected output directory. Depending on
the workflow and DiameterJ result type, filenames include:

- `<source>__auto_thresholding_<method>.png` and `.tif`: direct Fiji masks
- `<source>__srm_auto_thresholding_q<q>_<method>.png` and `.tif`: one-pass SRM masks
- `<source>__recursive_srm_q<levels>_<method>.png` and `.tif`: recursive SRM masks
- `<mask>_overlay.png`: red segmentation-boundary overlay
- `<mask>_diameters.csv`: independent QC diameter samples
- `<source>__<workflow>_segmentation_montage.png`: source and mask review sheet
- `<source>__<workflow>_overlay_montage.png`: source and overlay review sheet
- `qc_summary.csv`: calibration, area fraction, and QC summary values
- `<mask>_Compare.png`: DiameterJ comparison panel
- `<mask>_Total Summary.csv`: DiameterJ summary measurements
- `<mask>_Pore Data.csv`: DiameterJ pore measurements
- `<mask>_Radius Histo.csv` and `<mask>_Radius Plot.tif`: distributions

Fiji montage layouts are 5 x 4 for one 17-mask workflow and 8 x 7 for the
51-mask `all` workflow. PNG masks are convenient for review; TIFF masks retain
the polarity and photometric convention expected by DiameterJ.

## Build-time package overrides

Each URL is paired with a checksum build argument. Override both together:

```bash
docker build -t sem_diameterj:0.1 \
  --build-arg FIJI_URL=https://example.invalid/fiji.zip \
  --build-arg FIJI_SHA256=<sha256> \
  --build-arg DIAMETERJ_URL=https://example.invalid/diameterj.zip \
  --build-arg DIAMETERJ_SHA256=<sha256> \
  --build-arg AUTO_THRESHOLD_URL=https://example.invalid/Auto_Threshold.jar \
  --build-arg AUTO_THRESHOLD_SHA256=<sha256> \
  .
```

The image entrypoint is `/usr/local/bin/sem-analysis`; its default command is
`--help`.
