"""API verification tests — spot-check local DB against BodySpec public API.

Requires:
  - BODYSPEC_OAUTH_TOKEN env var (OAuth2 access token from BodySpec website)
  - Production database at ~/.bodyspecy/bodyspec.db
  - Network access to https://app.bodyspec.com

Run:
  BODYSPEC_OAUTH_TOKEN="<token>" pytest -m api -v
"""

import os
import sqlite3
from pathlib import Path

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required: pip install bodyspecy[api-test]")

BODYSPEC_BASE_URL = "https://app.bodyspec.com"
DEFAULT_DB_PATH = Path.home() / ".bodyspecy" / "bodyspec.db"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def api_token():
    """Read OAuth2 token from env or file; skip if absent."""
    token = os.environ.get("BODYSPEC_OAUTH_TOKEN")
    if not token:
        token_file = Path(__file__).parent / "personal_data" / "OAUTH_TOKEN"
        if token_file.exists():
            token = token_file.read_text().strip()
    if not token:
        pytest.skip("BODYSPEC_OAUTH_TOKEN not set and no tests/personal_data/OAUTH_TOKEN file")
    return token


@pytest.fixture(scope="session")
def api_client(api_token):
    """httpx client with base URL and auth header."""
    client = httpx.Client(
        base_url=BODYSPEC_BASE_URL,
        headers={"Authorization": f"Bearer {api_token}"},
        timeout=30.0,
    )
    yield client
    client.close()


