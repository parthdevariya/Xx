"""Intent layer: natural-language goal -> ProblemSpec.

Three stages, cheapest first:

1. **Pattern match** (always) -- identify the template from an explicit
   vocabulary. Free, instant, deterministic, auditable.
2. **Numeric extraction** (always) -- pull lists, matrices and limits out of
   the goal text and merge with any structured data the caller supplied.
3. **LLM parse** (optional) -- only when the first two leave the goal
   unclassified or data missing, and only if a model is configured.

The rule the whole layer obeys: **never invent problem data.** If the goal says
"find the best delivery route" and supplies no distances, the platform reports
what it needs. Silently generating a random distance matrix would produce a
confident, meaningless answer, which is the worst possible failure mode for a
system whose output a user cannot easily check.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import numpy as np

from ..formulations.library import TEMPLATES
from ..models import Objective, ProblemClass, ProblemSpec
from .patterns import GENERIC_OPTIMIZATION, PATTERNS, best_patterns

NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


# --------------------------------------------------------------------------
# Numeric extraction
# --------------------------------------------------------------------------

def extract_number_list(text: str) -> list[float]:
    """Pull an explicit list of numbers out of the goal.

    Looks for bracketed or colon-introduced runs of 3+ numbers, which is what
    distinguishes "split 8, 5, 4, 3 into two groups" (data) from
    "split into 2 groups" (a parameter).
    """
    for m in re.finditer(r"[\[\(]([^\]\)]*)[\]\)]", text):
        nums = NUMBER_RE.findall(m.group(1))
        if len(nums) >= 3:
            return [float(x) for x in nums]
    # Colon- or "these"-introduced run.
    for m in re.finditer(r"(?::|these|following|numbers?|values?|list)\s*([-\d.,\s]+)", text, re.I):
        nums = NUMBER_RE.findall(m.group(1))
        if len(nums) >= 3:
            return [float(x) for x in nums]
    return []


def extract_labeled(text: str, *keys: str) -> float | None:
    """Find "capacity of 50", "budget: 10", "k = 3" style values."""
    for key in keys:
        m = re.search(
            rf"{key}\s*(?:of|is|=|:|at most|no more than|under|up to)?\s*(-?\d+(?:\.\d+)?)",
            text, re.I,
        )
        if m:
            return float(m.group(1))
    return None


def extract_count(text: str, *nouns: str) -> int | None:
    """Find "pick 3 assets", "exactly 5 features", "choose 2 of"."""
    for noun in nouns:
        m = re.search(rf"(?:pick|choose|select|keep|exactly|hold|use)\s+(\d+)\s+\w*\s*{noun}",
                      text, re.I)
        if m:
            return int(m.group(1))
        m = re.search(rf"{noun}\D{{0,12}}?(?:exactly\s+)?(\d+)", text, re.I)
        if m:
            return int(m.group(1))
    m = re.search(r"\b(?:pick|choose|select|keep|hold)\s+(?:exactly\s+)?(\d+)\b", text, re.I)
    return int(m.group(1)) if m else None


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------

def parse(
    goal: str,
    data: dict[str, Any] | None = None,
    *,
    use_llm: str = "auto",
    model: str | None = None,
) -> ProblemSpec:
    """Read a goal into a ProblemSpec.

    ``data`` is structured problem data supplied by the caller (from a file,
    an API body, or a notebook). Caller-supplied data always wins over
    anything extracted from the text.

    ``use_llm``: "auto" (only if needed and configured), "never", "always".
    """
    supplied = dict(data or {})
    text = goal.strip()

    spec = _heuristic_parse(text, supplied)

    needs_help = (
        spec.problem_class is ProblemClass.UNKNOWN
        or spec.missing_data
        or spec.confidence < 0.55
    )
    if use_llm == "always" or (use_llm == "auto" and needs_help):
        llm_spec = _llm_parse(text, supplied, model=model)
        if llm_spec is not None:
            # Trust the LLM only when it did better: classified where the
            # heuristic could not, or supplied data the heuristic lacked.
            better = (
                (spec.problem_class is ProblemClass.UNKNOWN
                 and llm_spec.problem_class is not ProblemClass.UNKNOWN)
                or (spec.missing_data and not llm_spec.missing_data)
                or llm_spec.confidence > spec.confidence + 0.1
            )
            if better:
                llm_spec.assumptions.extend(spec.assumptions)
                return llm_spec
    return spec


def _heuristic_parse(text: str, supplied: dict[str, Any]) -> ProblemSpec:
    ranked = best_patterns(text)

    # Structured data can identify the template on its own, which matters when
    # the goal is terse ("solve this") but the payload is unambiguous.
    data_template = _template_from_data(supplied)

    if not ranked and data_template is None:
        if any(w in text.lower() for w in GENERIC_OPTIMIZATION) and "Q" in supplied:
            return _generic_qubo_spec(text, supplied)
        return ProblemSpec(
            raw_goal=text,
            problem_class=ProblemClass.UNKNOWN,
            objective=Objective.MINIMIZE,
            confidence=0.0,
            rationale="no known problem pattern matched this goal",
            missing_data=["unclassified goal"],
        )

    if ranked:
        pattern, score = ranked[0]
        # Data that clearly indicates a different template overrides a weak
        # keyword match -- payloads are more reliable than prose.
        if data_template and data_template != pattern.template and score < 0.62:
            pattern = next(p for p in PATTERNS if p.template == data_template)
            score = 0.80
    else:
        pattern = next(p for p in PATTERNS if p.template == data_template)
        score = 0.80

    merged, assumptions = _collect_data(text, supplied, pattern)
    missing = [k for k in pattern.requires if k not in merged or merged[k] is None]

    alts = [f"{p.template or p.problem_class.value} ({s:.2f})" for p, s in ranked[1:3]]
    rationale = f"matched '{pattern.template or pattern.problem_class.value}': {pattern.reads_as}"
    if alts:
        rationale += f"; runners-up: {', '.join(alts)}"

    return ProblemSpec(
        raw_goal=text,
        problem_class=pattern.problem_class,
        objective=pattern.objective,
        template=pattern.template,
        data=merged,
        confidence=round(min(0.95, score if not missing else score * 0.6), 3),
        rationale=rationale,
        assumptions=assumptions,
        missing_data=[f"{k}: {pattern.field_help.get(k, 'required')}" for k in missing],
    )


def _template_from_data(d: dict) -> str | None:
    """Infer the template from which data keys are present."""
    if not d:
        return None
    if "distances" in d:
        return "tsp"
    if "values" in d and "weights" in d and "capacity" in d:
        return "knapsack"
    if "returns" in d:
        return "portfolio"
    if "costs" in d:
        return "assignment"
    if "relevance" in d:
        return "feature_selection"
    if "sizes" in d and "capacity" in d:
        return "bin_packing"
    if "numbers" in d:
        return "number_partition"
    if "edges" in d and "k" in d:
        return "graph_coloring"
    return None


def _collect_data(
    text: str, supplied: dict[str, Any], pattern
) -> tuple[dict[str, Any], list[str]]:
    """Merge supplied data with values extracted from the text."""
    merged: dict[str, Any] = dict(supplied)
    assumptions: list[str] = []
    t = pattern.template

    if t == "number_partition" and "numbers" not in merged:
        nums = extract_number_list(text)
        if nums:
            merged["numbers"] = nums
            assumptions.append(f"read {len(nums)} numbers from the goal text")

    if t == "knapsack":
        if "capacity" not in merged:
            cap = extract_labeled(text, "capacity", "budget", "limit", "weight limit", "at most")
            if cap is not None:
                merged["capacity"] = cap
                assumptions.append(f"read capacity = {cap:g} from the goal text")

    if t == "bin_packing":
        if "capacity" not in merged:
            cap = extract_labeled(text, "capacity", "limit", "per bin", "each bin")
            if cap is not None:
                merged["capacity"] = cap
        if "bins" not in merged:
            nb = extract_count(text, "bins", "containers", "trucks", "servers", "groups")
            if nb:
                merged["bins"] = nb
                assumptions.append(f"using {nb} bins as stated in the goal")

    if t == "portfolio" and "budget" not in merged:
        k = extract_count(text, "assets", "stocks", "positions", "holdings", "names")
        if k:
            merged["budget"] = k
            assumptions.append(f"holding exactly {k} positions")

    if t == "feature_selection" and "k" not in merged:
        k = extract_count(text, "features", "predictors", "variables", "columns")
        if k:
            merged["k"] = k
            assumptions.append(f"keeping exactly {k} features")

    if t == "graph_coloring" and "k" not in merged:
        k = extract_count(text, "colors", "colours", "labels", "timeslots", "slots", "shifts", "rooms")
        if k:
            merged["k"] = k
            assumptions.append(f"using {k} labels")
        elif "edges" in merged:
            merged["k"] = 3
            assumptions.append("no label count given; assuming 3")

    # Derive n for graph templates when only edges were given.
    if t in ("max_cut", "vertex_cover", "independent_set", "graph_coloring"):
        if "n" not in merged and "edges" in merged:
            edges = merged["edges"]
            if edges:
                merged["n"] = int(max(max(e[0], e[1]) for e in edges)) + 1
                assumptions.append(f"inferred {merged['n']} nodes from the edge list")

    if t == "tsp" and "distances" in merged:
        merged["n"] = int(np.asarray(merged["distances"]).shape[0])

    # Record problem size for templates that need it.
    if t and t in TEMPLATES and "n" not in merged:
        for key in ("values", "numbers", "returns", "relevance", "sizes"):
            if key in merged:
                merged["n"] = len(merged[key])
                break

    return merged, assumptions


def _generic_qubo_spec(text: str, supplied: dict) -> ProblemSpec:
    Q = np.asarray(supplied["Q"], dtype=float)
    return ProblemSpec(
        raw_goal=text,
        problem_class=ProblemClass.QUBO,
        objective=Objective.MINIMIZE,
        template=None,
        data={"Q": Q, "n": int(Q.shape[0]), "offset": float(supplied.get("offset", 0.0))},
        confidence=0.9,
        rationale="raw QUBO matrix supplied; solving it directly",
    )


# --------------------------------------------------------------------------
# LLM-assisted parsing
# --------------------------------------------------------------------------

LLM_SYSTEM = """You translate a user's plain-language computational goal into a \
structured problem specification for a quantum optimization platform.

