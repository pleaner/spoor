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
        log_path = project / "raw" / slug / "collect.log"
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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
