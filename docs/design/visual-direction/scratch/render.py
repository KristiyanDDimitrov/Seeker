"""Scratch: render the harness screens for one direction into a dir."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import screenshots
from PySide6.QtWidgets import QApplication
out = Path(sys.argv[1])
pages = sys.argv[2].split(",") if len(sys.argv) > 2 else ["dashboard","review","settings-general","settings-matching","wizard"]
app = QApplication.instance() or QApplication([])
if os.environ.get("SEEKER_SCRATCH_DIRECTION"):
    sys.path.insert(0, str(Path(__file__).parent))
    import direction
    direction.install(app)
w = screenshots.render_all(app, out, pages, screenshots.THEMES, ((1280, 820),))
print(len(w), "images")
