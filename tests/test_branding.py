import hashlib
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_primary_product_surfaces_use_whykaigi_brand() -> None:
    expected = {
        "frontend/static/index.html": [
            "<h1>WhyKaigi</h1>",
            'class="brand-mark" src="/static/assets/whykaigi-icon.png?v=whykaigi-20260721"',
        ],
        "frontend/static/captions.html": ["실시간 자막 · WhyKaigi"],
        "backend/app/main.py": ['title="WhyKaigi"'],
        "viewer-site/app/layout.tsx": ['default: "WhyKaigi"', "og-whykaigi.jpg"],
        "viewer-site/app/page.tsx": ["WHYKAIGI", "whykaigi-mark"],
        "README.md": ["# WhyKaigi"],
        "README_KO.md": ["# WhyKaigi"],
    }
    for relative_path, markers in expected.items():
        content = (ROOT / relative_path).read_text(encoding="utf-8")
        for marker in markers:
            assert marker in content, f"{marker!r} missing from {relative_path}"


def test_brand_assets_exist_and_fit_distribution_limits() -> None:
    assets = [
        ROOT / "image" / "whykaigi.png",
        ROOT / "frontend" / "static" / "assets" / "whykaigi-icon.png",
        ROOT / "desktop" / "assets" / "whykaigi-icon.png",
        ROOT / "viewer-site" / "public" / "whykaigi-icon.png",
        ROOT / "viewer-site" / "public" / "og-whykaigi.jpg",
        ROOT / "docs" / "assets" / "whykaigi-devpost-thumbnail.png",
    ]
    for asset in assets:
        assert asset.is_file()
        assert 0 < asset.stat().st_size < 5 * 1024 * 1024


def test_runtime_brand_icons_are_identical_square_pngs() -> None:
    icons = [
        ROOT / "frontend" / "static" / "assets" / "whykaigi-icon.png",
        ROOT / "desktop" / "assets" / "whykaigi-icon.png",
        ROOT / "viewer-site" / "public" / "whykaigi-icon.png",
    ]
    hashes = set()
    for icon in icons:
        raw = icon.read_bytes()
        assert raw[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", raw[16:24]) == (512, 512)
        hashes.add(hashlib.sha256(raw).hexdigest())
    assert len(hashes) == 1


def test_old_product_brand_assets_are_removed() -> None:
    old_assets = [
        ROOT / "image" / "verbaradar.png",
        ROOT / "frontend" / "static" / "assets" / "verbaradar-icon.png",
        ROOT / "desktop" / "assets" / "verbaradar.ico",
        ROOT / "desktop" / "assets" / "verbaradar-icon.png",
        ROOT / "viewer-site" / "public" / "verbaradar-icon.png",
        ROOT / "viewer-site" / "public" / "og-verbaradar.jpg",
        ROOT / "docs" / "assets" / "verbaradar-devpost-thumbnail.png",
    ]
    assert not any(path.exists() for path in old_assets)


def test_runtime_surfaces_do_not_regress_to_legacy_display_names() -> None:
    runtime_paths = [
        ROOT / "backend",
        ROOT / "desktop",
        ROOT / "frontend" / "static",
        ROOT / "scripts",
        ROOT / "viewer-site" / "app",
        ROOT / "viewer-site" / "lib",
        ROOT / "viewer-site" / "public" / "demo",
    ]
    legacy_labels = ("VerbaRadar", "Meeting Live Translator")
    for path in runtime_paths:
        files = [path] if path.is_file() else path.rglob("*")
        for file_path in files:
            if not file_path.is_file() or file_path.suffix.lower() not in {
                ".cjs",
                ".html",
                ".js",
                ".json",
                ".mjs",
                ".ps1",
                ".py",
                ".ts",
                ".tsx",
            }:
                continue
            content = file_path.read_text(encoding="utf-8")
            assert not any(label in content for label in legacy_labels), file_path


def test_main_ui_assets_are_cache_safe_and_legacy_viewer_button_is_inert() -> None:
    html = (ROOT / "frontend" / "static" / "index.html").read_text(encoding="utf-8")
    assert html.count("?v=whykaigi-20260721") == 5
    assert '<button id="openLiveShareLinkButton" type="button" hidden' in html
    assert ">보기 화면 열기<" not in html
