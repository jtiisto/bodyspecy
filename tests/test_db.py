"""Tests for database layer with in-memory SQLite."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from bodyspecy.localdb.db import BodyspecDB, LBS_TO_KG, IN3_TO_CM3
from bodyspecy.localdb.models import Base, Scan, ScanRegion, ScanBoneDensity


@pytest.fixture
def db(tmp_path):
    """Create a BodyspecDB with a temporary SQLite database."""
    return BodyspecDB(tmp_path / "test.db")


class TestImportScan:
    """Test importing a ParsedScan into the database."""

    def test_import_scan_inserts_correctly(self, db, sample_parsed_scan):
        db.import_scan(sample_parsed_scan)

        with db.get_session() as session:
            scan = session.query(Scan).filter_by(
                scan_date=date(2026, 1, 23)
            ).one()
            assert scan.client_name == "Doe, John"
            assert scan.sex == "Male"
            assert scan.birth_date == date(1990, 1, 15)
            assert scan.total_body_fat_pct == 30.9
            assert scan.rmr_kcal == 1606
            assert scan.ag_ratio == 1.31

    def test_import_scan_creates_regions(self, db, sample_parsed_scan):
        db.import_scan(sample_parsed_scan)

        with db.get_session() as session:
            regions = session.query(ScanRegion).filter_by(
                scan_date=date(2026, 1, 23)
            ).all()
            region_names = {r.region for r in regions}
            # 6 from regional assessment + 4 from muscle balance = 10
            assert len(regions) == 10
            assert "arms" in region_names
            assert "right_arm" in region_names
            assert "left_leg" in region_names

    def test_import_scan_creates_bone_density(self, db, sample_parsed_scan):
        db.import_scan(sample_parsed_scan)

        with db.get_session() as session:
            bones = session.query(ScanBoneDensity).filter_by(
                scan_date=date(2026, 1, 23)
            ).all()
            assert len(bones) == 8
            bone_map = {b.region: b for b in bones}
            assert bone_map["head"].bmd_g_cm2 == 2.183
            assert bone_map["total"].t_score == 1.5
            assert bone_map["total"].z_score == 1.5
            assert bone_map["arms"].t_score is None


class TestIdempotentImport:
    """Test that re-importing the same scan date is idempotent (upsert)."""

    def test_upsert_same_scan_date(self, db, sample_parsed_scan):
        db.import_scan(sample_parsed_scan)
        db.import_scan(sample_parsed_scan)

        with db.get_session() as session:
            scans = session.query(Scan).all()
            assert len(scans) == 1

            regions = session.query(ScanRegion).filter_by(
                scan_date=date(2026, 1, 23)
            ).all()
            assert len(regions) == 10

            bones = session.query(ScanBoneDensity).filter_by(
                scan_date=date(2026, 1, 23)
            ).all()
            assert len(bones) == 8


class TestGetSyncedScanDates:
    """Test retrieving synced scan dates."""

    def test_empty_db_returns_empty_set(self, db):
        assert db.get_synced_scan_dates() == set()

    def test_returns_correct_dates(self, db, sample_parsed_scan, second_parsed_scan):
        db.import_scan(sample_parsed_scan)
        db.import_scan(second_parsed_scan)

        dates = db.get_synced_scan_dates()
        assert dates == {date(2026, 1, 23), date(2024, 2, 23)}


class TestUnitConversions:
    """Test that imperial → metric conversions are applied correctly."""

    def test_weight_conversion(self, db, sample_parsed_scan):
        db.import_scan(sample_parsed_scan)

        with db.get_session() as session:
            scan = session.query(Scan).one()
            # total_mass_lbs=193.2
            assert scan.total_mass_kg == pytest.approx(193.2 * LBS_TO_KG, rel=1e-4)
            assert scan.fat_mass_kg == pytest.approx(59.7 * LBS_TO_KG, rel=1e-4)
            assert scan.lean_mass_kg == pytest.approx(126.6 * LBS_TO_KG, rel=1e-4)
            assert scan.bone_mineral_content_kg == pytest.approx(
                7.0 * LBS_TO_KG, rel=1e-4
            )

    def test_vat_volume_conversion(self, db, sample_parsed_scan):
        db.import_scan(sample_parsed_scan)

        with db.get_session() as session:
            scan = session.query(Scan).one()
            # vat_mass_lbs=3.70, vat_volume_in3=108.62
            assert scan.vat_mass_kg == pytest.approx(3.70 * LBS_TO_KG, rel=1e-4)
            assert scan.vat_volume_cm3 == pytest.approx(
                108.62 * IN3_TO_CM3, rel=1e-4
            )

    def test_region_mass_conversion(self, db, sample_parsed_scan):
        db.import_scan(sample_parsed_scan)

        with db.get_session() as session:
            arms = session.query(ScanRegion).filter_by(
                scan_date=date(2026, 1, 23), region="arms"
            ).one()
            # Arms: total_mass_lbs=24.2, fat_mass_lbs=5.5, lean_mass_lbs=17.5
            assert arms.total_mass_kg == pytest.approx(24.2 * LBS_TO_KG, rel=1e-4)
            assert arms.fat_mass_kg == pytest.approx(5.5 * LBS_TO_KG, rel=1e-4)
            assert arms.lean_mass_kg == pytest.approx(17.5 * LBS_TO_KG, rel=1e-4)
            # Percentages are NOT converted
            assert arms.fat_pct == 22.8

    def test_bmd_not_converted(self, db, sample_parsed_scan):
        """BMD is already metric in the PDF — should be stored as-is."""
        db.import_scan(sample_parsed_scan)

        with db.get_session() as session:
            head = session.query(ScanBoneDensity).filter_by(
                scan_date=date(2026, 1, 23), region="head"
            ).one()
            assert head.bmd_g_cm2 == 2.183

    def test_total_bmd_extracted(self, db, sample_parsed_scan):
        """Total BMD, T-score, Z-score should be on the scan record."""
        db.import_scan(sample_parsed_scan)

        with db.get_session() as session:
            scan = session.query(Scan).one()
            assert scan.total_bmd_g_cm2 == 1.355
            assert scan.total_t_score == 1.5
            assert scan.total_z_score == 1.5
