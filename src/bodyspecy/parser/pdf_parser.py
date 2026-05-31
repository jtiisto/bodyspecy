"""PDF parser for BodySpec DEXA reports."""

import re
from datetime import date, datetime
from pathlib import Path

import pdfplumber

from .models import ParsedBoneDensity, ParsedRegion, ParsedScan

# Regex patterns
HEADER_RE = re.compile(
    r'(.+?)\s+(Male|Female)\s+(\d{1,2}/\d{1,2}/\d{4})\s+'
    r'(?:[\d.]+)\s*in\.\s+(?:[\d.]+)\s*lbs\.\s+(\d{1,2}/\d{1,2}/\d{4})'
)

SUMMARY_ROW_RE = re.compile(
    r'(\d{1,2}/\d{1,2}/\d{4})\s+([\d.]+)%\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)'
)

REGIONAL_ROW_RE = re.compile(
    r'(Arms|Legs|Trunk|Android|Gynoid|Total)\s+([\d.]+)%\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)'
)

SUPPLEMENTAL_RE = re.compile(
    r'([\d,]+)\s*cal/day\s+([\d.]+)%\s+([\d.]+)%\s+([\d.]+)'
)

BONE_RE = re.compile(
    r'(Head|Arms|Legs|Trunk|Ribs|Spine|Pelvis|Total)\s+([\d.]+)\s+([\d.]+|-)\s+([\d.]+|-)'
)

VAT_MASS_RE = re.compile(r'Mass \(lbs\)\s+([\d.]+)')
VAT_VOLUME_RE = re.compile(r'Volume \(in[³3]\)\s+([\d.]+)')

MUSCLE_RE = re.compile(
    r'(Right Arm|Left Arm|Right Leg|Left Leg)\s+'
    r'([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)'
)


def parse_date_mdy(s: str) -> date:
    """Parse M/D/YYYY date string."""
    return datetime.strptime(s, "%m/%d/%Y").date()


def parse_pdf(pdf_path: str | Path) -> ParsedScan:
    """Parse a BodySpec DEXA PDF report and return structured data.

    Only extracts the CURRENT scan's data (most recent row in any table).
    """
    pdf_path = Path(pdf_path)

    with pdfplumber.open(pdf_path) as pdf:
        # Combine pages 2 and 3 text (0-indexed: pages[1] and pages[2])
        # Page 1 (index 0) is always the intro page — skip
        page2_text = pdf.pages[1].extract_text() if len(pdf.pages) > 1 else ""
        page3_text = pdf.pages[2].extract_text() if len(pdf.pages) > 2 else ""

    # Parse header from page 2
    header = _parse_header(page2_text)

    # Parse summary results from page 2 (first row = current scan)
    summary = _parse_summary(page2_text)

    # Parse regional assessment from page 2
    regional = _parse_regional_assessment(page2_text)

    # Parse supplemental results from page 3
    supplemental = _parse_supplemental(page3_text)

    # Parse VAT from page 3
    vat = _parse_vat(page3_text)

    # Parse bone density from page 3
    bones = _parse_bone_density(page3_text)

    # Parse muscle balance from page 3
    muscles = _parse_muscle_balance(page3_text)

    return ParsedScan(
        scan_date=header["scan_date"],
        client_name=header["client_name"],
        sex=header["sex"],
        birth_date=header["birth_date"],
        total_body_fat_pct=summary["fat_pct"],
        total_mass_lbs=summary["total_mass"],
        fat_tissue_lbs=summary["fat_tissue"],
        lean_tissue_lbs=summary["lean_tissue"],
        bmc_lbs=summary["bmc"],
        rmr_kcal=supplemental["rmr"],
        android_fat_pct=supplemental["android"],
        gynoid_fat_pct=supplemental["gynoid"],
        ag_ratio=supplemental["ag_ratio"],
        vat_mass_lbs=vat["mass"],
        vat_volume_in3=vat["volume"],
        regional_assessment=regional,
        muscle_balance=muscles,
        bone_density=bones,
        pdf_path=str(pdf_path.resolve()),
    )


def _parse_header(text: str) -> dict:
    """Parse client header from page text."""
    m = HEADER_RE.search(text)
    if not m:
        raise ValueError("Could not find header (client name, sex, dates) in page text")
    return {
        "client_name": m.group(1).strip(),
        "sex": m.group(2),
        "birth_date": parse_date_mdy(m.group(3)),
        "scan_date": parse_date_mdy(m.group(4)),
    }


