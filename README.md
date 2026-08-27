# DiameterJ Docker image

This image prepares SEM TIFF images, runs DiameterJ v1.018 in a compatible
Fiji/ImageJ environment, and writes DiameterJ results plus Python QC outputs.

## Build

From this directory:

```bash
docker build -t sem_diameterj:0.1 .
```

The build downloads and SHA-256 verifies these pinned packages:

- Fiji Life-Line Linux 64-bit, 2017-05-30 (ImageJ 1.51n)
- DiameterJ for Fiji v1.018
- Fiji Auto Threshold v1.18.0

The packages are installed in the image and do not need to be stored in the
repository.

## Run

Place input `.tif` or `.tiff` images in `data/`, then run:

```bash
mkdir -p results
docker run --rm \
  -v "$PWD/data:/app/data" \
  -v "$PWD/results:/app/results" \
  sem_diameterj:0.1 \
  --input /app/data \
  --output /app/results \
  --method otsu
```

The input mount is read-only. The output mount preserves generated files after
the container exits. The entrypoint uses the owner of the mounted `results/`
directory, so UID and GID environment variables are not required.

To process a single TIFF, provide its path inside the input mount:

```bash
docker run --rm \
  -v "$PWD/data:/app/data" \
  -v "$PWD/results:/app/results" \
  sem_diameterj:0.1 \
  --input /app/data/image.tif \
  --output /app/results \
  --method otsu
```

## Segmentation modes

Show all container command options:

```bash
docker run --rm sem_diameterj:0.1 --help
```

Select a workflow with `--segmentation`:

| Mode | Processing | Masks per image |
| --- | --- | ---: |
| `auto-thresholding` | Every Fiji Auto Threshold method applied to the cropped image | 17 |
| `recursive-srm` | One recursive SRM sequence followed by every threshold | 17 |
| `srm-auto-thresholding` | One SRM pass followed by every threshold | 17 |
| `all` | All three Fiji workflows | 51 |

The default mode is `python`.

### Python segmentation

Python segmentation supports `--method otsu`, `li`, `yen`, or `triangle`.
Generate all four masks with:

```bash
docker run --rm \
  -v "$PWD/data:/app/data" \
  -v "$PWD/results:/app/results" \
  sem_diameterj:0.1 \
  --input /app/data \
  --output /app/results \
  --all-methods
```

### Auto Thresholding

Fiji Auto Threshold v1.18.0 is applied directly to the cropped image using all
17 concrete methods: Default, Huang, Huang2, Intermodes, IsoData, Li,
MaxEntropy, Mean, MinError(I), Minimum, Moments, Otsu, Percentile,
RenyiEntropy, Shanbhag, Triangle, and Yen. The interactive `Try all` command is
not itself a thresholding method and is therefore not an additional output.

```bash
docker run --rm \
  -v "$PWD/data:/app/data" \
  -v "$PWD/results:/app/results" \
  sem_diameterj:0.1 \
  --input /app/data \
  --output /app/results \
  --segmentation auto-thresholding
```

### SRM with Auto Thresholding

This workflow applies one Fiji Statistical Region Merging pass, converts its
result to 8-bit, and applies each of the same 17 Auto Threshold methods. The
SRM pass uses `--srm-q 100` by default.

```bash
docker run --rm \
  -v "$PWD/data:/app/data" \
  -v "$PWD/results:/app/results" \
  sem_diameterj:0.1 \
  --input /app/data \
  --output /app/results \
  --segmentation srm-auto-thresholding
```

Set another SRM granularity with `--srm-q`, for example:

```bash
docker run --rm \
  -v "$PWD/data:/app/data" \
  -v "$PWD/results:/app/results" \
  sem_diameterj:0.1 \
  --input /app/data \
  --output /app/results \
  --segmentation srm-auto-thresholding \
  --srm-q 50
```

### Recursive SRM

This mode runs one recursive Fiji Statistical Region Merging sequence. With
the default `--srm-q 100`, it uses:

```text
original → q=100 → q=50 → q=25 → q=12 → threshold
```

