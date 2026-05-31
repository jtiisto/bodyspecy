"""BodySpec DEXA MCP Server implementation.

Provides secure, read-only access to DEXA scan data through the Model Context
Protocol with optimized tools for LLM understanding. Follows garmy patterns.
"""

import logging
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from fastmcp import FastMCP
except ImportError:
    raise ImportError(
        "FastMCP is required for MCP server functionality. "
        "Install with: pip install bodyspecy[mcp] or pip install fastmcp"
    )

from .config import MCPConfig


class SQLiteConnection:
    """Secure SQLite connection context manager for read-only access."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = None

    def __enter__(self):
        """Open read-only SQLite connection."""
        self.conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        self.conn.row_factory = sqlite3.Row
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close connection safely."""
        if self.conn:
            self.conn.close()


class QueryValidator:
    """SQL query validation and sanitization for read-only access."""

    ALLOWED_STATEMENTS = ("select", "with")
    FORBIDDEN_KEYWORDS = {
        "insert",
        "update",
        "delete",
        "drop",
        "create",
        "alter",
        "pragma",
        "attach",
        "detach",
        "vacuum",
        "analyze",
    }

    @classmethod
    def validate_query(cls, query: str) -> None:
        """Validate SQL query for read-only access."""
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")

        query_lower = query.lower().strip()

        if not any(query_lower.startswith(prefix) for prefix in cls.ALLOWED_STATEMENTS):
            allowed = ", ".join(cls.ALLOWED_STATEMENTS).upper()
            raise ValueError(f"Only {allowed} queries are allowed for security")

        query_words = set(re.findall(r"\b\w+\b", query_lower))
        forbidden_found = query_words.intersection(cls.FORBIDDEN_KEYWORDS)
        if forbidden_found:
            raise ValueError(f"Forbidden keywords found: {', '.join(forbidden_found)}")

        if cls._contains_multiple_statements(query):
            raise ValueError("Multiple statements not allowed")

    @staticmethod
    def _contains_multiple_statements(sql: str) -> bool:
        """Check if SQL contains multiple statements."""
        in_single_quote = False
        in_double_quote = False

        for char in sql:
            if char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
            elif char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
            elif char == ";" and not in_single_quote and not in_double_quote:
                return True

        return False

    @staticmethod
    def add_row_limit(query: str, limit: int = 1000) -> str:
        """Add LIMIT clause if not present."""
        query_lower = query.lower()
        if "limit" not in query_lower:
            return f"{query.rstrip(';')} LIMIT {limit}"
        return query


class DatabaseManager:
    """Manages database connections and basic operations."""

    def __init__(self, config: MCPConfig):
        self.config = config
        self.validator = QueryValidator()
        self.logger = logging.getLogger("bodyspecy.mcp.database")

        if config.enable_query_logging and not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
                )
            )
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

    def get_connection(self):
        """Get read-only database connection."""
        return SQLiteConnection(self.config.db_path)

    def execute_safe_query(
        self, query: str, params: Optional[List[Any]] = None
    ) -> List[Dict[str, Any]]:
        """Execute validated query with safety checks."""
        if self.config.strict_validation:
            self.validator.validate_query(query)

        original_query = query
        query = self.validator.add_row_limit(query, self.config.max_rows)

        if self.config.enable_query_logging:
            self.logger.info(f"Executing query: {query}")
            if params:
                self.logger.info(f"Parameters: {params}")

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params or [])
                results = [dict(row) for row in cursor.fetchall()]

                if self.config.enable_query_logging:
                    self.logger.info(f"Query returned {len(results)} rows")

                return results
        except sqlite3.Error as e:
            if self.config.enable_query_logging:
                self.logger.error(f"Query failed: {str(e)}")
            raise ValueError(f"Database error: {str(e)}")


