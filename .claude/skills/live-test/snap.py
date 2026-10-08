"""Read a chrome-devtools snapshot file compactly: the Mini App subtree, matching lines or uid pairs, URLs masked."""

import argparse
import re
import sys

URL = re.compile(r'\b(url|src|href)="[^"]*"')
INIT_DATA = re.compile(r"tgWebApp\w*=[^\s\"']*|\bhash=[0-9a-f]{64}")
NODE = re.compile(r"^\s*uid=(\S+)\s+(.*?)\s*$")


def mask(line: str) -> str:
    """Iframe and page URLs carry the Mini App's initData (an admin credential for 24 h)."""
    return INIT_DATA.sub("<masked>", URL.sub(lambda m: f'{m.group(1)}="<masked>"', line))


def indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def iframe(lines: list[str], title: str) -> list[str]:
    """The first Iframe node whose line matches `title`, with its subtree (continuation lines kept)."""
    start = next(
        (i for i, x in enumerate(lines) if re.search(r"\bIframe\b", x) and re.search(title, x)),
        None,
    )
    if start is None:
        return []
    depth = indent(lines[start])
    out = [lines[start]]
    for x in lines[start + 1 :]:
        if x.lstrip().startswith("uid=") and indent(x) <= depth:
            break
        out.append(x)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "mode",
        choices=["iframe", "grep", "uid"],
        help="iframe: the Mini App subtree; grep: matching lines; uid: 'uid label' pairs of matching nodes",
    )
    ap.add_argument("file", help="snapshot saved with take_snapshot(filePath=...)")
    ap.add_argument(
        "pattern", nargs="?", default="", help="regex; only lines matching it (required for grep)"
    )
    ap.add_argument(
        "-t",
        "--title",
        default="",
        help="regex the Iframe line must match (default: the first iframe)",
    )
    ap.add_argument(
        "-n", "--max", type=int, default=80, help="at most this many lines (default 80)"
    )
    ap.add_argument(
        "-w",
        "--width",
        type=int,
        default=200,
        help="cut lines at this many characters (default 200)",
    )
    a = ap.parse_args()
    with open(a.file, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    if a.mode in ("grep", "uid") and not a.pattern:
        sys.exit(f"{a.mode} needs a pattern")
    if a.mode == "iframe":
        lines = iframe(lines, a.title)
        if not lines:
            sys.exit(
                "no Iframe node in the snapshot: the Mini App is not open, or the modal is collapsed"
            )
    if a.pattern:
        rx = re.compile(a.pattern)
        lines = [x for x in lines if rx.search(x)]
    if a.mode == "uid":
        pairs = [NODE.match(x) for x in lines]
        lines = [f"{m.group(1)} {URL.sub('', m.group(2)).strip()}" for m in pairs if m]
    for x in lines[: a.max]:
        print(mask(x.rstrip())[: a.width])
    if len(lines) > a.max:
        print(f"... {len(lines) - a.max} more lines (raise -n or narrow the pattern)")


if __name__ == "__main__":
    main()
