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
| `python` | Python preprocessing followed by one or all Python thresholds | 1 or 4 |
| `traditional` | Fiji Auto Threshold applied directly to the cropped image | 8 |
| `mixed` | One Fiji SRM pass followed by four thresholds | 4 |
| `srm` | Two recursive Fiji SRM sequences followed by four thresholds each | 8 |
| `all` | Traditional, Mixed, and recursive SRM | 20 |

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

### Traditional segmentation

Generate and analyze the eight original Traditional masks: Huang, Percentile,
MinError(I), Triangle, Li, Otsu, MaxEntropy, and RenyiEntropy.

```bash
docker run --rm \
  -v "$PWD/data:/app/data" \
  -v "$PWD/results:/app/results" \
  sem_diameterj:0.1 \
  --input /app/data \
  --output /app/results \
  --segmentation traditional
```

### Mixed segmentation

Mixed segmentation applies one Fiji Statistical Region Merging pass and then
converts the resulting grayscale image into four binary masks using Huang,
MinError(I), Percentile, and Triangle. The SRM pass uses `--srm-q 100` by
default.

```bash
docker run --rm \
  -v "$PWD/data:/app/data" \
  -v "$PWD/results:/app/results" \
  sem_diameterj:0.1 \
  --input /app/data \
  --output /app/results \
  --segmentation mixed
```

Set another SRM granularity with `--srm-q`, for example:

```bash
docker run --rm \
  -v "$PWD/data:/app/data" \
  -v "$PWD/results:/app/results" \
  sem_diameterj:0.1 \
  --input /app/data \
  --output /app/results \
  --segmentation mixed \
  --srm-q 50
```

### Recursive SRM segmentation

This mode runs DiameterJ's Fiji Statistical Region Merging branch. With the
default `--srm-q 100`, it uses these two sequences:

```text
original → q=100 → q=50 → q=25 → q=12 → threshold
original → q=50  → q=10                  → threshold
```

Each arrow is another SRM pass over the preceding pass's output. Each final
image is thresholded with Huang, MinError(I), Percentile, and Triangle,
producing eight masks.

For another starting value `q`, the levels use integer division:

```text
q → q/2 → q/4 → q/8
q/2 → q/10
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
  --segmentation srm
```

Use `--segmentation all` to generate Traditional, Mixed, and SRM masks in one
run.

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

Option used by `--segmentation mixed`, `srm`, and `all`:

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

- `*__<method>.tif`: Python binary masks
- `*__traditional_<method>.tif`: Traditional masks
- `*__mixed_q<q>_<method>.tif`: Mixed masks
- `*__srm_q<levels>_<method>.tif`: recursive SRM masks
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
  .
```