def _parse_summary(text: str) -> dict:
    """Parse first summary row (current scan) from page 2 text."""
    m = SUMMARY_ROW_RE.search(text)
    if not m:
        raise ValueError("Could not find summary results row in page text")
    return {
        "date": parse_date_mdy(m.group(1)),
        "fat_pct": float(m.group(2)),
        "total_mass": float(m.group(3)),
        "fat_tissue": float(m.group(4)),
        "lean_tissue": float(m.group(5)),
        "bmc": float(m.group(6)),
    }


def _parse_regional_assessment(text: str) -> list[ParsedRegion]:
    """Parse regional assessment table from page 2 text."""
    matches = REGIONAL_ROW_RE.findall(text)
    if not matches:
        raise ValueError("Could not find regional assessment data in page text")
    regions = []
    for m in matches:
        regions.append(ParsedRegion(
            region=m[0],
            fat_pct=float(m[1]),
            total_mass_lbs=float(m[2]),
            fat_mass_lbs=float(m[3]),
            lean_mass_lbs=float(m[4]),
            bmc_lbs=float(m[5]),
        ))
    return regions


def _parse_supplemental(text: str) -> dict:
    """Parse first supplemental results row (current scan) from page 3 text."""
    m = SUPPLEMENTAL_RE.search(text)
    if not m:
        raise ValueError("Could not find supplemental results in page text")
    return {
        "rmr": float(m.group(1).replace(",", "")),
        "android": float(m.group(2)),
        "gynoid": float(m.group(3)),
        "ag_ratio": float(m.group(4)),
    }


def _parse_vat(text: str) -> dict:
    """Parse VAT mass and volume from page 3 text."""
    mass_m = VAT_MASS_RE.search(text)
    if not mass_m:
        raise ValueError("Could not find VAT mass in page text")
    vol_m = VAT_VOLUME_RE.search(text)
    if not vol_m:
        raise ValueError("Could not find VAT volume in page text")
    return {
        "mass": float(mass_m.group(1)),
        "volume": float(vol_m.group(1)),
    }


def _parse_bone_density(text: str) -> list[ParsedBoneDensity]:
    """Parse bone density table from page 3 text.

    Searches only between 'Bone Density' and 'MUSCLE BALANCE REPORT' headers
    to avoid false positives.
    """
    # Extract text between bone density section and muscle balance section
    bone_start = text.find("Bone Density")
    muscle_start = text.find("MUSCLE BALANCE REPORT")
    if bone_start == -1:
        raise ValueError("Could not find 'Bone Density' section header in page text")
    if muscle_start == -1:
        raise ValueError("Could not find 'MUSCLE BALANCE REPORT' section header in page text")
    bone_text = text[bone_start:muscle_start]

    matches = BONE_RE.findall(bone_text)
    if not matches:
        raise ValueError("Could not find bone density data in page text")

    bones = []
    for m in matches:
        t_score = None if m[2] == "-" else float(m[2])
        z_score = None if m[3] == "-" else float(m[3])
        bones.append(ParsedBoneDensity(
            region=m[0],
            bmd_g_cm2=float(m[1]),
            t_score=t_score,
            z_score=z_score,
        ))
    return bones


def _parse_muscle_balance(text: str) -> list[ParsedRegion]:
    """Parse muscle balance report from page 3 text.

    Only extracts 4 left/right sub-regions (skips Arms Total / Legs Total).
    Normalizes names: 'Right Arm' → 'right_arm', etc.
    """
    start = text.find("MUSCLE BALANCE REPORT")
    if start == -1:
        raise ValueError("Could not find 'MUSCLE BALANCE REPORT' section header in page text")
    muscle_text = text[start:]

    matches = MUSCLE_RE.findall(muscle_text)
    if not matches:
        raise ValueError("Could not find muscle balance data in page text")

    regions = []
    for m in matches:
        # Normalize: "Right Arm" → "right_arm"
        name = m[0].lower().replace(" ", "_")
        regions.append(ParsedRegion(
            region=name,
            fat_pct=float(m[1]),
            total_mass_lbs=float(m[2]),
            fat_mass_lbs=float(m[3]),
            lean_mass_lbs=float(m[4]),
            bmc_lbs=float(m[5]),
        ))
    return regions
