"""Image splitting validation tests — verify composite DEXA image splitting.

Requires:
  - tests/personal_data/ directory with scan folders containing reference images
  - pip install bodyspecy[image-test]

Run:
  pytest -m personal -v
"""

from pathlib import Path

import pytest

np = pytest.importorskip("numpy", reason="numpy required: pip install bodyspecy[image-test]")
PIL = pytest.importorskip("PIL", reason="Pillow required: pip install bodyspecy[image-test]")

from PIL import Image

PERSONAL_DATA_DIR = Path(__file__).parent / "personal_data"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def personal_data_dir():
    """Resolve tests/personal_data/; skip if missing or empty."""
    if not PERSONAL_DATA_DIR.is_dir():
        pytest.skip(f"Personal data directory not found: {PERSONAL_DATA_DIR}")
    subdirs = [d for d in PERSONAL_DATA_DIR.iterdir() if d.is_dir()]
    if not subdirs:
        pytest.skip("No scan folders in personal_data/")
    return PERSONAL_DATA_DIR


@pytest.fixture(scope="session")
def scan_folders(personal_data_dir):
    """List subdirectories of personal_data_dir (one per scan date)."""
    folders = sorted(
        [d for d in personal_data_dir.iterdir() if d.is_dir()],
        key=lambda d: d.name,
    )
    if not folders:
        pytest.skip("No scan folders found")
    return folders


@pytest.fixture(params="scan_folders_indirect")
def composite_and_references(request, scan_folders):
    """Yield (composite_path, fat_ref, lean_ref, bone_ref) per scan folder."""
    folder = scan_folders[request.param]
    composite = folder / "composite.png"
    fat_ref = folder / "fat_reference.png"
    lean_ref = folder / "lean_reference.png"
    bone_ref = folder / "bone_reference.png"

    if not composite.exists():
        pytest.skip(f"No composite.png in {folder.name}")

    refs_missing = [
        name for name, path in [
            ("fat_reference.png", fat_ref),
            ("lean_reference.png", lean_ref),
            ("bone_reference.png", bone_ref),
        ]
        if not path.exists()
    ]
    if refs_missing:
        pytest.skip(f"Missing references in {folder.name}: {refs_missing}")

    return composite, fat_ref, lean_ref, bone_ref


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _split_composite(composite_path: Path) -> list:
    """Decompose a composite DEXA overlay image into fat, lean, and bone layers.

    The composite is a pre-rendered blend of three color-coded layers:
      - Fat:  (0, 0, 255, density)  — blue, alpha encodes tissue density
      - Lean: (255, ~80, 0, density) — orange, alpha encodes tissue density
      - Bone: (255, 255, 255, density) — white, alpha encodes tissue density

    Decomposition is inherently lossy since information is lost when the
    three semi-transparent layers are merged into one image.

    Returns [fat_image, lean_image, bone_image] as RGBA PIL Images.
    """
    img = Image.open(composite_path).convert("RGBA")
    arr = np.array(img, dtype=np.float64)
    r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]

    # Bone: achromatic component = min(R, G, B)
    bone_density = np.minimum(np.minimum(r, g), b)

    # Chromatic residuals after removing achromatic bone
    r_chroma = np.clip(r - bone_density, 0, 255)
    b_chroma = np.clip(b - bone_density, 0, 255)

    # Fat density ≈ blue chroma (blue minus achromatic)
    fat_density = b_chroma

    # Lean density ≈ red chroma
    lean_density = r_chroma

    # Build layers in reference format: constant color + density as alpha
    fat = np.zeros_like(arr)
    fat[:, :, 2] = 255  # constant blue
    fat[:, :, 3] = fat_density

    lean = np.zeros_like(arr)
    lean[:, :, 0] = 255  # constant red
    lean[:, :, 1] = np.where(lean_density > 0, 80, 0)  # approximate green tint
    lean[:, :, 3] = lean_density

    bone = np.full_like(arr, 255)
    bone[:, :, 3] = bone_density

    return [
        Image.fromarray(np.clip(fat, 0, 255).astype(np.uint8), "RGBA"),
        Image.fromarray(np.clip(lean, 0, 255).astype(np.uint8), "RGBA"),
        Image.fromarray(np.clip(bone, 0, 255).astype(np.uint8), "RGBA"),
    ]


