# Validation Test Plan

Tests that require personal data or network access — excluded from default
`pytest` runs and from git.

---

## Part 1 — API Verification

Spot-check local bodyspecy MCP/DB data against the BodySpec public API to catch
parsing or import drift.

### BodySpec API Reference

- **Base URL**: `https://app.bodyspec.com`
- **Docs**: `https://app.bodyspec.com/docs` (OpenAPI 3.1)
- **Auth**: Bearer JWT token via `Authorization: Bearer <token>`

#### Relevant Endpoints

| Endpoint | Returns |
|---|---|
| `GET /api/v1/users/me/results/` | Paginated list: `result_id`, `start_time`, `location`, `service` |
| `GET /api/v1/users/me/results/{id}/dexa/composition` | Per-region: `fat_mass_kg`, `lean_mass_kg`, `bone_mass_kg`, `tissue_fat_pct`, `region_fat_pct`; plus `android_gynoid_ratio` |
| `GET /api/v1/users/me/results/{id}/dexa/bone-density` | Per-region: `bone_mineral_density`, `bone_mineral_content_g`, `bone_area_cm2`, T/Z scores |
| `GET /api/v1/users/me/results/{id}/dexa/visceral-fat` | `vat_mass_kg`, `vat_volume_cm3` |
| `GET /api/v1/users/me/results/{id}/dexa/scan-info` | `acquire_time`, `analyze_time`, `patient_intake` (height, weight, etc.) |

### Authentication

- Env var: `BODYSPEC_OAUTH_TOKEN` — an OAuth2 access token from the BodySpec website.
- Tests skip with a clear message if the token is missing.
- Token retrieval is via OAuth2 PKCE flow (client ID: `bodyspec-api-ext-v1`,
  auth server: `auth.bodyspec.com`). For testing, copy a valid OAuth2 token
  from the website or browser dev tools.

### Test File

`tests/test_api_verify.py`

#### Fixtures

1. **`api_token`** — reads `BODYSPEC_ACCESS_TOKEN` from env; `pytest.skip()` if absent.
2. **`api_client`** — thin wrapper around `httpx` (or `requests`) that sets
   base URL + auth header. Constructed from `api_token`.
3. **`local_db`** — opens the production SQLite DB at `~/.bodyspecy/bodyspec.db`
   (read-only); `pytest.skip()` if file missing.
4. **`api_results`** — fetches all results from the API (paginating if needed),
   returns list sorted by date.
5. **`matched_scans`** — joins API results to local DB scans by date
   (`start_time` date portion == `scan_date`). Yields list of
   `(api_result_id, scan_date)` tuples. Skips if no matches found.

#### Test Cases

##### 1. `test_scan_count_matches`
Compare total number of DEXA scans between API and local DB.
- Fetch all results from API (paginate through all pages).
- Count rows in local `scans` table.
- Assert counts are equal or report the delta with dates present in only one
  source.

##### 2. `test_composition_total` (parametrized over each matched scan)
For each matched scan, compare top-level body composition:
- API: `GET .../dexa/composition` → total region values
- Local DB: `scans` table row for that `scan_date`
- Fields to compare:

| API field (total region) | DB column | Tolerance |
|---|---|---|
| `fat_mass_kg` | `fat_mass_kg` | 0.05 kg |
| `lean_mass_kg` | `lean_mass_kg` | 0.05 kg |
| `bone_mass_kg` | `bone_mineral_content_kg` | 0.05 kg |
| `tissue_fat_pct` | `total_body_fat_pct` | 0.15 % |
| `android_gynoid_ratio` | `ag_ratio` | 0.02 |

Tolerances account for possible rounding differences between the PDF report
values (which we parse) and the API values (which come from the scanner
database directly).

##### 3. `test_composition_regions` (parametrized over each matched scan)
For each matched scan, compare per-region composition:
- API: `GET .../dexa/composition` → per-region entries
- Local DB: `scan_regions` rows for that `scan_date`
- API regions to match: `left_arm`, `right_arm`, `left_leg`, `right_leg`,
  `trunk`, `android`, `gynoid`
- Fields: `fat_mass_kg`, `lean_mass_kg`, `bone_mass_kg` / `bone_mineral_content_kg`
- Same tolerances as above.
- Region name mapping (API → DB): names expected to align after lowercasing.

