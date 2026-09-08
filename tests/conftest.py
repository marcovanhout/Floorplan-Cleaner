import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Maakt de v1-prototypemap importeerbaar voor de regressietest, zonder
# 'm te verplaatsen (blijft op zijn plek als referentie/historie).
V1_DIR = REPO_ROOT / "Plattegrond_Schoonmaker_v1"
if str(V1_DIR) not in sys.path:
    sys.path.insert(0, str(V1_DIR))

SIMPLE_FLOORPLAN_PDF = FIXTURES_DIR / "simple_floorplan.pdf"