def create_mcp_server(config: MCPConfig) -> FastMCP:
    """Create and configure the BodySpec DEXA MCP server.

    Args:
        config: MCP configuration with database path and settings.
    """
    config.validate()

    db_manager = DatabaseManager(config)

    mcp = FastMCP("BodySpec DEXA Data Explorer")

    @mcp.tool()
    def explore_database_structure() -> Dict[str, Any]:
        """WHEN TO USE: When you need to understand what DEXA scan data is available.

        This is your starting point for exploring BodySpec DEXA data. Use this tool
        first to see what tables are available, how many scans exist, and the date
        range of data before running specific queries or using other tools.

        Returns:
            Database structure with tables, row counts, and date ranges
        """
        try:
            tables_query = """
                SELECT name FROM sqlite_master
                WHERE type='table'
                ORDER BY name
            """
            tables = db_manager.execute_safe_query(tables_query)
            table_names = [row["name"] for row in tables]

            table_info = {}
            for table_name in table_names:
                count_query = f"SELECT COUNT(*) as count FROM {table_name}"
                count_result = db_manager.execute_safe_query(count_query)

                info = {
                    "row_count": count_result[0]["count"],
                    "description": _get_table_description(table_name),
                }

                # Add date range for tables with scan_date
                if table_name in ("scans", "scan_regions", "scan_bone_density"):
                    date_query = f"SELECT MIN(scan_date) as earliest, MAX(scan_date) as latest FROM {table_name}"
                    date_result = db_manager.execute_safe_query(date_query)
                    if date_result and date_result[0]["earliest"]:
                        info["date_range"] = {
                            "earliest": date_result[0]["earliest"],
                            "latest": date_result[0]["latest"],
                        }

                table_info[table_name] = info

            return {
                "available_tables": table_info,
                "usage_tip": "Use 'get_scan_summary' for a quick overview, 'get_table_details' to see column structure, or 'execute_sql_query' for custom queries",
            }
        except Exception as e:
            raise ValueError(f"Failed to explore database: {str(e)}")

    @mcp.tool()
    def get_table_details(table_name: str) -> Dict[str, Any]:
        """WHEN TO USE: When you need to see the structure and sample data of a specific table.

        Use this after 'explore_database_structure' when you want to understand what
        columns are available in a table and see examples of the actual data. Useful
        for crafting custom SQL queries.

        Args:
            table_name: Name of the table (scans, scan_regions, or scan_bone_density)

        Returns:
            Table structure with columns, data types, and sample records
        """
        if not table_name or not table_name.strip():
            raise ValueError("Table name cannot be empty")

        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table_name):
            raise ValueError("Invalid table name format")

        try:
            check_query = """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name=?
            """
            check_result = db_manager.execute_safe_query(check_query, [table_name])

            if not check_result:
                available_tables = db_manager.execute_safe_query(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                table_list = [row["name"] for row in available_tables]
                raise ValueError(
                    f"Table '{table_name}' does not exist. Available tables: {', '.join(table_list)}"
                )

            # Get table schema using PRAGMA
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = cursor.fetchall()

            column_info = [
                {
                    "name": col[1],
                    "type": col[2],
                    "required": bool(col[3]),
                    "is_primary_key": bool(col[5]),
                }
                for col in columns
            ]

            sample_query = f"SELECT * FROM {table_name} ORDER BY rowid DESC LIMIT 3"
            sample_data = db_manager.execute_safe_query(sample_query)

            return {
                "table_name": table_name,
                "columns": column_info,
                "sample_data": sample_data,
                "description": _get_table_description(table_name),
                "usage_tip": f"Use 'execute_sql_query' with SELECT statements to query {table_name}",
            }

        except Exception as e:
            raise ValueError(f"Failed to get table details: {str(e)}")

    @mcp.tool()
    def execute_sql_query(
        query: str, params: Optional[List[Any]] = None
    ) -> List[Dict[str, Any]]:
        """WHEN TO USE: When you need to run custom SQL queries against the DEXA scan database.

        This is the main tool for custom data analysis. Use it to run SELECT queries
        to analyze body composition, bone density, trends, or find patterns across scans.

        IMPORTANT: Only SELECT and WITH queries are allowed for security. All data is
        stored in metric units (kg, cm, g/cm2).

        Column names and `region` values are non-obvious — call
        get_table_details(table_name) to confirm columns and enumerate region
        values before filtering; do NOT guess. A wrong region returns 0 rows,
        not an error.

        Args:
            query: SQL SELECT query to execute
            params: Optional list of parameters for ? placeholders in query

        Example queries:
        - All scans overview: "SELECT scan_date, total_body_fat_pct, total_mass_kg, lean_mass_kg FROM scans ORDER BY scan_date"
        - Fat distribution: "SELECT scan_date, region, fat_pct FROM scan_regions WHERE region IN ('arms', 'legs', 'trunk') ORDER BY scan_date, region"
        - Bone density: "SELECT scan_date, region, bmd_g_cm2 FROM scan_bone_density ORDER BY scan_date, region"
        - Left vs right: "SELECT scan_date, region, lean_mass_kg FROM scan_regions WHERE region LIKE '%arm%' OR region LIKE '%leg%' ORDER BY scan_date"

        Returns:
            List of matching records as dictionaries
        """
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")

        try:
            return db_manager.execute_safe_query(query, params)
        except Exception as e:
            raise ValueError(f"Query execution failed: {str(e)}")

    @mcp.tool()
    def get_scan_summary() -> Dict[str, Any]:
        """WHEN TO USE: When you want a quick overview of all DEXA scan data without writing SQL.

        This is the best starting tool for understanding someone's body composition
        history. Provides total scan count, date range, latest scan metrics, and
        change from first to latest scan.

        Returns:
            Summary with total scans, date range, latest metrics, and trends
        """
        try:
            # Basic scan info
            overview_query = """
                SELECT
                    COUNT(*) as total_scans,
                    MIN(scan_date) as first_scan,
                    MAX(scan_date) as latest_scan
                FROM scans
            """
            overview = db_manager.execute_safe_query(overview_query)
            if not overview or overview[0]["total_scans"] == 0:
                return {"total_scans": 0, "message": "No scans in database"}

            info = overview[0]

            # Latest scan details
            latest_query = """
                SELECT
                    scan_date, total_body_fat_pct, total_mass_kg, fat_mass_kg,
                    lean_mass_kg, bone_mineral_content_kg, rmr_kcal,
                    android_fat_pct, gynoid_fat_pct, ag_ratio,
                    vat_mass_kg, vat_volume_cm3,
                    total_bmd_g_cm2, total_t_score, total_z_score
                FROM scans
                ORDER BY scan_date DESC
                LIMIT 1
            """
            latest = db_manager.execute_safe_query(latest_query)[0]

            result = {
                "total_scans": info["total_scans"],
                "date_range": {
                    "first": info["first_scan"],
                    "latest": info["latest_scan"],
                },
                "latest_scan": latest,
            }

            # Trend: change from first to latest
            if info["total_scans"] > 1:
                first_query = """
                    SELECT
                        scan_date, total_body_fat_pct, total_mass_kg,
                        fat_mass_kg, lean_mass_kg, total_bmd_g_cm2
                    FROM scans
                    ORDER BY scan_date ASC
                    LIMIT 1
                """
                first = db_manager.execute_safe_query(first_query)[0]

                result["trend_first_to_latest"] = {
                    "body_fat_pct_change": round(
                        latest["total_body_fat_pct"] - first["total_body_fat_pct"], 1
                    ),
                    "total_mass_kg_change": round(
                        latest["total_mass_kg"] - first["total_mass_kg"], 2
                    ),
                    "fat_mass_kg_change": round(
                        latest["fat_mass_kg"] - first["fat_mass_kg"], 2
                    ),
                    "lean_mass_kg_change": round(
                        latest["lean_mass_kg"] - first["lean_mass_kg"], 2
                    ),
                    "bmd_change": round(
                        (latest["total_bmd_g_cm2"] or 0) - (first["total_bmd_g_cm2"] or 0), 3
                    ),
                }

            return result

        except Exception as e:
            raise ValueError(f"Failed to generate scan summary: {str(e)}")

    @mcp.tool()
    def get_body_composition_trends() -> Dict[str, Any]:
        """WHEN TO USE: When you need time-series body composition data across all scans.

        Returns every scan's key metrics as a time series, ideal for charting progress
        or analyzing trends in body fat, lean mass, weight, metabolic rate, and visceral
        fat over time.

        Returns:
            Time-series data with scan_date, body_fat_pct, fat_mass_kg, lean_mass_kg,
            total_mass_kg, rmr_kcal, ag_ratio, vat_mass_kg for each scan
        """
        try:
            query = """
                SELECT
                    scan_date,
                    total_body_fat_pct as body_fat_pct,
                    fat_mass_kg,
                    lean_mass_kg,
                    total_mass_kg,
                    rmr_kcal,
                    ag_ratio,
                    vat_mass_kg
                FROM scans
                ORDER BY scan_date ASC
            """
            scans = db_manager.execute_safe_query(query)

            return {
                "scan_count": len(scans),
                "scans": scans,
                "units": {
                    "body_fat_pct": "percentage",
                    "fat_mass_kg": "kilograms",
                    "lean_mass_kg": "kilograms",
                    "total_mass_kg": "kilograms",
                    "rmr_kcal": "kcal/day",
                    "ag_ratio": "ratio (android/gynoid)",
                    "vat_mass_kg": "kilograms",
                },
            }

        except Exception as e:
            raise ValueError(f"Failed to get body composition trends: {str(e)}")

    @mcp.tool()
    def get_regional_comparison(region: Optional[str] = None) -> Dict[str, Any]:
        """WHEN TO USE: When you need body composition broken down by body region.

        Two modes:
        - No region specified: Returns the latest scan's breakdown across ALL regions
          (arms, legs, trunk, android, gynoid, total, plus left/right limbs).
        - Region specified: Returns that region's trends across ALL scans over time.

        Valid regions: arms, legs, trunk, android, gynoid, total, right_arm, left_arm,
        right_leg, left_leg.

        Args:
            region: Optional specific region to get trends for. If None, returns
                    latest scan's all-region breakdown.

        Returns:
            Regional body composition data (fat%, mass, lean mass by region)
        """
        try:
            if region:
                region = region.lower().strip()
                valid_regions = {
                    "arms", "legs", "trunk", "android", "gynoid", "total",
                    "right_arm", "left_arm", "right_leg", "left_leg",
                }
                if region not in valid_regions:
                    raise ValueError(
                        f"Invalid region '{region}'. Valid: {', '.join(sorted(valid_regions))}"
                    )

                query = """
                    SELECT
                        scan_date, region, fat_pct, total_mass_kg,
                        fat_mass_kg, lean_mass_kg, bone_mineral_content_kg
                    FROM scan_regions
                    WHERE region = ?
                    ORDER BY scan_date ASC
                """
                rows = db_manager.execute_safe_query(query, [region])

                return {
                    "region": region,
                    "scan_count": len(rows),
                    "trends": rows,
                }

            else:
                # Latest scan, all regions
                latest_date_query = "SELECT MAX(scan_date) as latest FROM scan_regions"
                latest_date = db_manager.execute_safe_query(latest_date_query)[0]["latest"]

                if not latest_date:
                    return {"message": "No regional data available"}

                query = """
                    SELECT
                        region, fat_pct, total_mass_kg,
                        fat_mass_kg, lean_mass_kg, bone_mineral_content_kg
                    FROM scan_regions
                    WHERE scan_date = ?
                    ORDER BY region
                """
                rows = db_manager.execute_safe_query(query, [latest_date])

                return {
                    "scan_date": latest_date,
                    "regions": rows,
                    "usage_tip": "Call with region parameter (e.g., 'arms', 'trunk') to see that region's trends over time",
                }

        except Exception as e:
            raise ValueError(f"Failed to get regional comparison: {str(e)}")

    @mcp.tool()
    def get_bone_density_summary() -> Dict[str, Any]:
        """WHEN TO USE: When you need bone mineral density (BMD) data and interpretation.

        Returns BMD by anatomical region across all scans, plus T-score and Z-score
        interpretation using WHO thresholds. Useful for tracking bone health over time.

        WHO T-score interpretation:
        - >= -1.0: Normal bone density
        - -2.5 to -1.0: Osteopenia (low bone mass)
        - <= -2.5: Osteoporosis

        Returns:
            BMD by region across scans, T/Z scores, and WHO classification
        """
        try:
            # All bone density data across scans
            query = """
                SELECT
                    scan_date, region, bmd_g_cm2, t_score, z_score
                FROM scan_bone_density
                ORDER BY scan_date ASC, region
            """
            all_rows = db_manager.execute_safe_query(query)

            # Organize by scan date
            scans_by_date = {}
            for row in all_rows:
                d = row["scan_date"]
                if d not in scans_by_date:
                    scans_by_date[d] = []
                scans_by_date[d].append(row)

            # Latest total BMD with T/Z scores
            latest_total_query = """
                SELECT
                    s.scan_date, s.total_bmd_g_cm2, s.total_t_score, s.total_z_score
                FROM scans s
                ORDER BY s.scan_date DESC
                LIMIT 1
            """
            latest_total = db_manager.execute_safe_query(latest_total_query)

            interpretation = None
            if latest_total and latest_total[0]["total_t_score"] is not None:
                t = latest_total[0]["total_t_score"]
                if t >= -1.0:
                    classification = "Normal"
                    detail = "Bone density is within the normal range."
                elif t > -2.5:
                    classification = "Osteopenia"
                    detail = "Low bone mass. Consider discussing with your doctor."
                else:
                    classification = "Osteoporosis"
                    detail = "Significantly low bone density. Medical consultation recommended."

                interpretation = {
                    "t_score": t,
                    "z_score": latest_total[0]["total_z_score"],
                    "classification": classification,
                    "detail": detail,
                    "reference": "WHO T-score thresholds: >= -1.0 normal, -2.5 to -1.0 osteopenia, <= -2.5 osteoporosis",
                }

            # BMD trends for total region across scans
            total_trend_query = """
                SELECT scan_date, bmd_g_cm2
                FROM scan_bone_density
                WHERE region = 'total'
                ORDER BY scan_date ASC
            """
            total_trends = db_manager.execute_safe_query(total_trend_query)

            return {
                "scans_by_date": scans_by_date,
                "total_bmd_trend": total_trends,
                "latest_interpretation": interpretation,
                "units": {
                    "bmd_g_cm2": "grams per square centimeter",
                    "t_score": "standard deviations from young adult mean",
                    "z_score": "standard deviations from age-matched mean",
                },
            }

        except Exception as e:
            raise ValueError(f"Failed to get bone density summary: {str(e)}")

    @mcp.resource("file://bodyspec_data_guide")
    def bodyspec_data_guide() -> str:
        """Complete guide to understanding and querying BodySpec DEXA scan data.

        This resource provides all the information needed to understand the available
        DEXA data and how to query it effectively.
        """
        return _get_data_guide()

    return mcp


def _get_table_description(table_name: str) -> str:
    """Get human-readable description for table."""
    descriptions = {
        "scans": "Primary scan data — one row per DEXA scan with body composition totals, metabolic rate, VAT, and bone density summary",
        "scan_regions": "Body composition by region (arms, legs, trunk, android, gynoid, total, plus left/right limbs)",
        "scan_bone_density": "Bone mineral density by anatomical region (head, arms, legs, trunk, ribs, spine, pelvis, total) with T/Z scores",
    }
    return descriptions.get(table_name, "Data table")


def _get_data_guide() -> str:
    """Get comprehensive guide for DEXA scan data analysis."""
    return """
# BodySpec DEXA Scan Data Guide

## Quick Start
1. Use `get_scan_summary` for a quick overview of all scans
2. Use `get_body_composition_trends` for time-series data
3. Use `get_regional_comparison` for body region breakdowns
4. Use `get_bone_density_summary` for bone health data
5. Use `execute_sql_query` for custom analysis

## Database Tables

### scans (Primary table — one row per DEXA scan)
- `scan_date` (DATE PK): Scan date, e.g. 2026-01-23
- `client_name` (TEXT): Client name
- `sex` (TEXT): "Male" or "Female"
- `birth_date` (DATE): Date of birth
- `total_body_fat_pct` (REAL): Total body fat percentage, e.g. 30.9
- `total_mass_kg` (REAL): Total body mass in kg (DEXA-measured)
- `fat_mass_kg` (REAL): Total fat tissue in kg
- `lean_mass_kg` (REAL): Total lean tissue in kg
- `bone_mineral_content_kg` (REAL): Total BMC in kg
- `rmr_kcal` (REAL): Resting Metabolic Rate in kcal/day (Katch-McArdle formula)
- `android_fat_pct` (REAL): Android region (lower abdomen) fat percentage
- `gynoid_fat_pct` (REAL): Gynoid region (hips/thighs) fat percentage
- `ag_ratio` (REAL): Android/Gynoid fat ratio. < 1.0 is healthier.
- `vat_mass_kg` (REAL): Visceral Adipose Tissue mass in kg
- `vat_volume_cm3` (REAL): Visceral Adipose Tissue volume in cm³
- `total_bmd_g_cm2` (REAL): Total bone mineral density in g/cm²
- `total_t_score` (REAL): T-score (comparison to young adult mean)
- `total_z_score` (REAL): Z-score (comparison to age-matched mean)
- `pdf_path` (TEXT): Path to source PDF report
- `imported_at` (DATETIME): When record was imported

### scan_regions (Body composition by region)
- `scan_date` (DATE PK/FK): References scans.scan_date
- `region` (TEXT PK): Region name (see below)
- `fat_pct` (REAL): Region fat percentage
- `total_mass_kg` (REAL): Region total mass in kg
- `fat_mass_kg` (REAL): Region fat mass in kg
- `lean_mass_kg` (REAL): Region lean mass in kg
- `bone_mineral_content_kg` (REAL): Region BMC in kg

**Regions**: arms, legs, trunk, android, gynoid, total (aggregate), right_arm, left_arm, right_leg, left_leg (individual limbs)

### scan_bone_density (BMD by bone region)
- `scan_date` (DATE PK/FK): References scans.scan_date
- `region` (TEXT PK): Bone region name
- `bmd_g_cm2` (REAL): Bone mineral density in g/cm²
- `t_score` (REAL): T-score (only Total region has a value)
- `z_score` (REAL): Z-score (only Total region has a value)

**Regions**: head, arms, legs, trunk, ribs, spine, pelvis, total

## Units — ALL METRIC
- Mass/weight: kilograms (kg)
- Height: centimeters (cm)
- Volume: cubic centimeters (cm³)
- Bone density: grams per square centimeter (g/cm²)
- Percentages: stored as plain numbers (30.9 = 30.9%)
- Energy: kcal/day

## DEXA Terminology
- **BMD** (Bone Mineral Density): Measured in g/cm². Higher is denser/stronger.
- **T-score**: How your BMD compares to a healthy 30-year-old. Used for diagnosis.
- **Z-score**: How your BMD compares to others your age. Used for context.
- **Android fat**: Fat in the lower abdominal region (visceral risk area).
- **Gynoid fat**: Fat in the hips, upper thighs, and buttocks.
- **A/G Ratio**: Android fat % / Gynoid fat %. < 1.0 indicates healthier fat distribution.
- **VAT** (Visceral Adipose Tissue): Internal organ fat. Higher values = higher metabolic risk.
- **RMR** (Resting Metabolic Rate): Calories burned at rest per day (Katch-McArdle formula).
- **BMC** (Bone Mineral Content): Total bone mineral mass in the region.
- **Lean mass**: Everything that isn't fat or bone (muscle, organs, water).

## WHO T-score Thresholds
- **>= -1.0**: Normal bone density
- **-2.5 to -1.0**: Osteopenia (low bone mass)
- **<= -2.5**: Osteoporosis

## Common Query Patterns

### Track body fat over time
```sql
SELECT scan_date, total_body_fat_pct, fat_mass_kg, lean_mass_kg
FROM scans ORDER BY scan_date
```

### Compare regions at latest scan
```sql
SELECT region, fat_pct, lean_mass_kg, fat_mass_kg
FROM scan_regions
WHERE scan_date = (SELECT MAX(scan_date) FROM scans)
ORDER BY region
```

### Left vs right muscle balance
```sql
SELECT scan_date, region, lean_mass_kg
FROM scan_regions
WHERE region IN ('right_arm', 'left_arm', 'right_leg', 'left_leg')
ORDER BY scan_date, region
```

### Bone density trends
```sql
SELECT scan_date, region, bmd_g_cm2
FROM scan_bone_density
WHERE region = 'total'
ORDER BY scan_date
```

### Visceral fat and metabolic trends
```sql
SELECT scan_date, vat_mass_kg, vat_volume_cm3, rmr_kcal, ag_ratio
FROM scans ORDER BY scan_date
```

### Regional fat distribution changes
```sql
SELECT scan_date, region, fat_pct
FROM scan_regions
WHERE region IN ('arms', 'legs', 'trunk', 'android', 'gynoid')
ORDER BY scan_date, region
```
""".strip()
