"""
End-to-end tests for the FastAPI endpoints.
Generates a test PDF, uploads it, processes it, and verifies the ZIP output.
"""

import io
import json
import zipfile
import requests
import pikepdf
from pikepdf import Name, Array, Dictionary

BASE = "http://localhost:8080"


def make_test_pdf():
    """Create a test PDF with two spot colors."""
    pdf = pikepdf.new()
    page_dict = Dictionary({
        "/Type": Name.Page,
        "/MediaBox": Array([0, 0, 612, 792]),
    })
    page = pikepdf.Page(pdf.make_indirect(page_dict))

    tint1 = Dictionary({
        "/FunctionType": 2,
        "/Domain": Array([0.0, 1.0]),
        "/Range": Array([0.0, 1.0]),
        "/C0": Array([0.0]),
        "/C1": Array([1.0]),
        "/N": 1,
    })
    tint2 = Dictionary({
        "/FunctionType": 2,
        "/Domain": Array([0.0, 1.0]),
        "/Range": Array([0.0, 1.0]),
        "/C0": Array([0.0]),
        "/C1": Array([1.0]),
        "/N": 1,
    })

    cs_dict = Dictionary({
        "/CS0": Array([Name.Separation, Name("/PANTONE 286 C"), Name.DeviceGray, pdf.make_indirect(tint1)]),
        "/CS1": Array([Name.Separation, Name("/PANTONE 485 C"), Name.DeviceGray, pdf.make_indirect(tint2)]),
    })
    page.obj[Name.Resources] = Dictionary({"/ColorSpace": cs_dict})
    pdf.pages.append(page)

    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


def test_frontend_served():
    resp = requests.get(f"{BASE}/")
    assert resp.status_code == 200
    assert "PDF Color Mapper" in resp.text
    print("PASS: frontend served")


def test_upload():
    pdf_bytes = make_test_pdf()
    files = [("files", ("test.pdf", io.BytesIO(pdf_bytes), "application/pdf"))]
    resp = requests.post(f"{BASE}/api/upload", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["files"]) == 1
    assert "PANTONE 286 C" in data["all_spot_colors"]
    assert "PANTONE 485 C" in data["all_spot_colors"]
    print(f"PASS: upload — detected spots: {data['all_spot_colors']}")


def test_presets():
    resp = requests.get(f"{BASE}/api/presets")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["presets"]) >= 1  # default preset
    print(f"PASS: presets — found {len(data['presets'])} presets")


def test_process():
    pdf_bytes = make_test_pdf()

    config = {
        "naming_pattern": "2025_TEST_###",
        "color_variants": [
            {
                "suffix": "Blue",
                "mappings": {
                    "PANTONE 286 C": {"c": 1.0, "m": 0.66, "y": 0.0, "k": 0.02},
                    "PANTONE 485 C": {"c": 0.0, "m": 0.0, "y": 0.0, "k": 0.0},
                },
            },
            {
                "suffix": "Red",
                "mappings": {
                    "PANTONE 286 C": {"c": 0.0, "m": 0.0, "y": 0.0, "k": 0.0},
                    "PANTONE 485 C": {"c": 0.0, "m": 0.95, "y": 1.0, "k": 0.0},
                },
            },
        ],
    }

    files = [("files", ("design.pdf", io.BytesIO(pdf_bytes), "application/pdf"))]
    data = {"config": json.dumps(config)}

    resp = requests.post(f"{BASE}/api/process", files=files, data=data)
    assert resp.status_code == 200, f"Process failed: {resp.text}"
    assert resp.headers["content-type"] == "application/zip"

    # Check summary header
    summary = json.loads(resp.headers["X-Processing-Summary"])
    assert summary["total_files_processed"] == 1
    assert summary["total_outputs"] == 2  # 1 file x 2 variants
    assert "PANTONE 286 C" in summary["spots_replaced"]
    assert "PANTONE 485 C" in summary["spots_replaced"]
    print(f"PASS: process — summary: {json.dumps(summary, indent=2)}")

    # Verify ZIP contents
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = zf.namelist()
    print(f"  ZIP contents: {names}")
    assert len(names) == 2
    assert any("Blue/" in n for n in names)
    assert any("Red/" in n for n in names)

    # Verify the output PDFs are valid and colorspaces were replaced
    for name in names:
        pdf_data = zf.read(name)
        pdf = pikepdf.open(io.BytesIO(pdf_data))
        page = pdf.pages[0]
        cs_dict = page[Name.Resources][Name.ColorSpace]
        for key in cs_dict.keys():
            cs = cs_dict[key]
            if str(cs[0]) == "/Separation":
                alt = str(cs[2])
                # Should be DeviceCMYK now (not DeviceGray)
                assert alt == "/DeviceCMYK", f"Expected /DeviceCMYK in {name}, got {alt}"
        pdf.close()

    print("PASS: process — ZIP verified, all colorspaces replaced with DeviceCMYK")


if __name__ == "__main__":
    test_frontend_served()
    test_upload()
    test_presets()
    test_process()
    print("\nAll e2e tests passed!")
