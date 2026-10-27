"""
Renders the agent logos (SVG, used by the macOS plugin) to PNGs for the Linux
plugin, since Pillow can't draw SVG. Run it after changing a logo:

    pip install PySide6-Essentials && python3 tools/render_agent_logos.py
"""

import glob
import os

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SOURCE = os.path.join(ROOT, "elgato", "com.rucker.agent-sessions.sdPlugin", "imgs", "agents")
OUT = os.path.join(ROOT, "com_rucker_AgentSessions", "assets")
SIZE = 256


def main() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QGuiApplication([])  # noqa: F841 - QPainter needs one
    os.makedirs(OUT, exist_ok=True)
    for svg in sorted(glob.glob(os.path.join(SOURCE, "*.svg"))):
        image = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        QSvgRenderer(svg).render(painter, QRectF(0, 0, SIZE, SIZE))
        painter.end()
        out = os.path.join(OUT, os.path.basename(svg)[:-4] + ".png")
        image.save(out)
        print(f"Wrote {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
