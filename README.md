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
  -v "$PWD/data:/app/data:ro" \
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
  -v "$PWD/data:/app/data:ro" \
  -v "$PWD/results:/app/results" \
  sem_diameterj:0.1 \
  --input /app/data/image.tif \
  --output /app/results \
  --method otsu
```

## Options

Show all container command options:

```bash
docker run --rm sem_diameterj:0.1 --help
```

Available threshold methods are `otsu`, `li`, `yen`, and `triangle`. Run
every method with:

```bash
docker run --rm \
  -v "$PWD/data:/app/data:ro" \
  -v "$PWD/results:/app/results" \
  sem_diameterj:0.1 \
  --input /app/data \
  --output /app/results \
  --all-methods
```

Common analysis options:

- `--crop-bottom N`: remove an instrument footer of `N` pixels; default `59`.
- `--hfw-um N`: horizontal field width in micrometres; default `27.04`.
- `--pixel-size-um N`: use a known pixel size instead of HFW calibration.
- `--sigma N`: Gaussian denoising sigma; default `1.0`.
- `--min-object-px N`: minimum retained object size; default `25`.
- `--min-hole-px N`: minimum filled hole size; default `25`.
- `--invert`: use for fibers darker than the background.
- `--skip-diameterj`: generate segmentation and Python QC outputs only.

Example with custom calibration and footer height:

```bash
docker run --rm \
  -v "$PWD/data:/app/data:ro" \
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

- `*__<method>.tif`: binary DiameterJ input masks
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
