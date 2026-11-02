"""Command-line interface.

    qos solve "pick the 4 best assets from these returns" --data assets.json
    qos explain "find the shortest route between my 8 depots" --data stops.json
    qos plan "..." --data d.json --allow-hardware --budget 25
    qos backends
    qos templates
    qos demo

Deliberately argparse-only: the CLI must work the instant numpy is installed,
with no click/typer/rich dependency, because the whole point of the local
provider is that the platform runs out of the box.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .models import Policy


def _load_data(path: str | None, inline: str | None) -> dict[str, Any] | None:
    if inline:
        try:
            return json.loads(inline)
        except json.JSONDecodeError as e:
            _die(f"--json is not valid JSON: {e}")
    if not path:
        return None
    if not os.path.exists(path):
        _die(f"data file not found: {path}")
    with open(path, encoding="utf-8") as fh:
        try:
            payload = json.load(fh)
        except json.JSONDecodeError as e:
            _die(f"{path} is not valid JSON: {e}")
    if not isinstance(payload, dict):
        _die(f"{path} must contain a JSON object mapping field names to values")
    return payload


def _die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(2)


def _policy(args: argparse.Namespace) -> Policy:
    return Policy(
        max_cost_usd=float(getattr(args, "budget", 0.0) or 0.0),
        max_wait_s=float(getattr(args, "max_wait", 300.0)),
        priority=getattr(args, "priority", "balanced"),
        allow_vendors=tuple(getattr(args, "vendor", None) or ()),
        deny_vendors=tuple(getattr(args, "deny_vendor", None) or ()),
        allow_hardware=bool(getattr(args, "allow_hardware", False)),
        require_classical_baseline=not getattr(args, "no_baseline", False),
        seed=getattr(args, "seed", None),
        force_backend=getattr(args, "backend", None),
        force_algorithm=getattr(args, "algorithm", None),
    )


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def cmd_solve(args: argparse.Namespace) -> int:
    from .interpret.decoder import format_answer
    from .runtime.orchestrator import MissingProblemData, solve

    data = _load_data(args.data, args.json)
    try:
        sol = solve(
            args.goal, data,
            policy=_policy(args),
            use_llm="never" if args.no_llm else "auto",
            dry_run=False,
        )
    except MissingProblemData as e:
        print(str(e))
        print("\nSupply the missing fields with --data <file.json> or --json '{...}'.")
        print("Run 'qos templates' to see the exact shape each problem type expects.")
        return 3

    print("=" * 74)
    print(f"GOAL: {sol.goal}")
    print("=" * 74)
    print()
    print("ANSWER")
    print(format_answer(sol))
    print()
    print("ASSESSMENT")
    print(f"  objective      {sol.objective_value:,.6g}" if sol.objective_value is not None
          else "  objective      n/a")
    print(f"  feasible       {sol.feasible}")
    if sol.violations:
        for v in sol.violations:
            print(f"                 ! {v}")
    print(f"  confidence     {sol.confidence:.2f}")
    print(f"  vs classical   {sol.quantum_advantage}"
          + (f" (baseline {sol.baseline_value:,.6g})" if sol.baseline_value is not None else ""))
    if sol.raw:
        print(f"  ran on         {sol.raw.backend_id} via {sol.raw.algorithm}")
        print(f"  cost           ${sol.raw.cost_usd:,.4f}")
        print(f"  wall time      {sol.raw.wall_time_s:.2f}s")
    print()
    print("SUMMARY")
    for line in _wrap(sol.summary, 70):
        print(f"  {line}")
    if args.verbose:
        print()
        print("TRACE")
        for t in sol.trace:
            print(f"  - {t}")
    if args.out:
        _write_json(args.out, sol)
        print(f"\nfull result written to {args.out}")
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    from .runtime.orchestrator import explain

    data = _load_data(args.data, args.json)
    print(explain(
        args.goal, data,
        policy=_policy(args),
        use_llm="never" if args.no_llm else "auto",
    ))
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    from .runtime.orchestrator import MissingProblemData, solve

    data = _load_data(args.data, args.json)
    try:
        sol = solve(
            args.goal, data,
            policy=_policy(args),
            use_llm="never" if args.no_llm else "auto",
            dry_run=True,
        )
    except MissingProblemData as e:
        print(str(e))
        return 3
    print(sol.summary)
    print()
    for k, v in sol.answer.items():
        print(f"  {k:22s} {v}")
    return 0


def cmd_backends(args: argparse.Namespace) -> int:
    from .providers.registry import Registry

    reg = Registry()
    if args.refresh:
        reg.refresh()
    print(reg.report())
    usable = reg.usable()
    print()
    print(f"{len(usable)} of {len(reg.capabilities())} backends are usable right now.")
    if len(usable) <= 4:
        print()
        print("To unlock quantum hardware, install a provider SDK and set its credentials:")
        print("  pip install 'quantum-os[ibm]'    + QISKIT_IBM_TOKEN")
        print("  pip install 'quantum-os[aws]'    + AWS credentials (IAM)")
        print("  pip install 'quantum-os[azure]'  + AZURE_QUANTUM_WORKSPACE_RESOURCE_ID")
        print("  pip install 'quantum-os[dwave]'  + DWAVE_API_TOKEN")
        print("  pip install 'quantum-os[google]' + GOOGLE_CLOUD_PROJECT")
    return 0


def cmd_templates(args: argparse.Namespace) -> int:
    from .formulations.library import TEMPLATES
    from .intent.patterns import PATTERNS

    by_template = {p.template: p for p in PATTERNS if p.template}
    for name, t in sorted(TEMPLATES.items()):
        print(f"{name}")
        print(f"  {t.description}")
        p = by_template.get(name)
        if p:
            fields = ", ".join(p.requires)
            print(f"  required data: {fields}")
            for k, help_text in p.field_help.items():
                print(f"    {k:12s} {help_text}")
            print(f"  triggers on e.g.: {', '.join(p.strong[:4])}")
        print()
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """Run a built-in problem end to end, so a new install proves itself."""
    from .interpret.decoder import format_answer
    from .runtime.orchestrator import solve

    demos = {
        "portfolio": (
            "Pick exactly 3 assets maximizing risk-adjusted return",
            {
                "returns": [0.12, 0.10, 0.09, 0.07, 0.05, 0.14],
                "covariance": [
                    [0.040, 0.012, 0.008, 0.002, 0.001, 0.020],
                    [0.012, 0.035, 0.010, 0.003, 0.001, 0.015],
                    [0.008, 0.010, 0.030, 0.004, 0.002, 0.009],
                    [0.002, 0.003, 0.004, 0.015, 0.001, 0.003],
                    [0.001, 0.001, 0.002, 0.001, 0.010, 0.002],
                    [0.020, 0.015, 0.009, 0.003, 0.002, 0.060],
                ],
                "names": ["TECH", "FIN", "HEALTH", "UTIL", "BOND", "CRYPTO"],
                "budget": 3,
                "risk_aversion": 2.0,
            },
        ),
        "route": (
            "Find the shortest round trip visiting all six depots",
            {
                "distances": [
                    [0, 14, 22, 9, 30, 18],
                    [14, 0, 11, 20, 25, 8],
                    [22, 11, 0, 17, 12, 15],
                    [9, 20, 17, 0, 28, 24],
                    [30, 25, 12, 28, 0, 19],
                    [18, 8, 15, 24, 19, 0],
                ],
                "names": ["HQ", "North", "East", "South", "Far", "West"],
            },
        ),
        "maxcut": (
            "Split this network into two groups maximizing connections between them",
            {"n": 12, "edges": [[i, (i + 1) % 12] for i in range(12)]
                               + [[i, (i + 5) % 12] for i in range(12)]},
        ),
        "shifts": (
            "Assign each of these 4 engineers exactly one on-call shift at minimum cost",
            {
                "costs": [[4, 2, 8, 6], [4, 3, 7, 5], [3, 1, 6, 9], [7, 5, 2, 4]],
                "agents": ["Ada", "Blake", "Cruz", "Dev"],
                "tasks": ["Mon", "Tue", "Wed", "Thu"],
            },
        ),
    }
    which = [args.which] if args.which else list(demos)
    for name in which:
        if name not in demos:
            _die(f"unknown demo {name!r}; choose from {', '.join(demos)}")
        goal, data = demos[name]
        print("=" * 74)
        print(f"DEMO: {name}  --  {goal}")
        print("=" * 74)
        sol = solve(goal, data, policy=_policy(args), use_llm="never")
        print(format_answer(sol))
        print()
        for line in _wrap(sol.summary, 70):
            print(f"  {line}")
        print()
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError:
        _die("the HTTP API needs fastapi and uvicorn: pip install 'quantum-os[api]'")
    from .api.server import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")
    return 0


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


def _write_json(path: str, sol) -> None:
    payload = {
        "goal": sol.goal,
        "answer": sol.answer,
        "summary": sol.summary,
        "objective_value": sol.objective_value,
        "feasible": sol.feasible,
        "violations": sol.violations,
        "confidence": sol.confidence,
        "baseline_value": sol.baseline_value,
        "quantum_advantage": sol.quantum_advantage,
        "trace": sol.trace,
    }
    if sol.raw:
        payload["execution"] = {
            "backend": sol.raw.backend_id,
            "algorithm": sol.raw.algorithm,
            "shots": sol.raw.shots,
            "cost_usd": sol.raw.cost_usd,
            "wall_time_s": sol.raw.wall_time_s,
            "meta": {k: v for k, v in sol.raw.meta.items() if _jsonable(v)},
        }
    if sol.plan:
        payload["plan"] = {
            "chosen": f"{sol.plan.primary.backend.id}:{sol.plan.primary.algorithm}",
            "reason": sol.plan.primary.reason,
            "considered": [
                {"candidate": c, "score": s, "reason": r} for c, s, r in sol.plan.considered
            ],
            "rejected": [{"candidate": c, "why": w} for c, w in sol.plan.rejected],
        }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)


def _jsonable(v: Any) -> bool:
    try:
        json.dumps(v)
        return True
    except (TypeError, ValueError):
        return False


# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="qos",
        description="Quantum OS -- state a goal, the platform picks the resources and solves it.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  qos demo
  qos solve "split these numbers into two equal groups: 8 5 4 3 3 2"
  qos solve "pick 3 assets with the best risk-adjusted return" --data assets.json
  qos explain "route my van through these 9 stops" --data stops.json
  qos plan "..." --data big.json --allow-hardware --budget 50
  qos backends --refresh
""",
    )
    sub = p.add_subparsers(dest="command", required=True)

    def add_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--data", "-d", help="JSON file with the problem data")
        sp.add_argument("--json", "-j", help="problem data inline as a JSON string")
        sp.add_argument("--budget", type=float, default=0.0,
                        help="maximum spend in USD (default 0 = free resources only)")
        sp.add_argument("--max-wait", type=float, default=300.0,
                        help="maximum acceptable wall time in seconds")
        sp.add_argument("--priority", choices=["balanced", "accuracy", "cheap", "fast"],
                        default="balanced", help="what to optimize the resource choice for")
        sp.add_argument("--vendor", action="append",
                        help="restrict to this vendor (repeatable)")
        sp.add_argument("--deny-vendor", action="append",
                        help="exclude this vendor (repeatable)")
        sp.add_argument("--allow-hardware", action="store_true",
                        help="permit paid quantum hardware (off by default)")
        sp.add_argument("--no-baseline", action="store_true",
                        help="skip the classical baseline comparison")
        sp.add_argument("--no-llm", action="store_true",
                        help="use only pattern matching to read the goal")
        sp.add_argument("--seed", type=int, help="random seed for reproducible runs")
        sp.add_argument("--backend", help="pin execution to this backend id (see 'qos backends')")
        sp.add_argument("--algorithm", help="pin the algorithm, e.g. qaoa, vqe, grover, tabu")

    sp = sub.add_parser("solve", help="solve a goal end to end")
    sp.add_argument("goal")
    add_common(sp)
    sp.add_argument("--verbose", "-v", action="store_true", help="print the decision trace")
    sp.add_argument("--out", "-o", help="write the full result as JSON to this path")
    sp.set_defaults(func=cmd_solve)

    sp = sub.add_parser("explain", help="show how the goal is read and where it would run")
    sp.add_argument("goal")
    add_common(sp)
    sp.set_defaults(func=cmd_explain)

    sp = sub.add_parser("plan", help="estimate cost and runtime without executing")
    sp.add_argument("goal")
    add_common(sp)
    sp.set_defaults(func=cmd_plan)

    sp = sub.add_parser("backends", help="list every known backend and its status")
    sp.add_argument("--refresh", action="store_true",
                    help="query live device status from credentialed providers")
    sp.set_defaults(func=cmd_backends)

    sp = sub.add_parser("templates", help="list supported problem types and their data shapes")
    sp.set_defaults(func=cmd_templates)

    sp = sub.add_parser("demo", help="run built-in example problems end to end")
    sp.add_argument("which", nargs="?", help="portfolio | route | maxcut | shifts")
    sp.add_argument("--seed", type=int, default=7)
    sp.set_defaults(func=cmd_demo)

    sp = sub.add_parser("serve", help="start the HTTP API")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8080)
    sp.set_defaults(func=cmd_serve)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        if os.environ.get("QOS_DEBUG"):
            raise
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
