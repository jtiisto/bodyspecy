"""Tests for PDF parser against real BodySpec DEXA reports.

These tests require actual PDF files and are skipped when not available.
Set BODYSPECY_TEST_PDF_DIR to the directory containing bodyspec-results_*.pdf files.
"""

import os
from pathlib import Path

import pytest

from bodyspecy.parser import parse_pdf

PDF_DIR = Path(os.environ.get("BODYSPECY_TEST_PDF_DIR", ""))
_pdfs_available = PDF_DIR.is_dir() and any(PDF_DIR.glob("bodyspec-results_*.pdf"))

pytestmark = pytest.mark.skipif(
    not _pdfs_available,
    reason="Set BODYSPECY_TEST_PDF_DIR to directory with bodyspec-results_*.pdf files",
)


class TestParseLatestReport:
    """Test against the most recent report with known values."""

    @pytest.fixture
    def scan(self):
        pdfs = sorted(PDF_DIR.glob("bodyspec-results_*.pdf"))
        return parse_pdf(pdfs[-1])  # most recent by filename sort

    def test_header_fields_present(self, scan):
        assert scan.client_name
        assert scan.sex in ("Male", "Female")
        assert scan.birth_date is not None
        assert scan.scan_date is not None

    def test_summary(self, scan):
        assert scan.total_body_fat_pct > 0
        assert scan.total_mass_lbs > 0
        assert scan.fat_tissue_lbs > 0
        assert scan.lean_tissue_lbs > 0
        assert scan.bmc_lbs > 0

    def test_supplemental(self, scan):
        assert scan.rmr_kcal > 0
        assert scan.android_fat_pct > 0
        assert scan.gynoid_fat_pct > 0
        assert scan.ag_ratio > 0

    def test_vat(self, scan):
        assert scan.vat_mass_lbs > 0
        assert scan.vat_volume_in3 > 0

    def test_regional_assessment(self, scan):
        regions = {r.region: r for r in scan.regional_assessment}
        assert len(regions) == 6  # Arms, Legs, Trunk, Android, Gynoid, Total
        assert "Arms" in regions
        assert regions["Arms"].fat_pct > 0
        assert regions["Arms"].total_mass_lbs > 0

    def test_bone_density(self, scan):
        bones = {b.region: b for b in scan.bone_density}
        assert len(bones) == 8  # Head, Arms, Legs, Trunk, Ribs, Spine, Pelvis, Total
        assert bones["Total"].bmd_g_cm2 > 0
        assert bones["Total"].t_score is not None
        assert bones["Total"].z_score is not None
        assert bones["Arms"].t_score is None

    def test_muscle_balance(self, scan):
        muscles = {r.region: r for r in scan.muscle_balance}
        assert len(muscles) == 4  # right_arm, left_arm, right_leg, left_leg
        for region in ("right_arm", "left_arm", "right_leg", "left_leg"):
            assert region in muscles
            assert muscles[region].fat_pct > 0


class TestParseBaselineReport:
    """Test against the earliest report (baseline)."""

    @pytest.fixture
    def scan(self):
        pdfs = sorted(PDF_DIR.glob("bodyspec-results_*.pdf"))
        return parse_pdf(pdfs[0])  # earliest by filename sort

    def test_header(self, scan):
        assert scan.scan_date is not None

    def test_summary(self, scan):
        assert scan.total_body_fat_pct > 0
        assert scan.total_mass_lbs > 0

    def test_vat(self, scan):
        assert scan.vat_mass_lbs > 0
        assert scan.vat_volume_in3 > 0


class TestParseAllReports:
    """Ensure all PDFs parse without errors."""

    def test_all_pdfs_parse(self):
        pdfs = sorted(PDF_DIR.glob("bodyspec-results_*.pdf"))
        assert len(pdfs) >= 1
        for pdf in pdfs:
            scan = parse_pdf(pdf)
            assert scan.scan_date is not None
            assert scan.total_body_fat_pct > 0
            assert len(scan.bone_density) == 8
            assert len(scan.regional_assessment) == 6
