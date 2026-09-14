"""`smoke <workflow> <path-or-url>`: preview, price, confirm, run, write the deliverable."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from shared.config import settings
from shared.job import (
    AudioDeliverable,
    Cost,
    DocumentSource,
    FileDeliverable,
    LinkSource,
    Preview,
    Result,
    Source,
)

from .registry import WORKFLOWS


class StderrProgress:
    def phase(self, name: str, total: int) -> None:
        print(f"[{name}] total={total}", file=sys.stderr)

    def tick(self, done: int, total: int) -> None:
        print(f"  {done}/{total}", file=sys.stderr)


def _source(arg: str) -> Source:
    if arg.startswith(("http://", "https://")):
        return LinkSource(arg)
    path = Path(arg)
    return DocumentSource(path.read_bytes(), path.name)


def _print_cost(cost: Cost, *, approximate: bool = False) -> None:
    mark = "≈ " if approximate else ""
    for line in cost.lines:
        print(f"  {line.label:<14} {mark}${line.usd:.4f}")
    print(f"  {'Total':<14} {mark}${cost.total_usd:.4f}")


def _print_preview(preview: Preview) -> None:
    print(f"Title:      {preview.title}")
    print(f"Characters: {preview.char_count}  Chapters: {preview.chapter_count}")
    if preview.duration_s:
        print(f"Duration:   {preview.duration_s / 60:.1f} min")
    if preview.note:
        print(f"Note:       {preview.note}")


def _write(result: Result, out_dir: Path) -> None:
    deliverable = result.deliverable
    if deliverable is None:
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    if isinstance(deliverable, FileDeliverable):
        target = out_dir / deliverable.filename
        target.write_bytes(deliverable.data)
        print(f"Wrote {target} ({len(deliverable.data)} bytes)")
        return
    audio: AudioDeliverable = deliverable
    target = out_dir / audio.filename
    target.write_bytes(audio.data)
    print(f"Wrote {target} ({len(audio.data)} bytes, {audio.duration_s:.0f}s)")
    stem = target.stem
    for i, part in enumerate(audio.parts, start=1):
        (out_dir / f"{stem}.part{i}.ogg").write_bytes(part)
    if audio.parts:
        print(f"Wrote {len(audio.parts)} part file(s)")


def main() -> None:
    parser = argparse.ArgumentParser(prog="smoke", description=__doc__)
    parser.add_argument("workflow", choices=sorted(WORKFLOWS))
    parser.add_argument("source", help="document path or URL")
    parser.add_argument("--config", default="{}", help="JSON overrides for the workflow config")
    parser.add_argument("--out", default="dist/smoke", help="directory for the deliverable")
    parser.add_argument("--yes", action="store_true", help="run without confirming the estimate")
    args = parser.parse_args()

    workflow = WORKFLOWS[args.workflow]
    config = workflow.config_type.model_validate(json.loads(args.config))
    source = _source(args.source)
    if source.kind not in workflow.accepts:
        sys.exit(f"{workflow.id} accepts {sorted(workflow.accepts)}, got a {source.kind}")

    preview = workflow.preview(settings, config, source)
    if preview.error:
        sys.exit(f"preview failed: {preview.error}")
    _print_preview(preview)

    estimate = workflow.estimate(settings, config, preview)
    if estimate.error:
        sys.exit(f"estimate failed: {estimate.error}")
    print("Estimate:")
    _print_cost(estimate.cost, approximate=estimate.approximate)

    if not args.yes:
        answer = input("Run (paid)? [y/N] ").strip().lower()
        if answer != "y":
            sys.exit("aborted")

    result = workflow.run(settings, config, preview, StderrProgress())
    if result.error:
        sys.exit(f"run failed: {result.error}")
    print("Facts:")
    for fact in result.facts:
        print(f"  {fact.label}: {fact.value}")
    print("Cost:")
    _print_cost(result.cost)
    _write(result, Path(args.out))


if __name__ == "__main__":
    main()