Each arrow is another SRM pass over the preceding pass's output. The final
image is processed with all 17 Auto Threshold methods, producing 17 masks.

For another starting value `q`, the levels use integer division:

```text
q → q/2 → q/4 → q/8
```

Every derived value has a minimum of `1`. Higher `q` values generally preserve
more regions; lower values generally produce coarser regions.

```bash
docker run --rm \
  -v "$PWD/data:/app/data" \
  -v "$PWD/results:/app/results" \
  sem_diameterj:0.1 \
  --input /app/data \
  --output /app/results \
  --segmentation recursive-srm
```

Use `--segmentation all` to generate Auto Thresholding, Recursive SRM, and SRM
with Auto Thresholding masks in one run.

## Segmentation and overlay montages

Every Fiji segmentation mode writes its separate binary masks as PNG and TIFF,
plus two PNG montages:

- `<source>__<mode>_segmentation_montage.png`: original image and all binary
  segmentation candidates
- `<source>__<mode>_overlay_montage.png`: original image and all boundary
  overlays

Each montage uses the following layout:

- `auto-thresholding`: original plus 17 masks in a 5 × 4 montage
- `recursive-srm`: original plus 17 masks in a 5 × 4 montage
- `srm-auto-thresholding`: original plus 17 masks in a 5 × 4 montage
- `all`: original plus 51 masks in an 8 × 7 montage

The montages provide visual review sheets. Individual PNG masks are convenient
for viewing and export; matching TIFF masks are retained because DiameterJ
uses them for measurement. PNG pixels account for TIFF's `MINISWHITE` display
convention, so PNG and TIFF viewers show the same regions with the same
black/white colors. Both montage types use descriptive segmentation names.

## Analysis options

Options used by every segmentation mode:

- `--crop-bottom N`: remove an instrument footer of `N` pixels; default `59`.
- `--hfw-um N`: horizontal field width in micrometres; default `27.04`.
- `--pixel-size-um N`: use a known pixel size instead of HFW calibration.
- `--skip-diameterj`: generate segmentation and Python QC outputs only.

Options used only by `--segmentation python`:

- `--method NAME`: use `otsu`, `li`, `yen`, or `triangle`; default `otsu`.
- `--all-methods`: generate all four Python threshold masks.
- `--sigma N`: Gaussian denoising sigma; default `1.0`.
- `--min-object-px N`: minimum retained object size; default `25`.
- `--min-hole-px N`: minimum filled hole size; default `25`.
- `--invert`: use for fibers darker than the background.

Option used by `--segmentation recursive-srm`, `srm-auto-thresholding`, and
`all`:

- `--srm-q N`: positive SRM granularity value; default `100`.

Example with custom calibration and footer height:

```bash
docker run --rm \
  -v "$PWD/data:/app/data" \
  -v "$PWD/results:/app/results" \
  sem_diameterj:0.1 \
  --input /app/data \
  --output /app/results \
  --method yen \
  --crop-bottom 70 \
  --hfw-um 50
```

## Outputs

The mounted `results/` directory receives:

- `*__<mode>_segmentation_montage.png`: original image and every mask
- `*__<mode>_overlay_montage.png`: original image and every boundary overlay
- `*__<method>.{png,tif}`: Python binary masks
- `*__auto_thresholding_<method>.{png,tif}`: direct Auto Threshold masks
- `*__srm_auto_thresholding_q<q>_<method>.{png,tif}`: one-pass SRM plus Auto
  Threshold masks
- `*__recursive_srm_q<levels>_<method>.{png,tif}`: Recursive SRM plus Auto
  Threshold masks
- `*_Compare.png`: DiameterJ comparison panels
- `*_Total Summary.csv`: DiameterJ summary measurements
- `*_Pore Data.csv`: DiameterJ pore measurements
- `*_Radius Histo.csv` and `*_Radius Plot.tif`: diameter distributions
- `*_overlay.png`: segmentation boundary overlays
- `*_diameters.csv`: Python QC diameter samples
- `python_qc_summary.csv`: calibration and QC summary

## Build-time package overrides

The package locations and checksums are Docker build arguments. Override a
package only together with its matching checksum:

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
