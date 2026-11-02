"""Regenerate app/intellect/source/x_layers_v0_3B.json from the source PDF.

    python scripts/build_source_pack.py [path/to/X_Layers_v0.3B_Rules.pdf]

Fails (exit 1) on any parser warning or if the counts are not 10 layers / 93 rules,
so a bad extraction can never silently become the seed.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.intellect.source_parser import parse_pdf  # noqa: E402

DEFAULT_PDF = ROOT.parent / "docs" / "source" / "X_Layers_v0.3B_Rules.pdf"
OUT = ROOT / "app" / "intellect" / "source" / "x_layers_v0_3B.json"
EXPECTED_LAYERS, EXPECTED_RULES = 10, 93


def main() -> int:
    pdf = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PDF
    fw = parse_pdf(pdf)
    problems = list(fw.warnings)
    if len(fw.layers) != EXPECTED_LAYERS:
        problems.append(f"expected {EXPECTED_LAYERS} layers, parsed {len(fw.layers)}")
    if len(fw.rules) != EXPECTED_RULES:
        problems.append(f"expected {EXPECTED_RULES} rules, parsed {len(fw.rules)}")
    if problems:
        print("Source pack NOT written. Discrepancies:")
        for p in problems:
            print("  -", p)
        return 1
    data = fw.to_dict()
    data["source_file"] = pdf.name
    data["source_sha256"] = hashlib.sha256(pdf.read_bytes()).hexdigest()
    data["pack_id"] = "x_layers_v0_3B"
    data["transformations"] = [
        "typographic ligatures (U+FB00-U+FB04) replaced by their letters",
        "PDF line wraps re-joined; a hyphen attached to a word at line end joins without a space",
        "page footers and repeated table headers removed",
        "row markers 'Always on' / 'Hard limit · always on' moved from the rule text into source_marker",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(fw.layers)} layers, {len(fw.rules)} rules, "
          f"{len(fw.stages)} stages, {len(fw.always_on)} always-on")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
