"""
Tests for PDF spot color detection and color mapping.
Creates synthetic PDFs with Separation colorspaces and verifies
detection and replacement logic.
"""

import io
import pikepdf
from pikepdf import Name, Array, Dictionary, Stream
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.pdf_processor import detect_spot_colors, apply_color_map


def _create_test_pdf_with_spots(spot_names: list[str]) -> bytes:
    """
    Create a minimal PDF that has Separation colorspaces for the given spot names.
    Each spot gets a dummy tint transform (identity to DeviceGray).
    """
    pdf = pikepdf.new()
    page_dict = Dictionary({
        "/Type": Name.Page,
        "/MediaBox": Array([0, 0, 612, 792]),
    })
    page = pikepdf.Page(pdf.make_indirect(page_dict))

    # Build colorspace dictionary
    cs_dict = Dictionary()
    for i, spot_name in enumerate(spot_names):
        tint_fn = Dictionary({
            "/FunctionType": 2,
            "/Domain": Array([0.0, 1.0]),
            "/Range": Array([0.0, 1.0]),
            "/C0": Array([0.0]),
            "/C1": Array([1.0]),
            "/N": 1,
        })
        cs_array = Array([
            Name.Separation,
            Name(f"/{spot_name}"),
            Name.DeviceGray,
            pdf.make_indirect(tint_fn),
        ])
        cs_dict[f"/CS{i}"] = cs_array

    resources = Dictionary({
        "/ColorSpace": cs_dict,
    })
    page.obj[Name.Resources] = resources
    pdf.pages.append(page)

    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


def _create_test_pdf_with_form_xobject(spot_name: str) -> bytes:
    """
    Create a PDF where a spot color is inside a Form XObject's resources
    (to test recursive scanning).
    """
    pdf = pikepdf.new()

    tint_fn = Dictionary({
        "/FunctionType": 2,
        "/Domain": Array([0.0, 1.0]),
        "/Range": Array([0.0, 1.0]),
        "/C0": Array([0.0]),
        "/C1": Array([1.0]),
        "/N": 1,
    })

    cs_array = Array([
        Name.Separation,
        Name(f"/{spot_name}"),
        Name.DeviceGray,
        pdf.make_indirect(tint_fn),
    ])

    form_resources = Dictionary({
        "/ColorSpace": Dictionary({
            "/CS0": cs_array,
        }),
    })

    # Minimal content stream
    form_stream = Stream(pdf, b"")
    form_stream[Name.Type] = Name.XObject
    form_stream[Name.Subtype] = Name.Form
    form_stream[Name.BBox] = Array([0, 0, 100, 100])
    form_stream[Name.Resources] = form_resources

    page_dict = Dictionary({
        "/Type": Name.Page,
        "/MediaBox": Array([0, 0, 612, 792]),
        "/Resources": Dictionary({
            "/XObject": Dictionary({
                "/Form0": pdf.make_indirect(form_stream),
            }),
        }),
    })
    page = pikepdf.Page(pdf.make_indirect(page_dict))
    pdf.pages.append(page)

    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


def test_detect_single_spot():
    pdf_bytes = _create_test_pdf_with_spots(["PANTONE 286 C"])
    spots = detect_spot_colors(pdf_bytes)
    assert spots == ["PANTONE 286 C"], f"Expected ['PANTONE 286 C'], got {spots}"
    print("PASS: test_detect_single_spot")


def test_detect_multiple_spots():
    names = ["PANTONE 286 C", "PANTONE 485 C", "Gold Foil"]
    pdf_bytes = _create_test_pdf_with_spots(names)
    spots = detect_spot_colors(pdf_bytes)
    assert spots == sorted(names), f"Expected {sorted(names)}, got {spots}"
    print("PASS: test_detect_multiple_spots")


def test_detect_spot_in_xobject():
    pdf_bytes = _create_test_pdf_with_form_xobject("Varnish Spot")
    spots = detect_spot_colors(pdf_bytes)
    assert spots == ["Varnish Spot"], f"Expected ['Varnish Spot'], got {spots}"
    print("PASS: test_detect_spot_in_xobject")


def test_detect_no_spots():
    """A blank PDF with no colorspaces should return empty list."""
    pdf = pikepdf.new()
    page_dict = Dictionary({
        "/Type": Name.Page,
        "/MediaBox": Array([0, 0, 612, 792]),
    })
    page = pikepdf.Page(pdf.make_indirect(page_dict))
    pdf.pages.append(page)
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()

    spots = detect_spot_colors(buf.getvalue())
    assert spots == [], f"Expected [], got {spots}"
    print("PASS: test_detect_no_spots")


def test_apply_color_map():
    pdf_bytes = _create_test_pdf_with_spots(["PANTONE 286 C", "Unknown Spot"])
    color_map = {
        "PANTONE 286 C": {"c": 1.0, "m": 0.66, "y": 0.0, "k": 0.02},
    }

    output_bytes, replaced, unmatched = apply_color_map(pdf_bytes, color_map)

    assert "PANTONE 286 C" in replaced, f"Expected 'PANTONE 286 C' in replaced, got {replaced}"
    assert "Unknown Spot" in unmatched, f"Expected 'Unknown Spot' in unmatched, got {unmatched}"

    # Verify the output PDF is valid and the colorspace was changed
    out_pdf = pikepdf.open(io.BytesIO(output_bytes))
    page = out_pdf.pages[0]
    cs_dict = page[Name.Resources][Name.ColorSpace]

    # Find the CS for PANTONE 286 C
    found_cmyk = False
    for key in cs_dict.keys():
        cs = cs_dict[key]
        if len(cs) >= 4:
            cs_type = str(cs[0]).lstrip("/")
            if cs_type == "Separation":
                spot = str(cs[1]).lstrip("/")
                if spot == "PANTONE 286 C":
                    alt_space = str(cs[2]).lstrip("/")
                    assert alt_space == "DeviceCMYK", \
                        f"Expected DeviceCMYK, got {alt_space}"
                    # Verify tint transform
                    fn = cs[3]
                    assert float(fn[Name.C1][0]) == 1.0, "C value mismatch"
                    assert float(fn[Name.C1][1]) == 0.66, "M value mismatch"
                    assert float(fn[Name.C1][2]) == 0.0, "Y value mismatch"
                    assert float(fn[Name.C1][3]) == 0.02, "K value mismatch"
                    found_cmyk = True

    assert found_cmyk, "Did not find the replaced CMYK colorspace"
    out_pdf.close()
    print("PASS: test_apply_color_map")


def test_apply_color_map_xobject():
    pdf_bytes = _create_test_pdf_with_form_xobject("PANTONE 485 C")
    color_map = {
        "PANTONE 485 C": {"c": 0.0, "m": 0.95, "y": 1.0, "k": 0.0},
    }

    output_bytes, replaced, unmatched = apply_color_map(pdf_bytes, color_map)
    assert "PANTONE 485 C" in replaced
    assert len(unmatched) == 0
    print("PASS: test_apply_color_map_xobject")


if __name__ == "__main__":
    test_detect_single_spot()
    test_detect_multiple_spots()
    test_detect_spot_in_xobject()
    test_detect_no_spots()
    test_apply_color_map()
    test_apply_color_map_xobject()
    print("\nAll tests passed!")
