"""Framework import facility (PDF, DOCX, TXT, JSON, CSV).

Imported content is untrusted data. It is parsed, never executed; source wording is kept as extracted;
nothing becomes active: every imported rule lands inactive in a new draft version, with a report,
and requires review and publication by an administrator.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from ..models import IntellectImport, IntellectVersion
from . import frameworks as fw_svc
from .source_parser import RULE_ID, SourceParseError, join_lines, normalise, parse_rules_pack

ALLOWED = {"pdf", "docx", "txt", "json", "csv"}
MAX_BYTES = 10 * 1024 * 1024
GENERIC_RULE = re.compile(r"^\s*([A-Z]{2,4}-\d{2})\s*[:.\-–—)]?\s*(.*)$")


class ImportRejected(ValueError):
    pass


def extract_text(filename: str, raw: bytes) -> tuple[str, str]:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED:
        raise ImportRejected(f"unsupported file type .{ext}; allowed: {', '.join(sorted(ALLOWED))}")
    if len(raw) > MAX_BYTES:
        raise ImportRejected("file exceeds the 10 MB import limit")
    if ext == "pdf":
        if not raw.startswith(b"%PDF"):
            raise ImportRejected("file does not look like a PDF")
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        pages = [normalise(p.extract_text() or "") for p in reader.pages]
        return ext, "\n\n=====PAGE=====\n".join(pages)
    if ext == "docx":
        if not raw.startswith(b"PK"):
            raise ImportRejected("file does not look like a DOCX document")
        import docx
        d = docx.Document(io.BytesIO(raw))
        return ext, "\n".join(p.text for p in d.paragraphs)
    try:
        return ext, normalise(raw.decode("utf-8-sig"))
    except UnicodeDecodeError as e:
        raise ImportRejected("text file is not valid UTF-8") from e


def _rule(code, layer, text, when="", not_when="", priority=None, provenance="imported", source=""):
    return {"rule_id": code.strip().upper(), "layer": (layer or code.split("-")[0]).strip().upper(),
            "text": text.strip(), "applies_when": (when or "").strip(), "not_when": (not_when or "").strip(),
            "priority": priority, "provenance": provenance or "imported", "source_excerpt": source[:600]}


def parse_structured(ext: str, text: str) -> tuple[list[dict], list[dict], list[str]]:
    """Returns (layers, rules, notes)."""
    notes: list[str] = []
    if ext == "json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ImportRejected(f"invalid JSON: {e}") from e
        layers = [{"code": str(l.get("code", "")).upper(), "name": l.get("name", ""),
                   "question": l.get("question", ""), "description": l.get("description", ""),
                   "tier": l.get("tier")} for l in data.get("layers", [])]
        rules = [_rule(r.get("rule_id") or r.get("id", ""), r.get("layer"), r.get("text", ""),
                       r.get("applies_when", ""), r.get("not_when", ""), r.get("priority"), r.get("provenance"))
                 for r in data.get("rules", [])]
        return layers, rules, notes
    if ext == "csv":
        reader = csv.DictReader(io.StringIO(text))
        need = {"rule_id", "text"}
        if not need <= set(reader.fieldnames or []):
            raise ImportRejected("CSV needs at least columns rule_id,text (optional: layer,applies_when,not_when,"
                                 "priority,provenance)")
        rules = [_rule(row["rule_id"], row.get("layer"), row["text"], row.get("applies_when", ""),
                       row.get("not_when", ""), row.get("priority"), row.get("provenance")) for row in reader]
        return [], rules, notes
    if ext == "pdf" and "=====PAGE=====" in text:
        try:
            pack = parse_rules_pack(text.split("\n\n=====PAGE=====\n"))
            if pack.rules:
                notes.append(f"Recognised X Layers rules-pack format: {pack.title}")
                notes += [f"parser warning: {w}" for w in pack.warnings]
                layers = [{"code": l.code, "name": l.name, "question": l.question, "description": l.description,
                           "tier": l.tier} for l in pack.layers]
                rules = [_rule(r.rule_id, r.layer, r.text, r.applies_when, r.not_when, r.priority, r.provenance,
                               r.source_block) for r in pack.rules]
                return layers, rules, notes
        except SourceParseError as e:
            notes.append(f"not in X Layers rules-pack format ({e}); using generic extraction")
    return [], _generic(text), notes


def _generic(text: str) -> list[dict]:
    rules, cur = [], None
    for line in text.replace("=====PAGE=====", "").splitlines():
        m = GENERIC_RULE.match(line)
        if m and RULE_ID.match(m.group(1)):
            if cur:
                rules.append(cur)
            cur = {"code": m.group(1), "lines": [m.group(2)] if m.group(2) else [], "raw": [line]}
        elif cur is not None:
            cur["lines"].append(line)
            cur["raw"].append(line)
    if cur:
        rules.append(cur)
    out = []
    for r in rules:
        body = join_lines(r["lines"])
        prio = re.search(r"\bP([1-4])\b", body)
        when = re.search(r"\bWhen:\s*(.*?)(?=\bNot when:|$)", body, re.S)
        notw = re.search(r"\bNot when:\s*(.*)$", body, re.S)
        core = re.split(r"\bWhen:", body)[0]
        core = re.sub(r"^\s*P[1-4]\s*", "", core)
        out.append(_rule(r["code"], None, core, when.group(1) if when else "", notw.group(1) if notw else "",
                         int(prio.group(1)) if prio else None, "imported", "\n".join(r["raw"])))
    return out


def _norm(s: str) -> str:
    return re.sub(r"\W+", " ", s.lower()).strip()


def build_report(version: IntellectVersion, layers: list[dict], rules: list[dict], notes: list[str]) -> dict:
    existing = {r.rule_code: r for r in version.rules}
    existing_layers = {l.code: l for l in version.layers}
    protected = {r.rule_code for r in version.rules if r.is_protected}
    duplicates, mappings, conflicts, tests, source_changes, problems = [], [], [], [], [], []
    for r in rules:
        if not r["rule_id"] or not r["text"]:
            problems.append(f"skipped entry without id or text: {r.get('source_excerpt', '')[:80]}")
            continue
        best = max(((SequenceMatcher(None, _norm(r["text"]), _norm(e.text)).ratio(), e.rule_code)
                    for e in version.rules), default=(0.0, ""))
        if best[0] >= 0.85:
            duplicates.append({"rule": r["rule_id"], "similar_to": best[1], "similarity": round(best[0], 3)})
        if r["rule_id"] in existing:
            e = existing[r["rule_id"]]
            if e.origin == "source":
                if (e.text, e.applies_when, e.not_when) != (r["text"], r["applies_when"], r["not_when"]):
                    source_changes.append(r["rule_id"])
                conflicts.append({"rule": r["rule_id"], "type": "id_collision_with_source_rule",
                                  "detail": "Source rules are not changed by imports; the imported rule will be "
                                            "renamed or rejected at review."})
            else:
                conflicts.append({"rule": r["rule_id"], "type": "id_collision", "detail": "id already exists"})
        refs = set(re.findall(r"\b[A-Z]{2,4}-\d{2}\b", " ".join([r["text"], r["not_when"]]))) & protected
        if refs and re.search(r"\b(ignore|override|disable|suspend|regardless of)\b", r["text"], re.I):
            conflicts.append({"rule": r["rule_id"], "type": "targets_protected_rule",
                              "detail": f"text refers to protected {sorted(refs)} with overriding language; "
                                        "protected rules cannot be overridden"})
        layer = r["layer"]
        mappings.append({"rule": r["rule_id"], "layer": layer,
                         "mapping": "existing layer" if layer in existing_layers else
                         ("new layer in import" if any(l["code"] == layer for l in layers) else
                          "new layer required (will be created as custom, tier to confirm)")})
        if r["applies_when"]:
            tests.append({"name": f"{r['rule_id']} applies", "prompt": f"[write a prompt matching] {r['applies_when']}",
                          "expected": {"must_apply": [r["rule_id"]]}})
        if r["not_when"]:
            tests.append({"name": f"{r['rule_id']} excluded", "prompt": f"[write a prompt matching] {r['not_when']}",
                          "expected": {"must_not_apply": [r["rule_id"]]}})
        if r["priority"] is None:
            problems.append(f"{r['rule_id']}: no priority found; P3 proposed for review")
        if not r["applies_when"]:
            problems.append(f"{r['rule_id']}: no 'Applies when' condition extracted; add one at review")
    return {"notes": notes, "extracted_layers": len(layers), "extracted_rules": len(rules),
            "duplicates": duplicates, "layer_mappings": mappings, "conflicts": conflicts,
            "suggested_tests": tests, "source_rule_changes_detected": source_changes, "problems": problems,
            "activation": "All imported rules are inactive until reviewed and published."}


def import_file(db: Session, *, framework, filename: str, raw: bytes, user_id: str | None) -> IntellectImport:
    sha = hashlib.sha256(raw).hexdigest()
    rec = IntellectImport(framework_id=framework.id, filename=filename[:255],
                          file_format=filename.rsplit(".", 1)[-1].lower()[:8], file_sha256=sha, created_by=user_id)
    db.add(rec)
    try:
        ext, text = extract_text(filename, raw)
        layers, rules, notes = parse_structured(ext, text)
        base = db.get(IntellectVersion, framework.active_version_id)
        report = build_report(base, layers, rules, notes)
        if not rules:
            rec.status, rec.report = "failed", {**report, "error": "no rules could be identified in the document"}
            db.flush()
            return rec
        draft = fw_svc.create_draft(db, base, f"import-{sha[:8]}", user_id,
                                    notes=f"Draft created from import of {filename}")
        existing_layers = {l.code: l for l in draft.layers}
        added, skipped = [], []
        for spec in layers:
            if spec["code"] and spec["code"] not in existing_layers:
                tier = spec.get("tier") if isinstance(spec.get("tier"), int) and 2 <= spec["tier"] <= 6 else 6
                existing_layers[spec["code"]] = fw_svc.add_layer(
                    db, draft, code=spec["code"], name=spec["name"] or spec["code"], question=spec["question"],
                    description=spec["description"], tier=tier, insert_after_position=None)
                existing_layers[spec["code"]].origin = "imported"
        codes = {r.rule_code for r in draft.rules}
        for r in rules:
            if not r["rule_id"] or not r["text"] or r["rule_id"] in codes:
                skipped.append(r["rule_id"])
                continue
            layer = existing_layers.get(r["layer"])
            if layer is None:
                layer = fw_svc.add_layer(db, draft, code=r["layer"], name=f"{r['layer']} (imported)", question="",
                                         description="Created by import; review name, question and tier.", tier=6,
                                         insert_after_position=None)
                layer.origin = "imported"
                existing_layers[r["layer"]] = layer
            fw_svc.add_rule(db, draft, layer, rule_code=r["rule_id"], text=r["text"],
                            applies_when=r["applies_when"], not_when=r["not_when"],
                            priority=int(r["priority"]) if r["priority"] else 3, provenance=r["provenance"][:16],
                            is_active=False, user_id=user_id, origin="imported")
            codes.add(r["rule_id"])
            added.append(r["rule_id"])
        report["added_to_draft"] = added
        report["skipped"] = skipped
        report["draft_version"] = draft.label
        rec.status, rec.report, rec.draft_version_id = "draft", report, draft.id
    except ImportRejected as e:
        rec.status, rec.report = "failed", {"error": str(e)}
    db.flush()
    return rec
