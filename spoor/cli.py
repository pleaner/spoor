"""spoor CLI — invokes Claude Code skills to collect safari lodge information.

Each subcommand builds a prompt that instructs Claude Code to run a skill, then
shells out to the `claude` binary in headless mode (`claude -p`). Skills live in
`.claude/skills/` and are discovered automatically by Claude Code.
"""

from __future__ import annotations

import argparse
import datetime
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Tools the collect skill needs: Skill to invoke it, plus the tools it uses.
# WebSearch finds review pages; Bash runs the Booking.com review scraper.
COLLECT_ALLOWED_TOOLS = "Skill,WebFetch,WebSearch,Read,Write,Bash"

# The evaluate-phase skills read raw dossiers (Read, incl. PDFs via poppler), write
# generated scripts/JSON/markdown (Write), and run the deterministic spoor modules
# and generated pricing scripts (Bash). None of them touch the network.
EVALUATE_ALLOWED_TOOLS = "Skill,Read,Write,Bash"

# Default models per the PRD's cost split: the exacting, high-leverage script
# generation runs on Opus; the lighter grounding QA runs on cheaper Sonnet.
OPUS_MODEL = "opus"
SONNET_MODEL = "claude-sonnet-4-6"


def slugify(name: str) -> str:
    """Mirror the slug rule documented in the collect skill."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _require_claude() -> str:
    path = shutil.which("claude")
    if not path:
        sys.exit(
            "error: the `claude` CLI was not found on your PATH.\n"
            "Install Claude Code and ensure `claude` is runnable: "
            "https://docs.claude.com/en/docs/claude-code"
        )
    return path


def _run_claude(
    prompt: str,
    allowed_tools: str,
    cwd: Path,
    model: "str | None" = None,
    log_path: "Path | None" = None,
) -> int:
    """Run Claude Code headlessly with the given prompt.

    Without ``log_path`` the child's output streams live to this process's
    terminal. With ``log_path`` the combined output is captured and written
    there instead — used for concurrent batch runs, where live interleaving of
    several agents' output would be unreadable.
    """
    cmd = [
        _require_claude(),
        "-p",
        prompt,
        "--allowedTools",
        allowed_tools,
    ]
    if model:
        cmd += ["--model", model]
    if log_path is None:
        return subprocess.run(cmd, cwd=str(cwd)).returncode
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.run(
            cmd, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT, text=True
        )
    return proc.returncode


def _build_collect_prompt(
    name: str,
    website: "str | None",
    rate_cards: "list[Path]",
    sources: "list[str] | None",
    no_wetu: bool,
    no_reviews: bool,
    today: str,
) -> str:
    """Build the headless prompt instructing Claude to run the collect skill."""
    lines = [
        "Use the `collect` skill to discover every bookable property in this safari",
        "lodge group and gather one raw dossier per property.",
        "",
        f"- Today's date: {today}  (use this for the Freshness policy cadence checks)",
        f"- Name: {name}",
        f"- Website: {website or 'none provided'}",
    ]
    if rate_cards:
        lines.append("- Rate cards:")
        lines.extend(f"  - {p}" for p in rate_cards)
    else:
        lines.append("- Rate cards: none provided")
    if sources:
        lines.append("- Other sources:")
        lines.extend(f"  - {s}" for s in sources)
    if no_wetu:
        lines.append("- Wetu: skip — do not cross-reference Wetu Content Central.")
    if no_reviews:
        lines.append("- Reviews: skip — do not collect TripAdvisor or Booking.com reviews.")
    return "\n".join(lines)


def _read_names_file(path: Path) -> "list[str]":
    """Read lodge group names, one per line. Blank lines and #-comments are ignored."""
    if not path.is_file():
        sys.exit(f"error: names file not found: {path}")
    names = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            names.append(line)
    if not names:
        sys.exit(f"error: no lodge names found in {path}")
    return names


def cmd_collect(args: argparse.Namespace) -> int:
    project = Path(args.dir).resolve()
    if not (project / ".claude" / "skills" / "collect").is_dir():
        sys.exit(
            f"error: no collect skill found under {project}/.claude/skills/collect\n"
            "Run spoor from the project root (the directory containing .claude/)."
        )

    today = datetime.date.today().isoformat()

    if args.names_file:
        return _collect_batch(args, project, today)

    if not args.name:
        sys.exit("error: provide a lodge group name, or --names-file with a list of names.")

    # Validate rate cards up front so failures are fast and clear.
    rate_cards = []
    for rc in args.rate_card or []:
        path = Path(rc).resolve()
        if not path.is_file():
            sys.exit(f"error: rate card not found: {path}")
        rate_cards.append(path)

    prompt = _build_collect_prompt(
        args.name, args.website, rate_cards, args.source, args.no_wetu, args.no_reviews, today
    )

    print(
        f"→ collecting '{args.name}' → data/raw/{slugify(args.name)}/ "
        f"(one file per property{', model=' + args.model if args.model else ''})\n",
        file=sys.stderr,
    )
    return _run_claude(prompt, COLLECT_ALLOWED_TOOLS, project, model=args.model)


