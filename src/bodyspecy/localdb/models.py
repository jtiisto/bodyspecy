"""SQLAlchemy ORM models for DEXA scan data."""

from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Float, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Scan(Base):
    """Primary scan data — one row per DEXA scan."""

    __tablename__ = "scans"

    scan_date = Column(Date, primary_key=True)
    client_name = Column(String)
    sex = Column(String)
    birth_date = Column(Date)
    total_body_fat_pct = Column(Float)
    total_mass_kg = Column(Float)
    fat_mass_kg = Column(Float)
    lean_mass_kg = Column(Float)
    bone_mineral_content_kg = Column(Float)
    rmr_kcal = Column(Float)
    android_fat_pct = Column(Float)
    gynoid_fat_pct = Column(Float)
    ag_ratio = Column(Float)
    vat_mass_kg = Column(Float)
    vat_volume_cm3 = Column(Float)
    total_bmd_g_cm2 = Column(Float)
    total_t_score = Column(Float)  # nullable
    total_z_score = Column(Float)  # nullable
    pdf_path = Column(Text)
    imported_at = Column(DateTime, default=datetime.utcnow)


class ScanRegion(Base):
    """Body composition by region."""

    __tablename__ = "scan_regions"

    scan_date = Column(Date, primary_key=True)
    region = Column(
        String, primary_key=True
    )  # arms, legs, trunk, android, gynoid, total, right_arm, left_arm, right_leg, left_leg
    fat_pct = Column(Float)
    total_mass_kg = Column(Float)
    fat_mass_kg = Column(Float)
    lean_mass_kg = Column(Float)
    bone_mineral_content_kg = Column(Float)


class ScanBoneDensity(Base):
    """Bone mineral density by region."""

    __tablename__ = "scan_bone_density"

    scan_date = Column(Date, primary_key=True)
    region = Column(
        String, primary_key=True
    )  # head, arms, legs, trunk, ribs, spine, pelvis, total
    bmd_g_cm2 = Column(Float)
    t_score = Column(Float)  # nullable
    z_score = Column(Float)  # nullable
