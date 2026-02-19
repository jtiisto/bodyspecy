"""SQLAlchemy database for DEXA scan data."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, Scan, ScanBoneDensity, ScanRegion


LBS_TO_KG = 0.45359237
IN_TO_CM = 2.54
IN3_TO_CM3 = 16.387064


def _get_total_bmd(parsed_scan) -> Optional[float]:
    for b in parsed_scan.bone_density:
        if b.region.lower() == "total":
            return b.bmd_g_cm2
    return None


def _get_total_score(parsed_scan, attr: str) -> Optional[float]:
    for b in parsed_scan.bone_density:
        if b.region.lower() == "total":
            return getattr(b, attr, None)
    return None


class BodyspecDB:
    """SQLAlchemy database for DEXA scan data."""

    def __init__(self, db_path: Path):
        self.db_path = db_path

        # Ensure parent directory exists
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(f"sqlite:///{db_path}")
        self.SessionLocal = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)

    def get_session(self) -> Session:
        return self.SessionLocal()

    def import_scan(self, parsed_scan) -> None:
        """Import a ParsedScan into the database. Upserts by scan_date."""
        with self.get_session() as session:
            # Main scan record
            scan = Scan(
                scan_date=parsed_scan.scan_date,
                client_name=parsed_scan.client_name,
                sex=parsed_scan.sex,
                birth_date=parsed_scan.birth_date,
                height_cm=parsed_scan.height_in * IN_TO_CM,
                weight_kg=parsed_scan.weight_lbs * LBS_TO_KG,
                total_body_fat_pct=parsed_scan.total_body_fat_pct,
                total_mass_kg=parsed_scan.total_mass_lbs * LBS_TO_KG,
                fat_mass_kg=parsed_scan.fat_tissue_lbs * LBS_TO_KG,
                lean_mass_kg=parsed_scan.lean_tissue_lbs * LBS_TO_KG,
                bone_mineral_content_kg=parsed_scan.bmc_lbs * LBS_TO_KG,
                rmr_kcal=parsed_scan.rmr_kcal,
                android_fat_pct=parsed_scan.android_fat_pct,
                gynoid_fat_pct=parsed_scan.gynoid_fat_pct,
                ag_ratio=parsed_scan.ag_ratio,
                vat_mass_kg=parsed_scan.vat_mass_lbs * LBS_TO_KG,
                vat_volume_cm3=parsed_scan.vat_volume_in3 * IN3_TO_CM3,
                total_bmd_g_cm2=_get_total_bmd(parsed_scan),
                total_t_score=_get_total_score(parsed_scan, "t_score"),
                total_z_score=_get_total_score(parsed_scan, "z_score"),
                pdf_path=parsed_scan.pdf_path,
                imported_at=datetime.now(timezone.utc),
            )
            session.merge(scan)

            # Regional assessment regions
            for r in parsed_scan.regional_assessment:
                region = ScanRegion(
                    scan_date=parsed_scan.scan_date,
                    region=r.region.lower(),
                    fat_pct=r.fat_pct,
                    total_mass_kg=r.total_mass_lbs * LBS_TO_KG,
                    fat_mass_kg=r.fat_mass_lbs * LBS_TO_KG,
                    lean_mass_kg=r.lean_mass_lbs * LBS_TO_KG,
                    bone_mineral_content_kg=r.bmc_lbs * LBS_TO_KG,
                )
                session.merge(region)

            # Muscle balance (left/right sub-regions)
            for r in parsed_scan.muscle_balance:
                region = ScanRegion(
                    scan_date=parsed_scan.scan_date,
                    region=r.region,  # already normalized to snake_case
                    fat_pct=r.fat_pct,
                    total_mass_kg=r.total_mass_lbs * LBS_TO_KG,
                    fat_mass_kg=r.fat_mass_lbs * LBS_TO_KG,
                    lean_mass_kg=r.lean_mass_lbs * LBS_TO_KG,
                    bone_mineral_content_kg=r.bmc_lbs * LBS_TO_KG,
                )
                session.merge(region)

            # Bone density
            for b in parsed_scan.bone_density:
                bone = ScanBoneDensity(
                    scan_date=parsed_scan.scan_date,
                    region=b.region.lower(),
                    bmd_g_cm2=b.bmd_g_cm2,
                    t_score=b.t_score,
                    z_score=b.z_score,
                )
                session.merge(bone)

            session.commit()

    def get_synced_scan_dates(self) -> set:
        """Get set of scan dates already in the database."""
        with self.get_session() as session:
            rows = session.query(Scan.scan_date).all()
            return {row[0] for row in rows}