def _collect_batch(args: argparse.Namespace, project: Path, today: str) -> int:
    """Run one collect agent per lodge name from --names-file, concurrently.

    The per-lodge inputs (--website, --rate-card, --source) don't generalise to a
    flat list of names, so they're rejected here; Claude discovers each group's
    website itself. Each agent writes to its own data/raw/<slug>/, so they're independent;
    their output is captured to data/raw/<slug>/collect.log to keep the terminal readable.
    """
    for flag, val in (("--website", args.website), ("--rate-card", args.rate_card), ("--source", args.source)):
        if val:
            sys.exit(f"error: {flag} is per-lodge and can't be combined with --names-file.")

    names = _read_names_file(Path(args.names_file).resolve())
    workers = max(1, args.concurrency)
    model = f", model={args.model}" if args.model else ""
    print(
        f"→ collecting {len(names)} lodge group(s) with up to {workers} concurrent "
        f"agent(s){model}; per-lodge output → data/raw/<slug>/collect.log\n",
        file=sys.stderr,
    )

    def run_one(name: str) -> "tuple[str, int]":
        slug = slugify(name)
        prompt = _build_collect_prompt(
            name, None, [], None, args.no_wetu, args.no_reviews, today
        )
        log_path = project / "data" / "raw" / slug / "collect.log"
        rc = _run_claude(prompt, COLLECT_ALLOWED_TOOLS, project, model=args.model, log_path=log_path)
        return name, rc

    failures = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_one, name): name for name in names}
        for fut in as_completed(futures):
            name, rc = fut.result()
            status = "✓" if rc == 0 else f"✗ (exit {rc})"
            if rc != 0:
                failures += 1
            print(f"  {status}  {name} → data/raw/{slugify(name)}/", file=sys.stderr)

    print(
        f"\n→ done: {len(names) - failures} succeeded, {failures} failed.",
        file=sys.stderr,
    )
    return 1 if failures else 0


def _require_skill(project: Path, skill: str) -> None:
    if not (project / ".claude" / "skills" / skill).is_dir():
        sys.exit(
            f"error: no {skill} skill found under {project}/.claude/skills/{skill}\n"
            "Run spoor from the project root (the directory containing .claude/)."
        )


def cmd_build_pricing_script(args: argparse.Namespace) -> int:
    """(Re)generate one property's pricing script from its raw rate card (Opus)."""
    project = Path(args.dir).resolve()
    _require_skill(project, "build-pricing-script")

    lodge = slugify(args.lodge)
    prop = slugify(args.property)
    dossier = project / "data" / "raw" / lodge / f"{prop}.md"
    if not dossier.is_file():
        sys.exit(
            f"error: no raw dossier at {dossier}\n"
            "Run `spoor collect` first, or check the lodge/property slugs."
        )

    out_dir = project / "data" / "evaluated" / lodge
    prompt = "\n".join([
        "Use the `build-pricing-script` skill to turn this property's raw rate card "
        "into a self-contained, stdlib-only Python pricing script.",
        "",
        f"- Lodge slug: {lodge}",
        f"- Property slug: {prop}",
        f"- Raw dossier (read-only): {dossier}",
        f"- Write the script to: {out_dir}/{prop}-pricing.py",
        f"- Force rebuild even if unchanged: {'yes' if args.force_rebuild else 'no'}",
        f"- Today's date: {datetime.date.today().isoformat()}",
    ])
    print(
        f"→ building pricing script for {lodge}/{prop} → "
        f"data/evaluated/{lodge}/{prop}-pricing.py (model={args.model})\n",
        file=sys.stderr,
    )
    return _run_claude(prompt, EVALUATE_ALLOWED_TOOLS, project, model=args.model)


