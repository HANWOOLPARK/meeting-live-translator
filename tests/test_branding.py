from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_primary_product_surfaces_use_verbaradar_brand() -> None:
    expected = {
        "frontend/static/index.html": [
            "<h1>VerbaRadar</h1>",
            'class="brand-mark" src="/static/assets/verbaradar-icon.png?v=verbaradar-20260721"',
        ],
        "frontend/static/captions.html": ["실시간 자막 · VerbaRadar"],
        "backend/app/main.py": ['title="VerbaRadar"'],
        "viewer-site/app/layout.tsx": ['default: "VerbaRadar"', "og-verbaradar.jpg"],
        "viewer-site/app/page.tsx": ["VERBARADAR", "verbaradar-mark"],
        "README.md": ["# VerbaRadar"],
        "README_KO.md": ["# VerbaRadar"],
    }
    for relative_path, markers in expected.items():
        content = (ROOT / relative_path).read_text(encoding="utf-8")
        for marker in markers:
            assert marker in content, f"{marker!r} missing from {relative_path}"


def test_brand_assets_exist_and_fit_distribution_limits() -> None:
    assets = [
        ROOT / "image" / "verbaradar.png",
        ROOT / "frontend" / "static" / "assets" / "verbaradar-icon.png",
        ROOT / "viewer-site" / "public" / "verbaradar-icon.png",
        ROOT / "viewer-site" / "public" / "og-verbaradar.jpg",
    ]
    for asset in assets:
        assert asset.is_file()
        assert 0 < asset.stat().st_size < 5 * 1024 * 1024


def test_main_ui_assets_are_cache_safe_and_legacy_viewer_button_is_inert() -> None:
    html = (ROOT / "frontend" / "static" / "index.html").read_text(encoding="utf-8")
    assert html.count("?v=verbaradar-20260721") == 5
    assert '<button id="openLiveShareLinkButton" type="button" hidden' in html
    assert ">보기 화면 열기<" not in html