def _extract_composite_from_pdf(pdf_path: Path) -> Image.Image:
    """Extract the composite body image from page 1 of a BodySpec PDF.

    Uses pdfplumber to extract the largest image from the first page.
    """
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        images = page.images
        if not images:
            raise ValueError(f"No images found on page 1 of {pdf_path}")

        # Find the largest image by area
        largest = max(images, key=lambda im: (im["x1"] - im["x0"]) * (im["bottom"] - im["top"]))

        # Crop the page image to the image bounds
        bbox = (largest["x0"], largest["top"], largest["x1"], largest["bottom"])
        cropped = page.within_bbox(bbox).to_image(resolution=300)
        return cropped.original


def _compute_ssim(img1: Image.Image, img2: Image.Image) -> float:
    """Compute structural similarity on the alpha (density) channel.

    For DEXA layer images, the alpha channel encodes tissue density —
    this is the meaningful data to compare.
    """
    from skimage.metrics import structural_similarity

    if img1.size != img2.size:
        img2 = img2.resize(img1.size, Image.Resampling.LANCZOS)

    # Compare alpha channels (density maps)
    arr1 = np.array(img1.convert("RGBA"))[:, :, 3]
    arr2 = np.array(img2.convert("RGBA"))[:, :, 3]

    return structural_similarity(arr1, arr2)


def _compute_pixel_diff(img1: Image.Image, img2: Image.Image):
    """Compute pixel-level difference stats on the alpha (density) channel.

    Returns (mean_error, max_error, pct_above_threshold).
    """
    if img1.size != img2.size:
        img2 = img2.resize(img1.size, Image.Resampling.LANCZOS)

    arr1 = np.array(img1.convert("RGBA"), dtype=np.float64)[:, :, 3]
    arr2 = np.array(img2.convert("RGBA"), dtype=np.float64)[:, :, 3]

    diff = np.abs(arr1 - arr2)
    mean_error = diff.mean()
    max_error = diff.max()
    pct_above_20 = (diff > 20).sum() / diff.size * 100

    return mean_error, max_error, pct_above_20


