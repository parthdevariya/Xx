"""Parser for X Layers rules-pack documents (the format of X_Layers_v0.3B_Rules.pdf).

The parser preserves source wording. The only transformations applied are:

* typographic ligature glyphs are replaced by their letters (U+FB00..U+FB04),
* line breaks introduced by the PDF's column layout are re-joined
  (a line ending in a hyphen attached to a word joins without a space,
  so "non-\\nimminent" stays "non-imminent" and "MC-\\n01" becomes "MC-01"),
* page footers and repeated table headers are removed.

Nothing is paraphrased, reordered or inferred. The source's own "Always on" /
"Hard limit · always on" markers are kept in ``source_marker`` and the full
unmodified rule block is kept in ``source_block``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl"}

RULE_ID = re.compile(r"^([A-Z]{2,4})-(\d{2})$")
PRIORITY = re.compile(r"^P([1-9])$")
PROVENANCE = re.compile(r"^(?:[EBSPG](?:\+G)?|G\d|G-review)$")
LAYER_HEADER = re.compile(r"^([A-Z]{2,4}) (.+?) (\d+) rules$")
FOOTER = re.compile(r"^X Layers v[\w.]+ Rules · page \d+ of \d+$")
TABLE_HEADER = "ID Rule Applies when / Not when"
MARKERS = ("Hard limit · always on", "Always on")


class SourceParseError(ValueError):
    pass


@dataclass
class SourceRule:
    rule_id: str
    layer: str
    number: int
    priority: int
    provenance: str
    text: str
    applies_when: str
    not_when: str
    source_marker: str | None
    page: int
    position: int  # order within its layer as printed
    source_block: str
    sha256: str = ""

    def compute_hash(self) -> str:
        payload = "\x1f".join([self.rule_id, f"P{self.priority}", self.provenance,
                               self.text, self.applies_when, self.not_when,
                               self.source_marker or ""])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class SourceLayer:
    code: str
    name: str
    question: str
    description: str
    declared_rule_count: int
    page: int
    tier: int | None = None
    tier_basis: str = ""


@dataclass
class SourceStage:
    position: int
    layer: str
    mode: str
    source_label: str
    bound_to: int | None = None  # position of the stage an EFV sub-stage belongs to


@dataclass
class SourceFramework:
    title: str
    subtitle: str
    framework_name: str
    version: str
    preamble: str
    sequence_text: str
    stages: list[SourceStage]
    hierarchy: list[dict]
    hierarchy_note: str
    always_on: list[str]
    hard_limits: list[str]
    hard_limit_note: str
    legend: str
    layers: list[SourceLayer]
    rules: list[SourceRule]
    declared_total: int
    library: dict
    planned: dict
    footer_note: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def normalise(text: str) -> str:
    for glyph, letters in LIGATURES.items():
        text = text.replace(glyph, letters)
    return text


def join_lines(lines: list[str]) -> str:
    out = ""
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if not out:
            out = line
        elif out.endswith("-") and len(out) >= 2 and out[-2] != " ":
            out += line
        else:
            out += " " + line
    return out


def extract_pages(pdf_path: str | Path) -> list[str]:
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    return [normalise(p.extract_text() or "") for p in reader.pages]


# ---------------------------------------------------------------------------
# overview page
# ---------------------------------------------------------------------------

def _between(text: str, start: str, end: str) -> str:
    i = text.find(start)
    if i < 0:
        raise SourceParseError(f"marker not found: {start!r}")
    i += len(start)
    j = text.find(end, i) if end else len(text)
    if j < 0:
        raise SourceParseError(f"marker not found: {end!r}")
    return text[i:j]


def parse_sequence(sequence_text: str) -> list[SourceStage]:
    """'CB → TP (frame) → HM (read, EFV picks preset) → …' into ordered stages."""
    stages: list[SourceStage] = []
    for token in [t.strip() for t in sequence_text.split("→")]:
        m = re.match(r"^([A-Z]{2,4})(?:\s*\((.*)\))?$", token)
        if not m:
            raise SourceParseError(f"cannot read sequence token {token!r}")
        code, args = m.group(1), m.group(2)
        parts = [a.strip() for a in args.split(",")] if args else []
        mode = parts[0] if parts and not re.match(r"^[A-Z]{2,4} ", parts[0]) else "main"
        stages.append(SourceStage(len(stages) + 1, code, mode, token))
        owner = len(stages)
        for sub in parts[1:] if mode != "main" else parts:
            sm = re.match(r"^([A-Z]{2,4}) (.+)$", sub)
            if not sm:
                raise SourceParseError(f"cannot read sub-stage {sub!r} in {token!r}")
            verb = sm.group(2)
            sub_mode = {"picks preset": "select_preset", "applies preset": "apply_preset"}.get(verb)
            if sub_mode is None:
                raise SourceParseError(f"unknown sub-stage action {verb!r}")
            stages.append(SourceStage(len(stages) + 1, sm.group(1), sub_mode, sub, bound_to=owner))
    return stages


def parse_hierarchy(block: str) -> list[dict]:
    """Numbered conflict hierarchy. Returns [{rank, label, layers, raw}]."""
    items = re.split(r"(?m)^\s*(\d)\.\s+", block)
    out = []
    for k in range(1, len(items), 2):
        rank = int(items[k])
        raw = join_lines(items[k + 1].splitlines())
        label = raw.split("(")[0].strip()
        layers: list[str] = []
        inner = re.search(r"\((.*)\)", raw)
        if inner:
            body = inner.group(1)
            owner_part = re.split(r",?\s*judged by\s+", body)[0]
            owner_part = owner_part.replace("with inputs from", ",")
            layers = [c for c in re.findall(r"\b([A-Z]{2,4})\b", owner_part)]
        out.append({"rank": rank, "label": label, "layers": layers, "raw": raw})
    return out


def parse_overview(page: str) -> dict:
    lines = [l for l in page.splitlines() if not FOOTER.match(l.strip())]
    text = "\n".join(lines)
    title = lines[0].strip()
    subtitle = lines[1].strip()
    m = re.match(r"^(.*?) (v[\w.]+) — ", title)
    if not m:
        raise SourceParseError(f"cannot read framework name/version from title {title!r}")
    preamble = join_lines(_between(text, subtitle, "CB →").splitlines())
    seq_raw = "CB →" + _between(text, "CB →", "When rules conflict")
    sequence_text = join_lines(seq_raw.splitlines())
    hier_block = _between(text, "When rules conflict, the higher wins", "HM, EFV and all settings")
    hierarchy_note = join_lines(("HM, EFV and all settings" + _between(
        text, "HM, EFV and all settings", "Always on:")).splitlines())
    always_block = _between(text, "can turn these off", "Moral Compass Hard Limits")
    hard_block = "Moral Compass Hard Limits" + _between(text, "Moral Compass Hard Limits", "Legend")
    legend = join_lines(_between(text, "Legend", "Layer Question it answers Rules").splitlines())
    table = _between(text, "Layer Question it answers Rules", "")
    total = re.search(r"^Total (\d+)$", table, re.M)
    hard_ids = re.findall(r"\b[A-Z]{2,4}-\d{2}\b", hard_block.split(")")[0])
    return {
        "title": title,
        "subtitle": subtitle,
        "framework_name": m.group(1),
        "version": m.group(2),
        "preamble": preamble,
        "sequence_text": sequence_text,
        "stages": parse_sequence(sequence_text.replace("\n", " ")),
        "hierarchy": parse_hierarchy(hier_block),
        "hierarchy_note": hierarchy_note,
        "always_on": re.findall(r"\b[A-Z]{2,4}-\d{2}\b", always_block),
        "hard_limits": hard_ids,
        "hard_limit_note": join_lines(hard_block.splitlines()),
        "legend": legend,
        "declared_total": int(total.group(1)) if total else -1,
        "layer_questions": {
            mm.group(1): (mm.group(2), mm.group(3), int(mm.group(4)))
            for mm in re.finditer(r"(?m)^([A-Z]{2,4}) (.+?) ((?:What|How|At what)[^\n]*?\?) (\d+)$", table)
        },
    }


# ---------------------------------------------------------------------------
# layer pages
# ---------------------------------------------------------------------------

def _clean_rule_lines(page_lines: list[str]) -> list[str]:
    return [l for l in page_lines
            if l.strip() and not FOOTER.match(l.strip()) and l.strip() != TABLE_HEADER]


def parse_rule_pages(pages: list[str], start_page: int = 2) -> tuple[list[SourceLayer], list[SourceRule], int]:
    """Parse pages until the Library page. Returns (layers, rules, library_page_index)."""
    layers: list[SourceLayer] = []
    rules: list[SourceRule] = []
    current_layer: SourceLayer | None = None
    rule_buf: dict | None = None
    expecting_layer_intro = 0
    library_index = len(pages)

    def flush():
        nonlocal rule_buf
        if rule_buf is None:
            return
        rules.append(_finish_rule(rule_buf))
        rule_buf = None

    for pidx in range(start_page - 1, len(pages)):
        page_no = pidx + 1
        lines = _clean_rule_lines(pages[pidx].splitlines())
        if lines and lines[0].startswith("Library"):
            library_index = pidx
            break
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            lh = LAYER_HEADER.match(line)
            if lh and (i + 1 < len(lines)):
                flush()
                current_layer = SourceLayer(code=lh.group(1), name=lh.group(2),
                                            question=lines[i + 1].strip(), description="",
                                            declared_rule_count=int(lh.group(3)), page=page_no)
                layers.append(current_layer)
                desc: list[str] = []
                i += 2
                while i < len(lines) and not RULE_ID.match(lines[i].strip()):
                    desc.append(lines[i])
                    i += 1
                current_layer.description = join_lines(desc)
                continue
            rm = RULE_ID.match(line)
            if rm and i + 2 < len(lines) and PRIORITY.match(lines[i + 1].strip()) \
                    and PROVENANCE.match(lines[i + 2].strip()):
                flush()
                if current_layer is None or rm.group(1) != current_layer.code:
                    raise SourceParseError(f"rule {line} found outside its layer section (page {page_no})")
                rule_buf = {
                    "rule_id": line, "layer": rm.group(1), "number": int(rm.group(2)),
                    "priority": int(PRIORITY.match(lines[i + 1].strip()).group(1)),
                    "provenance": lines[i + 2].strip(), "page": page_no,
                    "position": sum(1 for r in rules if r.layer == rm.group(1)) + 1,
                    "body": [], "block": [line, lines[i + 1].strip(), lines[i + 2].strip()],
                }
                i += 3
                continue
            if rule_buf is not None:
                rule_buf["body"].append(line)
                rule_buf["block"].append(line)
            i += 1
    flush()
    return layers, rules, library_index


def _finish_rule(buf: dict) -> SourceRule:
    body: list[str] = buf["body"]
    try:
        w = next(k for k, l in enumerate(body) if l.startswith("When:"))
        n = next(k for k, l in enumerate(body) if l.startswith("Not when:") and k > w)
    except StopIteration as exc:
        raise SourceParseError(f"{buf['rule_id']}: missing When/Not when columns") from exc
    text = join_lines(body[:w])
    marker = None
    for mk in MARKERS:
        if text.endswith(" " + mk) or text == mk:
            marker = mk
            text = text[: -len(mk)].rstrip()
            break
    when_lines = [body[w][len("When:"):]] + body[w + 1:n]
    not_lines = [body[n][len("Not when:"):]] + body[n + 1:]
    rule = SourceRule(
        rule_id=buf["rule_id"], layer=buf["layer"], number=buf["number"],
        priority=buf["priority"], provenance=buf["provenance"], text=text,
        applies_when=join_lines(when_lines), not_when=join_lines(not_lines),
        source_marker=marker, page=buf["page"], position=buf["position"],
        source_block="\n".join(buf["block"]),
    )
    rule.sha256 = rule.compute_hash()
    return rule


def parse_library(pages: list[str], index: int) -> tuple[dict, dict, str]:
    if index >= len(pages):
        return {}, {}, ""
    lines = [l for l in pages[index].splitlines() if not FOOTER.match(l.strip())]
    text = "\n".join(lines)
    why = join_lines(_between(text, "Why it exists:", "File What it contains").splitlines())
    files = []
    for name in re.findall(r"(?m)^([A-Z_]+\.md)\b", text):
        files.append(name)
    when = join_lines(_between(text, "When to use:", "Planned").splitlines())
    planned_block = "Planned" + _between(text, "Planned", "X OS ·")
    planned_lines = planned_block.splitlines()
    planned_name = planned_lines[0].replace("Planned", "").strip()
    planned = {"name": planned_name, "note": join_lines(planned_lines[1:])}
    footer = join_lines(("X OS ·" + _between(text, "X OS ·", "")).splitlines())
    entries = []
    for k, name in enumerate(files):
        nxt = files[k + 1] if k + 1 < len(files) else "When to use:"
        entries.append({"file": name, "row": join_lines((name + _between(text, name, nxt)).splitlines())})
    return ({"why": "Why it exists: " + why, "when_to_use": "When to use: " + when,
             "entries": entries, "executable": False}, planned, footer)


# ---------------------------------------------------------------------------
# hierarchy → tiers
# ---------------------------------------------------------------------------

def assign_tiers(layers: list[SourceLayer], hierarchy: list[dict]) -> list[str]:
    """Tier = rank in the conflict hierarchy. Rank 1 is reserved for guardrails."""
    warnings = []
    for layer in layers:
        for item in hierarchy:
            if layer.code in item["layers"]:
                layer.tier = item["rank"]
                owner = item["layers"][0] == layer.code
                layer.tier_basis = (f"hierarchy rank {item['rank']}: {item['raw']}" if owner else
                                    f"hierarchy rank {item['rank']} (listed as input to "
                                    f"{item['layers'][0]}): {item['raw']}")
                break
        if layer.tier is None:
            warnings.append(f"layer {layer.code} does not appear in the conflict hierarchy")
    return warnings


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def parse_rules_pack(pages: list[str]) -> SourceFramework:
    ov = parse_overview(pages[0])
    layers, rules, lib_idx = parse_rule_pages(pages)
    library, planned, footer = parse_library(pages, lib_idx)
    warnings = assign_tiers(layers, ov["hierarchy"])

    for layer in layers:
        q = ov["layer_questions"].get(layer.code)
        if q and q[1] != layer.question:
            warnings.append(f"{layer.code}: overview question {q[1]!r} differs from section {layer.question!r}")
        n = sum(1 for r in rules if r.layer == layer.code)
        if n != layer.declared_rule_count:
            warnings.append(f"{layer.code}: section declares {layer.declared_rule_count} rules, parsed {n}")
    ids = [r.rule_id for r in rules]
    dupes = {x for x in ids if ids.count(x) > 1}
    if dupes:
        warnings.append(f"duplicate rule ids: {sorted(dupes)}")
    if ov["declared_total"] != len(rules):
        warnings.append(f"document declares {ov['declared_total']} rules, parsed {len(rules)}")
    by_id = {r.rule_id: r for r in rules}
    for rid in ov["always_on"]:
        if rid not in by_id:
            warnings.append(f"always-on rule {rid} not found among parsed rules")
        elif by_id[rid].source_marker is None:
            warnings.append(f"always-on rule {rid} has no 'Always on' marker in its row")
    for r in rules:
        if r.source_marker and r.rule_id not in ov["always_on"]:
            warnings.append(f"{r.rule_id} carries marker {r.source_marker!r} but is not in the always-on list")

    return SourceFramework(
        title=ov["title"], subtitle=ov["subtitle"], framework_name=ov["framework_name"],
        version=ov["version"], preamble=ov["preamble"], sequence_text=ov["sequence_text"],
        stages=ov["stages"], hierarchy=ov["hierarchy"], hierarchy_note=ov["hierarchy_note"],
        always_on=ov["always_on"], hard_limits=ov["hard_limits"],
        hard_limit_note=ov["hard_limit_note"], legend=ov["legend"], layers=layers, rules=rules,
        declared_total=ov["declared_total"], library=library, planned=planned,
        footer_note=footer, warnings=warnings,
    )


def parse_pdf(pdf_path: str | Path) -> SourceFramework:
    return parse_rules_pack(extract_pages(pdf_path))
