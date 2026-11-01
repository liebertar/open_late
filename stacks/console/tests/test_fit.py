"""Size recommendation and fit codes. Run: uv run --no-project --with pytest --with fastapi --with httpx --with pyyaml pytest stacks/console/tests"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).parents[1] / "app"))

import fitting  # noqa: E402

SIZES = ["XS", "S", "M", "L", "XL"]
EASE = {"XS": -67, "S": 46, "M": 160, "L": 274, "XL": 387}  # f-M-east_asian against the current Hugo pattern
FITS = {s: {"ease_mm": e} for s, e in EASE.items()}


def test_each_preference_picks_the_nearest_ease():
    assert fitting.recommend(FITS, SIZES, "slim")["size"] == "S"
    assert fitting.recommend(FITS, SIZES, "regular")["size"] == "M"
    assert fitting.recommend(FITS, SIZES, "relaxed")["size"] == "M"


def test_alternative_sits_on_the_side_the_target_falls():
    r = fitting.recommend(FITS, SIZES, "relaxed")  # target 210, M gives 160: L is the other candidate
    assert (r["alt"], r["alt_dir"]) == ("L", "roomier")
    r = fitting.recommend(FITS, SIZES, "regular")  # target 125, M gives 160: S is the other candidate
    assert (r["alt"], r["alt_dir"]) == ("S", "closer")


def test_alternative_stays_inside_the_size_run():
    low = {s: {"ease_mm": e + 300} for s, e in EASE.items()}
    assert fitting.recommend(low, SIZES, "slim") == {"size": "XS", "alt": "S", "alt_dir": "roomier", "confidence": "low"}
    high = {s: {"ease_mm": e - 400} for s, e in EASE.items()}
    r = fitting.recommend(high, SIZES, "relaxed")
    assert (r["size"], r["alt"], r["alt_dir"]) == ("XL", "L", "closer")


def test_confidence_falls_as_the_best_size_misses_the_target():
    assert fitting.recommend({s: {"ease_mm": 60 + (i - 2) * 113} for i, s in enumerate(SIZES)}, SIZES, "slim")["confidence"] == "high"
    assert fitting.recommend(FITS, SIZES, "regular")["confidence"] == "medium"
    assert fitting.recommend(FITS, SIZES, "relaxed")["confidence"] == "low"
