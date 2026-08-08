"""Record the current validator behavior for the intentional PPTX error fixtures."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.validator import validate_pptx  # noqa: E402


FIXTURE_DIR = ROOT / "testdata" / "pptx_variants"
MANIFEST_PATH = FIXTURE_DIR / "manifest.json"
OUTPUT_PATH = FIXTURE_DIR / "validator-baseline.json"


def category_counts(result: dict) -> dict[str, int]:
    return {
        item["category"]: int(item["count"])
        for item in result.get("by_category", [])
    }


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    source_path = ROOT / manifest["source"]
    source_result = validate_pptx(source_path)
    source_counts = Counter(category_counts(source_result))

    variants = []
    for item in manifest["variants"]:
        result = validate_pptx(FIXTURE_DIR / item["file"])
        counts = Counter(category_counts(result))
        all_categories = sorted(set(source_counts) | set(counts))
        variants.append(
            {
                "file": item["file"],
                "expectedCategories": item["expectedCategories"],
                "total": result["total"],
                "byCategory": dict(counts),
                "deltaFromSource": {
                    category: counts[category] - source_counts[category]
                    for category in all_categories
                    if counts[category] != source_counts[category]
                },
                "issues": result["issues"],
            }
        )

    baseline = {
        "schemaVersion": 1,
        "source": {
            "file": manifest["source"],
            "total": source_result["total"],
            "byCategory": dict(source_counts),
        },
        "variants": variants,
    }
    OUTPUT_PATH.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