def cmd_evaluate(args: argparse.Namespace) -> int:
    """Evaluate every property in a lodge: ensure scripts, compute ADRs, write prose (Opus)."""
    project = Path(args.dir).resolve()
    _require_skill(project, "evaluate")

    lodge = slugify(args.lodge)
    raw_dir = project / "data" / "raw" / lodge
    if not raw_dir.is_dir():
        sys.exit(
            f"error: no raw data at {raw_dir}\n"
            "Run `spoor collect` for this lodge first."
        )

    prompt = "\n".join([
        "Use the `evaluate` skill to evaluate every property in this lodge group. "
        "Read data/raw/ (never mutate it) and write to data/evaluated/.",
        "",
        f"- Lodge slug: {lodge}",
        f"- Raw input directory (read-only): {raw_dir}",
        f"- Evaluated output directory: {project / 'data' / 'evaluated' / lodge}",
        f"- FX config: {project / 'config' / 'fx.json'}",
        f"- Force pricing-script rebuild: {'yes' if args.force_rebuild else 'no'}",
        f"- Today's date: {datetime.date.today().isoformat()}",
    ])
    print(
        f"→ evaluating '{lodge}' → data/evaluated/{lodge}/ "
        f"(pricing script + ADR JSON + evaluation per property, model={args.model})\n",
        file=sys.stderr,
    )
    return _run_claude(prompt, EVALUATE_ALLOWED_TOOLS, project, model=args.model)


def cmd_assess(args: argparse.Namespace) -> int:
    """Grounding-only QA over a lodge's evaluation prose (Sonnet)."""
    project = Path(args.dir).resolve()
    _require_skill(project, "assess")

    lodge = slugify(args.lodge)
    eval_dir = project / "data" / "evaluated" / lodge
    if not eval_dir.is_dir():
        sys.exit(
            f"error: no evaluated data at {eval_dir}\n"
            "Run `spoor evaluate` for this lodge first."
        )

    prompt = "\n".join([
        "Use the `assess` skill to check the grounding of this lodge's evaluation "
        "prose: every claim in each <property>.md must trace to the raw dossier or "
        "the <property>-adr.json. Flag unsupported claims. Do NOT edit the evaluation.",
        "",
        f"- Lodge slug: {lodge}",
        f"- Evaluated directory: {eval_dir}",
        f"- Raw dossiers (read-only): {project / 'data' / 'raw' / lodge}",
        f"- Today's date: {datetime.date.today().isoformat()}",
    ])
    print(
        f"→ assessing grounding for '{lodge}' (model={args.model})\n",
        file=sys.stderr,
    )
    return _run_claude(prompt, EVALUATE_ALLOWED_TOOLS, project, model=args.model)