@pytest.fixture(scope="session")
def local_db():
    """Read-only connection to the production SQLite DB."""
    db_path = Path(
        os.environ.get("BODYSPECY_DB_PATH", str(DEFAULT_DB_PATH))
    )
    if not db_path.exists():
        pytest.skip(f"Database not found at {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def api_results(api_client):
    """Fetch all DEXA results from the API, paginated."""
    results = []
    url = "/api/v1/users/me/results/"
    while url:
        resp = api_client.get(url)
        resp.raise_for_status()
        data = resp.json()
        items = data if isinstance(data, list) else data.get("results", data.get("items", []))
        results.extend(items)
        # Handle pagination
        url = data.get("next") if isinstance(data, dict) else None
    # Sort by start_time
    results.sort(key=lambda r: r.get("start_time", ""))
    return results


@pytest.fixture(scope="session")
def local_scan_dates(local_db):
    """All scan dates in the local DB."""
    cursor = local_db.execute("SELECT scan_date FROM scans ORDER BY scan_date")
    return [row["scan_date"] for row in cursor.fetchall()]


@pytest.fixture(scope="session")
def matched_scans(api_results, local_scan_dates):
    """Join API results to local DB scans by date.

    Yields list of (api_result_id, scan_date) tuples.
    """
    # Build set of local dates (stored as YYYY-MM-DD strings in SQLite)
    local_dates = set(local_scan_dates)

    matches = []
    for result in api_results:
        # API start_time is an ISO datetime; extract date portion
        start_time = result.get("start_time", "")
        api_date = start_time[:10]  # YYYY-MM-DD
        if api_date in local_dates:
            matches.append((result["result_id"], api_date))

    if not matches:
        pytest.skip("No matching scans between API and local DB")
    return matches


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_api_composition(api_client, result_id):
    """Fetch composition data for a single result."""
    resp = api_client.get(f"/api/v1/users/me/results/{result_id}/dexa/composition")
    resp.raise_for_status()
    return resp.json()


def _get_api_bone_density(api_client, result_id):
    """Fetch bone density data for a single result."""
    resp = api_client.get(f"/api/v1/users/me/results/{result_id}/dexa/bone-density")
    resp.raise_for_status()
    return resp.json()


def _get_api_visceral_fat(api_client, result_id):
    """Fetch visceral fat data for a single result. Returns None if not available."""
    resp = api_client.get(f"/api/v1/users/me/results/{result_id}/dexa/visceral-fat")
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def _get_api_scan_info(api_client, result_id):
    """Fetch scan info for a single result."""
    resp = api_client.get(f"/api/v1/users/me/results/{result_id}/dexa/scan-info")
    resp.raise_for_status()
    return resp.json()


def _get_local_scan(local_db, scan_date):
    """Fetch a scan row from the local DB by date."""
    cursor = local_db.execute(
        "SELECT * FROM scans WHERE scan_date = ?", (scan_date,)
    )
    return cursor.fetchone()


def _get_local_regions(local_db, scan_date):
    """Fetch region rows from local DB for a scan date."""
    cursor = local_db.execute(
        "SELECT * FROM scan_regions WHERE scan_date = ?", (scan_date,)
    )
    return {row["region"]: row for row in cursor.fetchall()}


def _get_local_bone_density(local_db, scan_date):
    """Fetch bone density rows from local DB for a scan date."""
    cursor = local_db.execute(
        "SELECT * FROM scan_bone_density WHERE scan_date = ?", (scan_date,)
    )
    return {row["region"]: row for row in cursor.fetchall()}


def _get_api_region(data, name):
    """Get a region dict from an API response.

    API returns {"total": {...}, "regions": {"left_arm": {...}, ...}}.
    """
    if name == "total":
        return data.get("total")
    regions = data.get("regions", {})
    return regions.get(name)


def _assert_approx(api_val, db_val, field, scan_date, tolerance):
    """Assert two values are approximately equal with an informative message."""
    assert abs(api_val - db_val) <= tolerance, (
        f"[{scan_date}] {field}: API={api_val}, DB={db_val}, "
        f"diff={abs(api_val - db_val):.4f}, tolerance={tolerance}"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.api
class TestScanCount:
    def test_scan_count_matches(self, api_results, local_scan_dates):
        """Compare total number of DEXA scans between API and local DB."""
        api_count = len(api_results)
        local_count = len(local_scan_dates)

        if api_count != local_count:
            api_dates = {r.get("start_time", "")[:10] for r in api_results}
            local_dates_set = set(local_scan_dates)
            only_api = api_dates - local_dates_set
            only_local = local_dates_set - api_dates
            msg = (
                f"Scan count mismatch: API={api_count}, Local={local_count}. "
                f"Only in API: {sorted(only_api)}. "
                f"Only in Local: {sorted(only_local)}."
            )
            assert api_count == local_count, msg
        else:
            assert api_count == local_count


@pytest.mark.api
class TestCompositionTotal:
    @pytest.fixture(params="matched_scans")
    def scan_pair(self, request, matched_scans):
        idx = request.param
        return matched_scans[idx]

    def test_composition_total(self, api_client, local_db, matched_scans):
        """Compare top-level body composition for each matched scan."""
        for result_id, scan_date in matched_scans:
            comp = _get_api_composition(api_client, result_id)
            local = _get_local_scan(local_db, scan_date)

            total = _get_api_region(comp, "total")
            assert total is not None, f"[{scan_date}] No 'total' in API composition"

            fields = [
                ("fat_mass_kg", "fat_mass_kg", 0.5),
                ("lean_mass_kg", "lean_mass_kg", 0.5),
                ("bone_mass_kg", "bone_mineral_content_kg", 0.2),
                ("region_fat_pct", "total_body_fat_pct", 0.5),
            ]
            mismatches = []
            for api_field, db_field, tol in fields:
                api_val = total.get(api_field)
                db_val = local[db_field]
                if api_val is not None and db_val is not None:
                    diff = abs(api_val - db_val)
                    if diff > tol:
                        mismatches.append(
                            f"  {api_field}: API={api_val}, DB={db_val}, "
                            f"diff={diff:.4f}, tol={tol}"
                        )

            api_ag = comp.get("android_gynoid_ratio")
            if api_ag is not None and local["ag_ratio"] is not None:
                diff = abs(api_ag - local["ag_ratio"])
                if diff > 0.05:
                    mismatches.append(
                        f"  android_gynoid_ratio: API={api_ag}, DB={local['ag_ratio']}, "
                        f"diff={diff:.4f}, tol=0.05"
                    )

            assert not mismatches, (
                f"[{scan_date}] Composition total mismatches:\n"
                + "\n".join(mismatches)
            )


@pytest.mark.api
class TestCompositionRegions:
    def test_composition_regions(self, api_client, local_db, matched_scans):
        """Compare per-region body composition for each matched scan."""
        check_regions = [
            "left_arm", "right_arm", "left_leg", "right_leg",
            "trunk", "android", "gynoid",
        ]
        for result_id, scan_date in matched_scans:
            comp = _get_api_composition(api_client, result_id)
            local_regions = _get_local_regions(local_db, scan_date)

            mismatches = []
            for region_name in check_regions:
                api_region = _get_api_region(comp, region_name)
                local_region = local_regions.get(region_name)

                if api_region is None or local_region is None:
                    continue

                fields = [
                    ("fat_mass_kg", "fat_mass_kg", 0.5),
                    ("lean_mass_kg", "lean_mass_kg", 0.5),
                    ("bone_mass_kg", "bone_mineral_content_kg", 0.1),
                ]
                for api_field, db_field, tol in fields:
                    api_val = api_region.get(api_field)
                    db_val = local_region[db_field]
                    if api_val is not None and db_val is not None:
                        diff = abs(api_val - db_val)
                        if diff > tol:
                            mismatches.append(
                                f"  {region_name}.{api_field}: API={api_val}, "
                                f"DB={db_val:.4f}, diff={diff:.4f}, tol={tol}"
                            )

            assert not mismatches, (
                f"[{scan_date}] Regional composition mismatches:\n"
                + "\n".join(mismatches)
            )


@pytest.mark.api
class TestBoneDensity:
    def test_bone_density(self, api_client, local_db, matched_scans):
        """Compare bone density data for each matched scan."""
        for result_id, scan_date in matched_scans:
            api_data = _get_api_bone_density(api_client, result_id)
            local_bones = _get_local_bone_density(local_db, scan_date)

            mismatches = []

            # Check per-region BMD
            api_regions = api_data.get("regions", {})
            for region_name, api_region in api_regions.items():
                local_bone = local_bones.get(region_name)
                if local_bone is None:
                    continue

                api_bmd = api_region.get("bone_mineral_density")
                if api_bmd is not None and local_bone["bmd_g_cm2"] is not None:
                    diff = abs(api_bmd - local_bone["bmd_g_cm2"])
                    if diff > 0.1:
                        mismatches.append(
                            f"  {region_name}.bmd: API={api_bmd}, "
                            f"DB={local_bone['bmd_g_cm2']}, diff={diff:.4f}, tol=0.1"
                        )

            # Check total BMD
            api_total = _get_api_region(api_data, "total")
            if api_total is not None:
                local_bone_total = local_bones.get("total")
                if local_bone_total is not None:
                    api_bmd = api_total.get("bone_mineral_density")
                    if api_bmd is not None and local_bone_total["bmd_g_cm2"] is not None:
                        diff = abs(api_bmd - local_bone_total["bmd_g_cm2"])
                        if diff > 0.01:
                            mismatches.append(
                                f"  total.bmd: API={api_bmd}, "
                                f"DB={local_bone_total['bmd_g_cm2']}, diff={diff:.4f}, tol=0.01"
                            )

            assert not mismatches, (
                f"[{scan_date}] Bone density mismatches:\n"
                + "\n".join(mismatches)
            )


@pytest.mark.api
class TestVisceralFat:
    def test_visceral_fat(self, api_client, local_db, matched_scans):
        """Compare visceral fat data for each matched scan."""
        any_available = False
        for result_id, scan_date in matched_scans:
            api_data = _get_api_visceral_fat(api_client, result_id)
            if api_data is None:
                continue
            any_available = True
            local = _get_local_scan(local_db, scan_date)

            api_mass = api_data.get("vat_mass_kg")
            if api_mass is not None and local["vat_mass_kg"] is not None:
                _assert_approx(
                    api_mass, local["vat_mass_kg"],
                    "vat_mass_kg", scan_date, 0.01,
                )

            api_vol = api_data.get("vat_volume_cm3")
            if api_vol is not None and local["vat_volume_cm3"] is not None:
                _assert_approx(
                    api_vol, local["vat_volume_cm3"],
                    "vat_volume_cm3", scan_date, 0.5,
                )
        if not any_available:
            pytest.skip("Visceral fat endpoint not available in API")


@pytest.mark.api
class TestScanInfo:
    def test_scan_info(self, api_client, local_db, matched_scans):
        """Compare patient intake data for each matched scan."""
        for result_id, scan_date in matched_scans:
            api_data = _get_api_scan_info(api_client, result_id)
            local = _get_local_scan(local_db, scan_date)

            # Patient intake may be nested
            intake = api_data.get("patient_intake", api_data)

            api_height = intake.get("height_cm") or intake.get("height")
            if api_height is not None and local["height_cm"] is not None:
                _assert_approx(
                    api_height, local["height_cm"],
                    "height_cm", scan_date, 0.5,
                )

            api_weight = intake.get("weight_kg") or intake.get("weight")
            if api_weight is not None and local["weight_kg"] is not None:
                _assert_approx(
                    api_weight, local["weight_kg"],
                    "weight_kg", scan_date, 0.5,
                )
