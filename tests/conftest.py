"""Shared fixtures for bodyspecy tests."""

import os
from datetime import date
from pathlib import Path

import pytest

from bodyspecy.parser.models import ParsedBoneDensity, ParsedRegion, ParsedScan

PDF_DIR = Path(os.environ.get("BODYSPECY_TEST_PDF_DIR", ""))


@pytest.fixture
def pdf_dir():
    """Path to directory containing BodySpec PDF reports."""
    return PDF_DIR


@pytest.fixture
def sample_parsed_scan():
    """A manually constructed ParsedScan for DB/MCP tests (anonymized)."""
    return ParsedScan(
        scan_date=date(2026, 1, 23),
        client_name="Doe, John",
        sex="Male",
        birth_date=date(1990, 1, 15),
        total_body_fat_pct=30.9,
        total_mass_lbs=193.2,
        fat_tissue_lbs=59.7,
        lean_tissue_lbs=126.6,
        bmc_lbs=7.0,
        rmr_kcal=1606,
        android_fat_pct=38.8,
        gynoid_fat_pct=29.6,
        ag_ratio=1.31,
        vat_mass_lbs=3.70,
        vat_volume_in3=108.62,
        regional_assessment=[
            ParsedRegion("Arms", 22.8, 24.2, 5.5, 17.5, 1.1),
            ParsedRegion("Legs", 29.7, 64.3, 19.1, 42.4, 2.8),
            ParsedRegion("Trunk", 35.0, 94.4, 33.1, 59.4, 1.9),
            ParsedRegion("Android", 38.8, 15.3, 5.9, 9.3, 0.1),
            ParsedRegion("Gynoid", 29.6, 31.9, 9.2, 22.0, 0.7),
            ParsedRegion("Total", 30.9, 193.2, 59.7, 126.6, 7.0),
        ],
        muscle_balance=[
            ParsedRegion("right_arm", 22.1, 12.1, 2.7, 8.8, 0.6),
            ParsedRegion("left_arm", 23.6, 12.2, 2.9, 8.7, 0.6),
            ParsedRegion("right_leg", 30.4, 32.2, 9.8, 20.9, 1.4),
            ParsedRegion("left_leg", 28.9, 32.2, 9.3, 21.5, 1.4),
        ],
        bone_density=[
            ParsedBoneDensity("Head", 2.183),
            ParsedBoneDensity("Arms", 1.214),
            ParsedBoneDensity("Legs", 1.485),
            ParsedBoneDensity("Trunk", 1.062),
            ParsedBoneDensity("Ribs", 0.949),
            ParsedBoneDensity("Spine", 1.129),
            ParsedBoneDensity("Pelvis", 1.142),
            ParsedBoneDensity("Total", 1.355, t_score=1.5, z_score=1.5),
        ],
        pdf_path="/fake/path/report-01-23-2026.pdf",
    )


@pytest.fixture
def second_parsed_scan():
    """A second ParsedScan (baseline) for multi-scan DB tests (anonymized)."""
    return ParsedScan(
        scan_date=date(2024, 2, 23),
        client_name="Doe, John",
        sex="Male",
        birth_date=date(1990, 1, 15),
        total_body_fat_pct=28.1,
        total_mass_lbs=194.6,
        fat_tissue_lbs=54.6,
        lean_tissue_lbs=133.3,
        bmc_lbs=6.7,
        rmr_kcal=1663,
        android_fat_pct=37.3,
        gynoid_fat_pct=27.8,
        ag_ratio=1.34,
        vat_mass_lbs=2.98,
        vat_volume_in3=87.56,
        regional_assessment=[
            ParsedRegion("Arms", 23.7, 25.4, 6.0, 18.2, 1.2),
            ParsedRegion("Legs", 27.2, 65.2, 17.7, 44.8, 2.7),
            ParsedRegion("Trunk", 31.6, 93.6, 29.5, 62.5, 1.6),
            ParsedRegion("Android", 37.3, 15.8, 5.9, 9.8, 0.1),
            ParsedRegion("Gynoid", 27.8, 31.6, 8.8, 22.2, 0.6),
            ParsedRegion("Total", 28.1, 194.6, 54.6, 133.3, 6.7),
        ],
        muscle_balance=[
            ParsedRegion("right_arm", 22.5, 12.8, 2.9, 9.3, 0.6),
            ParsedRegion("left_arm", 25.0, 12.6, 3.2, 8.8, 0.6),
            ParsedRegion("right_leg", 27.5, 32.9, 9.1, 22.5, 1.3),
            ParsedRegion("left_leg", 26.8, 32.4, 8.7, 22.3, 1.4),
        ],
        bone_density=[
            ParsedBoneDensity("Head", 2.088),
            ParsedBoneDensity("Arms", 1.204),
            ParsedBoneDensity("Legs", 1.459),
            ParsedBoneDensity("Trunk", 1.027),
            ParsedBoneDensity("Ribs", 0.919),
            ParsedBoneDensity("Spine", 1.097),
            ParsedBoneDensity("Pelvis", 1.091),
            ParsedBoneDensity("Total", 1.326, t_score=1.2, z_score=1.2),
        ],
        pdf_path="/fake/path/report-02-23-2024.pdf",
    )
