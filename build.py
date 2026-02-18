"""
Build script — packages app.py into a standalone executable using PyInstaller.

Usage:
    python build.py

Output:
    Windows: dist/ClaudeUsageMeter.exe  (single-file, ~30-50 MB)
    macOS:   dist/ClaudeUsageMeter.app  (app bundle)
    Linux:   dist/ClaudeUsageMeter      (single-file binary)
"""

import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
ENTRY = ROOT / "app.py"
NAME = "ClaudeUsageMeter"

# Platform-specific icon paths
SYSTEM = platform.system()
if SYSTEM == "Windows":
    ICON = ROOT / "icon.ico"
elif SYSTEM == "Darwin":  # macOS
    ICON = ROOT / "icon.icns"
else:  # Linux and others
    ICON = ROOT / "icon.png"


def _create_icon_image(size):
    """Create a single QImage of the icon at the given size."""
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter

    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)

    # Orange circle
    margin = max(1, size // 16)
    p.setBrush(QColor("#d9773c"))
    p.setPen(Qt.NoPen)
    p.drawEllipse(margin, margin, size - 2 * margin, size - 2 * margin)

    # "C" letter
    p.setPen(QColor("#1a1714"))
    font_size = max(6, int(size * 0.42))
    # Use a cross-platform font
    font_family = {"Windows": "Segoe UI", "Darwin": "Helvetica Neue"}.get(SYSTEM, "Arial")
    p.setFont(QFont(font_family, font_size, QFont.Bold))
    p.drawText(QRect(0, 0, size, size), Qt.AlignCenter, "C")
    p.end()

    return img


def generate_icon():
    """Generate platform-appropriate icon file."""
    if SYSTEM == "Windows":
        _generate_ico()
    elif SYSTEM == "Darwin":
        _generate_icns()
    else:  # Linux
        _generate_png()
    print(f"  Icon generated: {ICON}")


def _generate_ico():
    """Generate a .ico file for Windows."""
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [_create_icon_image(size) for size in sizes]
    _write_ico(images, ICON)


def _generate_icns():
    """Generate a .icns file for macOS."""
    # macOS .icns requires specific sizes
    icns_sizes = {
        16: "16x16",
        32: "16x16@2x",
        32: "32x32",
        64: "32x32@2x",
        128: "128x128",
        256: "128x128@2x",
        256: "256x256",
        512: "256x256@2x",
        512: "512x512",
        1024: "512x512@2x",
    }

    # For simplicity, we'll create a PNG and let PyInstaller convert it
    # Or use iconutil if available. For now, create a high-res PNG.
    img = _create_icon_image(1024)

    # Try to create proper .icns using iconutil (macOS only)
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        iconset = Path(tmpdir) / "icon.iconset"
        iconset.mkdir()

        # Create all required sizes
        for size, name in [(16, "16x16"), (32, "16x16@2x"), (32, "32x32"),
                          (64, "32x32@2x"), (128, "128x128"), (256, "128x128@2x"),
                          (256, "256x256"), (512, "256x256@2x"),
                          (512, "512x512"), (1024, "512x512@2x")]:
            icon_img = _create_icon_image(size)
            icon_img.save(str(iconset / f"icon_{name}.png"), "PNG")

        # Use iconutil to create .icns
        try:
            subprocess.run(
                ["iconutil", "-c", "icns", str(iconset), "-o", str(ICON)],
                check=True,
                capture_output=True
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Fallback: just save as PNG if iconutil is not available
            print("  Warning: iconutil not found, saving as PNG instead")
            img.save(str(ICON.with_suffix('.png')), "PNG")


def _generate_png():
    """Generate a .png file for Linux."""
    img = _create_icon_image(256)
    img.save(str(ICON), "PNG")


def _write_ico(images: list, path: Path):
    """Write a multi-size .ico file from a list of QImages."""
    import struct
    from io import BytesIO

    from PySide6.QtCore import QBuffer, QIODevice

    entries = []
    for img in images:
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        png_data = buf.data().data()
        buf.close()

        w = img.width()
        h = img.height()
        entries.append((w, h, png_data))

    # ICO header: 2 reserved + 2 type (1=icon) + 2 count
    header = struct.pack("<HHH", 0, 1, len(entries))

    # Each directory entry: 16 bytes
    dir_size = 6 + 16 * len(entries)
    offset = dir_size

    dir_entries = b""
    for w, h, data in entries:
        bw = 0 if w >= 256 else w
        bh = 0 if h >= 256 else h
        dir_entries += struct.pack(
            "<BBBBHHII",
            bw, bh,       # width, height (0 = 256)
            0, 0,         # color count, reserved
            1, 32,        # planes, bits per pixel
            len(data),    # size of image data
            offset,       # offset from beginning of file
        )
        offset += len(data)

    with open(path, "wb") as f:
        f.write(header)
        f.write(dir_entries)
        for _, _, data in entries:
            f.write(data)


def build():
    print(f"Building {NAME} for {SYSTEM}...")

    # Need a QApplication for icon generation
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])

    print("  Generating icon...")
    generate_icon()

    # Clean previous build artifacts
    for d in [BUILD, DIST]:
        if d.exists():
            shutil.rmtree(d)

    # Base PyInstaller command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", NAME,
        "--noconfirm",
        "--clean",
        # Hidden imports that PyInstaller may miss
        "--hidden-import", "PySide6.QtSvg",
    ]

    # Add icon if it exists
    if ICON.exists():
        cmd.extend(["--icon", str(ICON)])

    # Platform-specific options
    if SYSTEM == "Darwin":  # macOS
        cmd.extend([
            "--osx-bundle-identifier", "com.anthropic.claudeusagemeter",
            # Include Info.plist customizations if needed
        ])
    elif SYSTEM == "Linux":
        # Linux-specific options can go here
        pass

    cmd.append(str(ENTRY))

    print(f"  Running PyInstaller...")
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print("Build FAILED.", file=sys.stderr)
        sys.exit(1)

    # Find the output file (different extensions per platform)
    if SYSTEM == "Windows":
        output = DIST / f"{NAME}.exe"
    elif SYSTEM == "Darwin":
        output = DIST / f"{NAME}.app"
    else:
        output = DIST / NAME

    if output.exists():
        if output.is_file():
            size_mb = output.stat().st_size / (1024 * 1024)
            print(f"\nBuild complete: {output}  ({size_mb:.1f} MB)")
        else:
            print(f"\nBuild complete: {output}")
    else:
        print(f"\nBuild complete. Check the dist/ directory for output.")


if __name__ == "__main__":
    build()
