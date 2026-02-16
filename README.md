# PDF Color Mapper

A web application for mapping spot colors to CMYK in PDF files with batch renaming and ZIP export.

Built for design teams — upload PDFs, define naming patterns, configure spot-to-CMYK color mappings, and download renamed + color-mapped output files as a ZIP.

## Local Setup

### Requirements

- Python 3.11+
- pip

### Install and Run

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

Open http://localhost:8080 in your browser.

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MAX_UPLOAD_SIZE_MB` | `50` | Maximum upload size per file in MB |

## Deploy to Render

1. Push this repo to GitHub
2. Connect the repo on [Render](https://render.com)
3. Render will auto-detect the `render.yaml` and deploy
4. The app runs on the free tier with Docker

## Deploy to Railway

1. Push this repo to GitHub
2. Connect the repo on [Railway](https://railway.app)
3. Railway will auto-detect the `railway.toml` and deploy

## Deploy with Docker

```bash
docker build -t pdf-color-mapper .
docker run -p 8080:8080 -e MAX_UPLOAD_SIZE_MB=50 pdf-color-mapper
```

## Adding Color Map Presets

Presets are JSON files stored in `app/presets/`. To add a new preset:

1. Create a JSON file in `app/presets/` (e.g., `my_palette.json`):

```json
{
  "name": "My Custom Palette",
  "mappings": {
    "PANTONE 286 C": { "c": 1.0, "m": 0.66, "y": 0.0, "k": 0.02 },
    "PANTONE 485 C": { "c": 0.0, "m": 0.95, "y": 1.0, "k": 0.0 }
  }
}
```

2. CMYK values are floats from 0.0 to 1.0
3. Spot color names must match exactly what appears in your PDFs
4. Presets can also be saved from the web UI during step 3

## How It Works

1. **Upload** — Drag-and-drop or select PDF files. The app scans each PDF for Separation and DeviceN colorspaces to detect spot colors.
2. **Name** — Define a naming pattern with `###` for auto-incrementing numbers. The color variant suffix is appended automatically.
3. **Map Colors** — Configure CMYK values for each detected spot color. Create multiple color variants for batch output. Load/save presets for team reuse.
4. **Process & Download** — The app replaces each Separation colorspace's tint transform with a FunctionType 2 function mapping to your CMYK values, renames files per your pattern, and bundles everything into a ZIP organized by variant.

## Running Tests

```bash
python tests/test_pdf_processor.py
```
