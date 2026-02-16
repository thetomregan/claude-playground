"""
FastAPI backend for the PDF Color Mapping application.

Endpoints:
  POST /api/upload        – Upload PDFs, returns detected spot colors per file
  POST /api/process       – Apply color mappings + rename, returns ZIP download
  GET  /api/presets        – List saved color map presets
  POST /api/presets        – Save a new color map preset
  GET  /                   – Serve the single-page frontend
"""

import io
import json
import os
import tempfile
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .pdf_processor import detect_spot_colors, apply_color_map

MAX_UPLOAD_SIZE_MB = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "50"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024

PRESETS_DIR = Path(__file__).parent / "presets"
PRESETS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="PDF Color Mapper", version="1.0.0")


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    html_path = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(content=html_path.read_text(), status_code=200)


@app.post("/api/upload")
async def upload_pdfs(files: list[UploadFile] = File(...)):
    """
    Accept multiple PDF uploads. Returns detected spot colors per file.
    Files are read into memory—nothing is persisted.
    """
    results = []
    all_spots = set()

    for f in files:
        if not f.filename.lower().endswith(".pdf"):
            raise HTTPException(400, f"'{f.filename}' is not a PDF file.")

        data = await f.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                400,
                f"'{f.filename}' exceeds the {MAX_UPLOAD_SIZE_MB} MB upload limit."
            )

        try:
            spots = detect_spot_colors(data)
        except Exception as e:
            raise HTTPException(
                400,
                f"Could not read '{f.filename}' as a valid PDF. Error: {str(e)}"
            )

        all_spots.update(spots)
        results.append({
            "filename": f.filename,
            "spot_colors": spots,
            "size_bytes": len(data),
        })

    return {
        "files": results,
        "all_spot_colors": sorted(all_spots),
    }


@app.post("/api/process")
async def process_pdfs(
    files: list[UploadFile] = File(...),
    config: str = Form(...),
):
    """
    Process uploaded PDFs with color mappings and naming pattern.

    config is a JSON string:
    {
      "naming_pattern": "2025_TNOW_###_Blue",
      "color_variants": [
        {
          "suffix": "Blue",
          "mappings": { "SpotName": {"c":1,"m":0.66,"y":0,"k":0.02} }
        },
        ...
      ]
    }

    Returns a ZIP file organized into subfolders by color variant.
    """
    try:
        cfg = json.loads(config)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON in config field.")

    naming_pattern = cfg.get("naming_pattern", "output_###")
    color_variants = cfg.get("color_variants", [])

    if not color_variants:
        raise HTTPException(400, "No color variants defined.")

    # Read all uploaded files into memory
    pdf_data_list = []
    for f in files:
        if not f.filename.lower().endswith(".pdf"):
            raise HTTPException(400, f"'{f.filename}' is not a PDF file.")
        data = await f.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                400,
                f"'{f.filename}' exceeds the {MAX_UPLOAD_SIZE_MB} MB upload limit."
            )
        pdf_data_list.append({"filename": f.filename, "data": data})

    # Build the ZIP
    zip_buffer = io.BytesIO()
    summary = {
        "total_files_processed": 0,
        "total_outputs": 0,
        "spots_replaced": set(),
        "spots_unmatched": set(),
        "output_files": [],
    }

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for variant in color_variants:
            variant_suffix = variant.get("suffix", "variant")
            mappings = variant.get("mappings", {})

            for file_index, pdf_item in enumerate(pdf_data_list):
                # Generate filename from pattern
                seq_num = str(file_index + 1).zfill(
                    naming_pattern.count("#")
                )
                output_name = naming_pattern.replace(
                    "#" * naming_pattern.count("#"), seq_num
                )
                # Append variant suffix if not already in pattern
                if variant_suffix and variant_suffix not in output_name:
                    # Replace last segment after last underscore if pattern
                    # ends with a color name placeholder, otherwise append
                    output_name = f"{output_name}_{variant_suffix}"

                if not output_name.lower().endswith(".pdf"):
                    output_name += ".pdf"

                try:
                    output_bytes, replaced, unmatched = apply_color_map(
                        pdf_item["data"], mappings
                    )
                except Exception as e:
                    raise HTTPException(
                        500,
                        f"Error processing '{pdf_item['filename']}' "
                        f"with variant '{variant_suffix}': {str(e)}"
                    )

                summary["spots_replaced"].update(replaced)
                summary["spots_unmatched"].update(unmatched)
                summary["total_outputs"] += 1

                # Write to subfolder in ZIP
                zip_path = f"{variant_suffix}/{output_name}"
                zf.writestr(zip_path, output_bytes)
                summary["output_files"].append(zip_path)

            summary["total_files_processed"] = len(pdf_data_list)

    zip_buffer.seek(0)

    # Encode summary into response headers so frontend can display it
    summary_json = json.dumps({
        "total_files_processed": summary["total_files_processed"],
        "total_outputs": summary["total_outputs"],
        "spots_replaced": sorted(summary["spots_replaced"]),
        "spots_unmatched": sorted(summary["spots_unmatched"]),
        "output_files": summary["output_files"],
    })

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": "attachment; filename=color_mapped_pdfs.zip",
            "X-Processing-Summary": summary_json,
        },
    )


@app.get("/api/presets")
async def list_presets():
    """Return all saved color map presets."""
    presets = []
    for p in sorted(PRESETS_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text())
            presets.append({
                "id": p.stem,
                "name": data.get("name", p.stem),
                "mappings": data.get("mappings", {}),
            })
        except (json.JSONDecodeError, OSError):
            continue
    return {"presets": presets}


@app.post("/api/presets")
async def save_preset(preset: dict):
    """Save a color map preset as JSON."""
    name = preset.get("name", "").strip()
    if not name:
        raise HTTPException(400, "Preset name is required.")

    mappings = preset.get("mappings", {})
    if not mappings:
        raise HTTPException(400, "Preset must include at least one color mapping.")

    # Sanitize filename
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in name)
    safe_name = safe_name.strip().replace(" ", "_")
    if not safe_name:
        safe_name = "preset"

    file_path = PRESETS_DIR / f"{safe_name}.json"
    file_path.write_text(json.dumps({
        "name": name,
        "mappings": mappings,
    }, indent=2))

    return {"message": f"Preset '{name}' saved.", "id": safe_name}