def cmd_categorise(args: argparse.Namespace) -> int:
    """Categorise the whole evaluated corpus into per-archetype files (Opus)."""
    project = Path(args.dir).resolve()
    _require_skill(project, "categorise")

    evaluated = project / "data" / "evaluated"
    if not evaluated.is_dir():
        sys.exit(
            f"error: no evaluated data at {evaluated}\n"
            "Run `spoor evaluate` for at least one lodge first."
        )

    prompt = "\n".join([
        "Use the `categorise` skill to invert the evaluated corpus into a per-traveller "
        "view: one markdown file per fixed category under data/categorised/, listing the "
        "properties that genuinely suit it. Read data/evaluated/ across all lodges "
        "(never mutate it). Numbers come only from `python -m spoor.categories`.",
        "",
        f"- Evaluated directory (read-only): {evaluated}",
        f"- Categorised output directory: {project / 'data' / 'categorised'}",
        f"- FX config: {project / 'config' / 'fx.json'}",
        f"- Today's date: {datetime.date.today().isoformat()}",
    ])
    print(
        "→ categorising data/evaluated/ → data/categorised/ "
        f"(one file per traveller category, model={args.model})\n",
        file=sys.stderr,
    )
    return _run_claude(prompt, EVALUATE_ALLOWED_TOOLS, project, model=args.model)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spoor",
        description="Collect and process safari lodge information via Claude Code skills.",
    )
    parser.add_argument(
        "-C",
        "--dir",
        default=".",
        help="Project directory containing .claude/ (default: current directory).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser(
        "collect",
        help="Collect raw info about a lodge group into data/raw/<lodge-slug>/<property-slug>.md",
        description=(
            "Discover every bookable property in a safari lodge group and store one "
            "raw dossier per property under data/raw/<lodge-slug>/."
        ),
    )
    collect.add_argument(
        "name",
        nargs="?",
        help="Lodge group name, e.g. 'Londolozi'. Omit when using --names-file.",
    )
    collect.add_argument(
        "--names-file",
        metavar="TXT",
        help=(
            "Path to a text file of lodge group names, one per line (blank lines and "
            "#-comments ignored). Runs one collect agent per name. Mutually exclusive "
            "with a positional name and the per-lodge flags (--website/--rate-card/--source)."
        ),
    )
    collect.add_argument(
        "--concurrency",
        type=int,
        default=3,
        metavar="N",
        help="Max agents to run at once in --names-file mode (default: 3).",
    )
    collect.add_argument("--website", help="Group's official website URL.")
    collect.add_argument(
        "--rate-card",
        action="append",
        metavar="PDF",
        help="Path to a local PDF rate card with pricing. Repeatable.",
    )
    collect.add_argument(
        "--source",
        action="append",
        metavar="URL_OR_PATH",
        help="Additional source (URL or local file). Repeatable.",
    )
    collect.add_argument(
        "--no-wetu",
        action="store_true",
        help="Skip the Wetu Content Central cross-reference (on by default).",
    )
    collect.add_argument(
        "--no-reviews",
        action="store_true",
        help="Skip TripAdvisor and Booking.com review collection (on by default).",
    )
    collect.add_argument(
        "--model",
        default="claude-sonnet-4-6",
        help=(
            "Model for Claude Code to use (default: claude-sonnet-4-6 — the cheapest "
            "model fully capable of the collection). Override with 'opus', 'haiku', or "
            "another model id."
        ),
    )
    collect.set_defaults(func=cmd_collect)

    # ── evaluate phase ───────────────────────────────────────────────────────
    build = sub.add_parser(
        "build-pricing-script",
        help="(Re)generate one property's pricing script from its raw rate card.",
        description=(
            "Turn a single property's raw rate card into a self-contained, "
            "stdlib-only Python pricing script under data/evaluated/<lodge>/. "
            "Runs on Opus — the exacting, high-leverage step."
        ),
    )
    build.add_argument("lodge", help="Lodge group name or slug, e.g. 'tanda-tula'.")
    build.add_argument("property", help="Property name or slug, e.g. 'safari-camp'.")
    build.add_argument(
        "--force-rebuild",
        action="store_true",
        help="Regenerate even if the rate card is unchanged.",
    )
    build.add_argument(
        "--model",
        default=OPUS_MODEL,
        help=f"Model for Claude Code (default: {OPUS_MODEL} — exacting codegen).",
    )
    build.set_defaults(func=cmd_build_pricing_script)

    evaluate = sub.add_parser(
        "evaluate",
        help="Evaluate every property in a lodge into data/evaluated/<lodge>/.",
        description=(
            "Generate any missing/stale pricing scripts, compute the Benchmark "
            "Safari ADR table deterministically, and write the grounded evaluation "
            "— three files per property. Reads data/raw/ read-only. Runs on Opus."
        ),
    )
    evaluate.add_argument("lodge", help="Lodge group name or slug, e.g. 'tanda-tula'.")
    evaluate.add_argument(
        "--force-rebuild",
        action="store_true",
        help="Regenerate all pricing scripts even if rate cards are unchanged.",
    )
    evaluate.add_argument(
        "--model",
        default=OPUS_MODEL,
        help=f"Model for Claude Code (default: {OPUS_MODEL}; the in-process "
             "script generation needs Opus).",
    )
    evaluate.set_defaults(func=cmd_evaluate)

    assess = sub.add_parser(
        "assess",
        help="Grounding-only QA over a lodge's evaluation prose.",
        description=(
            "Check that every prose claim in each <property>.md traces to the raw "
            "dossier or the <property>-adr.json; flag anything unsupported. Writes "
            "no evaluation content. Runs on cheaper Sonnet."
        ),
    )
    assess.add_argument("lodge", help="Lodge group name or slug, e.g. 'tanda-tula'.")
    assess.add_argument(
        "--model",
        default=SONNET_MODEL,
        help=f"Model for Claude Code (default: {SONNET_MODEL} — lighter QA).",
    )
    assess.set_defaults(func=cmd_assess)

    # ── categorise phase ──────────────────────────────────────────────────────
    categorise = sub.add_parser(
        "categorise",
        help="Categorise the evaluated corpus into data/categorised/<category>.md.",
        description=(
            "Invert the per-property evaluations into a per-traveller-archetype "
            "view: one markdown file per fixed category, listing the properties "
            "that suit it with a deterministic USD ADR range and a grounded "
            "paragraph each. Reads data/evaluated/ read-only. Runs on Opus."
        ),
    )
    categorise.add_argument(
        "--model",
        default=OPUS_MODEL,
        help=f"Model for Claude Code (default: {OPUS_MODEL} — cross-property synthesis).",
    )
    categorise.set_defaults(func=cmd_categorise)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