Reply with ONE JSON object and nothing else:

{
  "problem_class": "qubo" | "ground_state" | "search" | "machine_learning" | "unknown",
  "template": one of [max_cut, tsp, knapsack, portfolio, number_partition,
                      vertex_cover, independent_set, graph_coloring, assignment,
                      feature_selection, bin_packing] or null,
  "objective": "minimize" | "maximize" | "satisfy",
  "data": { ...only values explicitly present in the user's text... },
  "missing_data": ["name: what this field is and why it is needed"],
  "confidence": 0.0-1.0,
  "rationale": "one sentence on why this template fits",
  "assumptions": ["any assumption you made"]
}

Rules, in priority order:
1. NEVER invent numeric problem data. If the user did not give the distances,
   values, weights, edges or returns, leave them out of "data" and name them in
   "missing_data". Fabricated data produces a confident wrong answer.
2. Only use a template from the list. If none fits, set template to null and
   problem_class to the best fit or "unknown".
3. Extract parameters the user DID state (capacity, how many to pick, number of
   bins/labels) into "data".
4. Data shapes: distances = square matrix; edges = [[i,j],...] or [[i,j,w],...];
   values/weights/numbers/returns/relevance/sizes = flat lists; costs = matrix
   [agent][task]; n = integer count; k/budget/bins/capacity = numbers.
"""


def _llm_parse(
    text: str, supplied: dict[str, Any], model: str | None = None
) -> ProblemSpec | None:
    """Parse with Claude, if the SDK and an API key are available.

    Returns None (rather than raising) whenever the model is unavailable or
    the reply cannot be trusted, so the heuristic result stands.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError:
        return None

    model = model or os.environ.get("QOS_LLM_MODEL", "claude-sonnet-5")
    prompt = f"User goal: {text}"
    if supplied:
        keys = ", ".join(sorted(supplied.keys()))
        prompt += f"\n\nStructured data already provided by the caller (do not repeat): {keys}"

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=1500,
            system=LLM_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    except Exception:
        return None

    payload = _extract_json(raw)
    if payload is None:
        return None

    try:
        pclass = ProblemClass(payload.get("problem_class", "unknown"))
    except ValueError:
        pclass = ProblemClass.UNKNOWN
    try:
        obj = Objective(payload.get("objective", "minimize"))
    except ValueError:
        obj = Objective.MINIMIZE

    template = payload.get("template")
    if template not in TEMPLATES:
        template = None

    merged = dict(payload.get("data") or {})
    merged.update(supplied)          # caller data always wins

    if template:
        pattern = next((p for p in PATTERNS if p.template == template), None)
        if pattern:
            merged, extra = _collect_data(text, merged, pattern)
            missing = [
                f"{k}: {pattern.field_help.get(k, 'required')}"
                for k in pattern.requires
                if k not in merged or merged[k] is None
            ]
        else:
            extra, missing = [], list(payload.get("missing_data") or [])
    else:
        extra, missing = [], list(payload.get("missing_data") or [])

    return ProblemSpec(
        raw_goal=text,
        problem_class=pclass,
        objective=obj,
        template=template,
        data=merged,
        confidence=float(payload.get("confidence", 0.6)),
        rationale=f"[llm] {payload.get('rationale', '')}",
        assumptions=list(payload.get("assumptions") or []) + extra,
        missing_data=missing,
    )


def _extract_json(raw: str) -> dict | None:
    """Pull the first JSON object out of a model reply."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.S)
    start = raw.find("{")
    if start < 0:
        return None
    depth = 0
    for i, ch in enumerate(raw[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None
