"""Dataclasses for parsed scan data."""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class ParsedRegion:
    """Body composition for a single region."""
    region: str              # e.g. "arms", "right_arm"
    fat_pct: float           # percentage
    total_mass_lbs: float
    fat_mass_lbs: float
    lean_mass_lbs: float
    bmc_lbs: float


@dataclass
class ParsedBoneDensity:
    """Bone density for a single region."""
    region: str              # e.g. "head", "total"
    bmd_g_cm2: float
    t_score: Optional[float] = None
    z_score: Optional[float] = None


@dataclass
class ParsedScan:
    """Complete parsed data from one PDF report."""
    # Header
    scan_date: date
    client_name: str
    sex: str
    birth_date: date
    height_in: float
    weight_lbs: float

    # Summary Results (current scan row only)
    total_body_fat_pct: float
    total_mass_lbs: float
    fat_tissue_lbs: float
    lean_tissue_lbs: float
    bmc_lbs: float

    # Supplemental Results
    rmr_kcal: float
    android_fat_pct: float
    gynoid_fat_pct: float
    ag_ratio: float

    # VAT
    vat_mass_lbs: float
    vat_volume_in3: float

    # Regional Assessment (6 aggregate regions: arms, legs, trunk, android, gynoid, total)
    regional_assessment: list[ParsedRegion] = field(default_factory=list)

    # Muscle Balance (4 left/right sub-regions only: right_arm, left_arm, right_leg, left_leg)
    # "Arms Total" and "Legs Total" rows are skipped — identical to Regional Assessment's Arms/Legs
    muscle_balance: list[ParsedRegion] = field(default_factory=list)

    # Bone Density (8 regions)
    bone_density: list[ParsedBoneDensity] = field(default_factory=list)

    # Source file
    pdf_path: str = ""