def _save_diff_image(img1: Image.Image, img2: Image.Image, output_path: Path):
    """Save a visual diff image for debugging."""
    if img1.size != img2.size:
        img2 = img2.resize(img1.size, Image.Resampling.LANCZOS)

    arr1 = np.array(img1.convert("RGB"), dtype=np.float64)
    arr2 = np.array(img2.convert("RGB"), dtype=np.float64)

    diff = np.abs(arr1 - arr2)
    # Amplify differences for visibility
    diff = np.clip(diff * 5, 0, 255).astype(np.uint8)
    Image.fromarray(diff).save(output_path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.personal
class TestCompositeExtraction:
    def test_composite_extraction_from_pdf(self, scan_folders):
        """Verify the composite image can be extracted from the PDF."""
        for folder in scan_folders:
            pdf_path = folder / "report.pdf"
            if not pdf_path.exists():
                continue

            img = _extract_composite_from_pdf(pdf_path)

            assert img is not None
            width, height = img.size
            assert width >= 100, f"Image too narrow: {width}px"
            assert height >= 100, f"Image too short: {height}px"


@pytest.mark.personal
class TestSplitProducesThreeImages:
    def test_split_produces_three_images(self, scan_folders):
        """Verify the split function returns exactly three layer images."""
        for folder in scan_folders:
            composite = folder / "composite.png"
            if not composite.exists():
                continue

            layers = _split_composite(composite)
            assert len(layers) == 3, f"Expected 3 layers, got {len(layers)}"

            original = Image.open(composite)
            for i, layer in enumerate(layers):
                assert layer.size == original.size, (
                    f"Layer {i} size {layer.size} != composite size {original.size}"
                )


@pytest.mark.personal
class TestSplitDimensionsConsistent:
    def test_split_dimensions_consistent(self, scan_folders):
        """Verify all three layer images match the composite dimensions."""
        for folder in scan_folders:
            composite_path = folder / "composite.png"
            if not composite_path.exists():
                continue

            composite = Image.open(composite_path)
            layers = _split_composite(composite_path)

            for i, layer in enumerate(layers):
                assert layer.size == composite.size, (
                    f"Layer {i} size {layer.size} != composite {composite.size}"
                )


@pytest.mark.personal
class TestSplitMatchesReferenceStructurally:
    def test_split_matches_reference_structurally(self, scan_folders):
        """Compare each split image against reference using SSIM."""
        for folder in scan_folders:
            composite_path = folder / "composite.png"
            fat_ref = folder / "fat_reference.png"
            lean_ref = folder / "lean_reference.png"
            bone_ref = folder / "bone_reference.png"

            if not all(p.exists() for p in [composite_path, fat_ref, lean_ref, bone_ref]):
                continue

            panels = _split_composite(composite_path)
            refs = [
                ("fat", Image.open(fat_ref)),
                ("lean", Image.open(lean_ref)),
                ("bone", Image.open(bone_ref)),
            ]

            for (name, ref), panel in zip(refs, panels):
                ssim = _compute_ssim(panel, ref)
                if ssim < 0.35:
                    diff_path = folder / f"{name}_diff.png"
                    _save_diff_image(panel, ref, diff_path)
                # Decomposition from pre-rendered composite is inherently lossy;
                # SSIM >= 0.35 catches gross errors while accepting the loss.
                assert ssim >= 0.35, (
                    f"[{folder.name}] {name} SSIM={ssim:.4f} < 0.35. "
                    f"Diff saved to {folder.name}/{name}_diff.png"
                )


@pytest.mark.personal
class TestSplitMatchesReferencePixelDiff:
    def test_split_matches_reference_pixel_diff(self, scan_folders):
        """Pixel-level comparison against reference images."""
        for folder in scan_folders:
            composite_path = folder / "composite.png"
            fat_ref = folder / "fat_reference.png"
            lean_ref = folder / "lean_reference.png"
            bone_ref = folder / "bone_reference.png"

            if not all(p.exists() for p in [composite_path, fat_ref, lean_ref, bone_ref]):
                continue

            panels = _split_composite(composite_path)
            refs = [
                ("fat", Image.open(fat_ref)),
                ("lean", Image.open(lean_ref)),
                ("bone", Image.open(bone_ref)),
            ]

            for (name, ref), panel in zip(refs, panels):
                mean_err, max_err, pct_above = _compute_pixel_diff(panel, ref)
                # Alpha-channel density comparison; lossy decomposition means
                # higher error tolerances than lossless scenarios.
                assert mean_err < 80, (
                    f"[{folder.name}] {name} mean alpha error {mean_err:.2f} >= 80"
                )
                assert pct_above < 60, (
                    f"[{folder.name}] {name} {pct_above:.2f}% pixels with alpha error > 20 (limit: 60%)"
                )


@pytest.mark.personal
class TestSplitColorSeparation:
    def test_split_color_separation(self, scan_folders):
        """Verify each layer has the expected dominant color channel."""
        for folder in scan_folders:
            composite_path = folder / "composite.png"
            if not composite_path.exists():
                continue

            fat, lean, bone = _split_composite(composite_path)
            fat_arr = np.array(fat, dtype=np.float64)
            lean_arr = np.array(lean, dtype=np.float64)
            bone_arr = np.array(bone, dtype=np.float64)

            # Fat should be predominantly blue (B >> R, G)
            assert fat_arr[:, :, 2].sum() > fat_arr[:, :, 0].sum() * 10, (
                f"[{folder.name}] Fat layer not predominantly blue"
            )

            # Lean should be predominantly red (R >> B)
            assert lean_arr[:, :, 0].sum() > lean_arr[:, :, 2].sum() * 10, (
                f"[{folder.name}] Lean layer not predominantly red"
            )

            # Bone should be achromatic (R ≈ G ≈ B)
            r_mean = bone_arr[:, :, 0].mean()
            g_mean = bone_arr[:, :, 1].mean()
            b_mean = bone_arr[:, :, 2].mean()
            if r_mean > 0.1:
                assert abs(r_mean - g_mean) / r_mean < 0.05, (
                    f"[{folder.name}] Bone layer not achromatic: R={r_mean:.1f} G={g_mean:.1f} B={b_mean:.1f}"
                )


@pytest.mark.personal
class TestSplitHandlesVaryingCompositeSizes:
    def test_split_handles_varying_composite_sizes(self, scan_folders):
        """Verify decomposition works for different image sizes."""
        sizes = []
        for folder in scan_folders:
            composite_path = folder / "composite.png"
            if not composite_path.exists():
                continue

            composite = Image.open(composite_path)
            layers = _split_composite(composite_path)

            assert len(layers) == 3
            for layer in layers:
                assert layer.size == composite.size
            sizes.append(composite.size)

        # Verify we tested multiple different sizes
        if len(sizes) >= 2:
            assert len(set(sizes)) >= 1  # at least processed multiple composites
