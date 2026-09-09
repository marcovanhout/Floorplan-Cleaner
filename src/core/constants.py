"""Keyword lists en regex-patronen voor laagfiltering en naam-herkenning.

Overgenomen uit Plattegrond_Schoonmaker_v1/floorplan_cleaner.py.
"""

import re

# Standaard keywoorden voor lagen die BEHOUDEN moeten blijven.
DEFAULT_KEEP_KEYWORDS = [
    "A-WALL", "A-DOOR", "A-GLAZ", "S-STRS", "S-STAIR", "A-STAIR",
    "I-WALL",
    # "WAND" is het gangbare synoniem voor "MUUR" (bv. "0_wanden"); "RAMEN"
    # apart naast "RAAM" omdat het Nederlandse meervoud onregelmatig is
    # ("raam" -> "ramen", niet "raamen") en dus geen substring-match geeft.
    "MUUR", "WAND", "DEUR", "RAAM", "RAMEN", "TRAP", "GLAS", "KOZIJN",
]

DEFAULT_DROP_KEYWORDS = [
    "AREA", "ANNO", "GRID", "TOPO", "DETL", "RHK", "GRADE", "FILL & SIGN",
]

# Patronen die duiden op een "code" (geen bruikbare ruimtenaam):
# ZHD-achtige ruimtecodes, wandtype/deur/raam-codes, m²-waarden, cijfers.
CODE_PATTERNS = [
    r"^[A-Z]{2,4}[-.]",          # ZHD-1.234, generieke projectcode
    r"^[A-Z]{1,2}-[A-Za-z0-9.]+$",  # P-P2d, W-W25, PT-PT03, VL-V2i, P-Be
    r"m.$",                       # eindigt op "m2/m²" (oppervlakte)
    r"^\d",                       # begint met een cijfer (afmetingen)
]
ROOM_CODE_PATTERN = re.compile(r"[A-Z]{2,4}[-.][\d.]+")