##### 4. `test_bone_density` (parametrized over each matched scan)
For each matched scan, compare bone density data:
- API: `GET .../dexa/bone-density` → total + per-region BMD
- Local DB: `scan_bone_density` rows for that `scan_date`
- Fields:

| API field | DB column | Tolerance |
|---|---|---|
| `bone_mineral_density` | `bmd_g_cm2` | 0.002 g/cm2 |
| `peak_sex_t_percentile` | `t_score` (total only) | 0.1 |
| `age_sex_z_percentile` | `z_score` (total only) | 0.1 |

Note: API may use different field names for T/Z scores
(`peak_sex_t_percentile` / `age_sex_z_percentile`). These may be percentiles
rather than raw scores — investigate in the first run and adjust accordingly.

##### 5. `test_visceral_fat` (parametrized over each matched scan)
For each matched scan, compare VAT:
- API: `GET .../dexa/visceral-fat` → `vat_mass_kg`, `vat_volume_cm3`
- Local DB: `scans` row `vat_mass_kg`, `vat_volume_cm3`
- Tolerances: 0.01 kg mass, 0.5 cm3 volume.

##### 6. `test_scan_info` (parametrized over each matched scan)
Compare patient intake data from API scan-info with local DB:
- API: `GET .../dexa/scan-info` → `patient_intake` (likely has height, weight)
- Local DB: `scans` row `height_cm`, `weight_kg`
- Tolerances: 0.5 cm height, 0.5 kg weight (intake vs DEXA-measured may differ).

---

## Part 2 — Composite Image Splitting Accuracy

Validate that the fallback logic for extracting individual body-composition
images (fat, lean mass, bone) from the composite image embedded in BodySpec
DEXA PDFs produces results that are visually and structurally accurate.

### Background

BodySpec DEXA PDF reports (page 1) contain a composite body image showing three
side-by-side views of the body scan: **fat tissue**, **lean tissue**, and
**bone**. When the API does not provide individual images, the fallback path
extracts the composite image from the PDF and splits it into three separate
images by cropping.

The test data for this section lives in `tests/personal_data/` — a git-ignored
directory containing real PDF reports and pre-extracted reference images.

### Test Data Layout

```
tests/personal_data/
├── README.md                  # Instructions for populating test data
├── <scan_date>/               # One folder per scan (e.g. 2024-06-15/)
│   ├── report.pdf             # Original BodySpec PDF report
│   ├── composite.png          # Composite image extracted from the PDF
│   ├── fat_reference.png      # Manually verified fat image (ground truth)
│   ├── lean_reference.png     # Manually verified lean image (ground truth)
│   └── bone_reference.png     # Manually verified bone image (ground truth)
```

The `*_reference.png` files are created once by manually cropping the composite
image (or downloading individual images from the API) and visually verifying
they are correct. These serve as ground truth.

### Test Isolation Strategy

Use `@pytest.mark.personal` marker. These tests are excluded from default runs
alongside the API tests.

**`pyproject.toml`** additions:

```toml
[tool.pytest.ini_options]
markers = [
    "api: BodySpec API verification tests (require network + token)",
    "personal: tests requiring personal data in tests/personal_data/ (git-ignored)",
]
addopts = "-m 'not api and not personal'"
```

Running image tests explicitly:

```bash
# Run only image splitting tests
pytest -m personal -v

# Run everything (API + personal + unit)
pytest -m '' -v
```

### Test File

`tests/test_image_split.py`

#### Fixtures

1. **`personal_data_dir`** — resolves `tests/personal_data/`; `pytest.skip()`
   if the directory is missing or empty.
2. **`scan_folders`** — lists subdirectories of `personal_data_dir`, each
   representing one scan date. Skips if none found.
3. **`composite_and_references`** — parametrized fixture that yields
   `(composite_path, fat_ref_path, lean_ref_path, bone_ref_path)` for each
   scan folder. Skips individual scans where reference files are missing.

#### Test Cases

##### 1. `test_composite_extraction_from_pdf`
Verify the composite image can be extracted from the PDF at all.
- Input: `report.pdf` from each scan folder.
- Action: run the image extraction function on the PDF.
- Assert: output image is non-empty, has reasonable dimensions (width > height,
  at least 300px wide), and is a valid PNG/JPEG.

