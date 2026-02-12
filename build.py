"""
Build script — packages app.py into a standalone .exe using PyInstaller.

Usage:
    python build.py

Output:
    dist/ClaudeUsageMeter.exe  (single-file, ~30-50 MB)
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
ICON = ROOT / "icon.ico"
ENTRY = ROOT / "app.py"
NAME = "ClaudeUsageMeter"


def generate_icon():
    """Generate a .ico file from QPainter rendering (same look as the tray icon)."""
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter

    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = []

    for size in sizes:
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
        p.setFont(QFont("Segoe UI", font_size, QFont.Bold))
        p.drawText(QRect(0, 0, size, size), Qt.AlignCenter, "C")
        p.end()

        images.append(img)

    # Write .ico — Qt can save .ico natively on Windows
    # but only single-size. Use the largest and let Windows scale.
    # For a proper multi-size .ico, write manually.
    _write_ico(images, ICON)
    print(f"  Icon generated: {ICON}")


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
    print(f"Building {NAME}...")

    # Need a QApplication for icon generation
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])

    print("  Generating icon...")
    generate_icon()

    # Clean previous build artifacts
    for d in [BUILD, DIST]:
        if d.exists():
            shutil.rmtree(d)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", NAME,
        "--icon", str(ICON),
        "--noconfirm",
        "--clean",
        # Hidden imports that PyInstaller may miss
        "--hidden-import", "PySide6.QtSvg",
        str(ENTRY),
    ]

    print(f"  Running PyInstaller...")
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print("Build FAILED.", file=sys.stderr)
        sys.exit(1)

    exe = DIST / f"{NAME}.exe"
    size_mb = exe.stat().st_size / (1024 * 1024)
    print(f"\nBuild complete: {exe}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    build()
