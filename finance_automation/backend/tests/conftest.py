import sys
from pathlib import Path

# Backend modules are imported as top-level packages (services, app, utils).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