##### 2. `test_split_produces_three_images`
Verify the split function returns exactly three images.
- Input: `composite.png` from each scan folder.
- Action: run the composite splitting function.
- Assert: returns a list/tuple of exactly 3 images (fat, lean, bone).
- Assert: each image is non-empty and has plausible dimensions (roughly 1/3 the
  width of the composite, same height).

##### 3. `test_split_dimensions_consistent`
Verify the three output images have consistent and correct dimensions.
- Input: `composite.png`.
- Action: split into three images.
- Assert: all three images have the same height as the composite.
- Assert: the sum of the three widths is approximately equal to the composite
  width (within a small tolerance for crop borders/gaps).
- Assert: each individual image width is within 10% of `composite_width / 3`.

##### 4. `test_split_matches_reference_structurally` (parametrized per scan)
Compare each split image against its reference using structural similarity
(SSIM).
- Input: `composite.png` + `*_reference.png` files.
- Action: split composite; compare each result to its corresponding reference.
- Metric: SSIM (scikit-image `structural_similarity`).
- Threshold: SSIM >= 0.95 for each image pair.
- On failure: report the SSIM score and save a diff image to
  `tests/personal_data/<scan_date>/` for visual inspection.

##### 5. `test_split_matches_reference_pixel_diff` (parametrized per scan)
Pixel-level comparison as a complement to SSIM.
- Input: same as above.
- Action: compute per-pixel absolute difference between split result and
  reference, after resizing to match if dimensions differ slightly.
- Assert: mean absolute pixel error < 5 (on 0–255 scale).
- Assert: percentage of pixels with error > 20 is less than 2%.
- On failure: report the mean error and max-error pixel location.

##### 6. `test_split_no_content_leakage`
Verify that each split image contains only its expected region — i.e., the fat
image doesn't include lean/bone content from an adjacent panel.
- Input: `composite.png`.
- Action: split into three images.
- Assert: the rightmost column of the fat image and leftmost column of the lean
  image are not identical (rules out off-by-one crop that leaks content).
- Assert: same check between lean/bone boundary.

##### 7. `test_split_handles_varying_composite_sizes`
Verify the splitting logic is not hard-coded to one specific image size.
- Input: `composite.png` from multiple scan folders (different scan dates may
  produce slightly different image dimensions).
- Action: split each composite.
- Assert: all splits succeed without error.
- Assert: output dimensions scale proportionally with input dimensions.

### Dependencies

Add to `pyproject.toml` optional deps:

```toml
[project.optional-dependencies]
api-test = ["httpx>=0.27.0"]
image-test = [
    "Pillow>=10.0.0",
    "scikit-image>=0.22.0",
    "numpy>=1.26.0",
]
```

---

## Shared Configuration

### `pyproject.toml` — full pytest config

```toml
[tool.pytest.ini_options]
markers = [
    "api: BodySpec API verification tests (require network + token)",
    "personal: tests requiring personal data in tests/personal_data/ (git-ignored)",
]
addopts = "-m 'not api and not personal'"
```

### Git exclusion

`tests/personal_data/` is added to `.gitignore` — it contains real DEXA scan
PDFs and body images that must never be committed to the repository.

---

## Output and Reporting

- On mismatch, assertion messages include both values, the field name, the
  scan date, and the tolerance used — so a failure is immediately actionable.
- Image test failures save diff images alongside the reference files for quick
  visual inspection.
- A summary helper prints a table of all compared fields per scan at the end
  (using pytest's `-v` output or a custom fixture that collects diffs).
- Fields that the API returns but we don't store locally are logged as info
  (candidates for future import enrichment).

## Future Enhancements (not in scope now)

- Automated token refresh via OAuth2 PKCE device flow.
- CI integration with a secrets-managed token.
- Reverse verification: check that PDF → DB import didn't lose data by
  re-parsing PDFs and comparing to DB.
- Percentile endpoint comparison once we store percentile data locally.
- Colorimetric validation: verify that the fat image is predominantly in the
  expected color palette (warm tones), lean in its palette, bone in its palette.
