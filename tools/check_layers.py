"""Layer dependency checker.

Validates rules from docs/decisions/005-interfaces-as-thin-adapters.md and 015-apps-layer-and-notes.md.
Exits non-zero on violation. Output includes remediation hint.

Run: uv run python tools/check_layers.py
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

LLM_SDKS = {
    "langchain",
    "langchain_core",
    "langchain_community",
    "langgraph",
    "openai",
    "anthropic",
}

# Apps hold domain and storage; transport stays in interfaces/* (ADR-015).
APP_FORBIDDEN = {"workflows", "interfaces", "aiogram", "fastapi", "starlette", "uvicorn"}


@dataclass
class Violation:
    file: Path
    importing: str
    rule: str
    fix: str

    def format(self) -> str:
        rel = self.file.relative_to(REPO_ROOT)
        return (
            f"VIOLATION: {rel}\n"
            f"  imports: {self.importing}\n"
            f"  rule:    {self.rule}\n"
            f"  fix:     {self.fix}\n"
        )


def iter_imports(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def root_pkg(import_name: str) -> str:
    return import_name.split(".")[0]


def _app_packages() -> set[str]:
    apps = REPO_ROOT / "apps"
    if not apps.exists():
        return set()
    return {pkg.name for pkg in apps.glob("*/src/*") if pkg.is_dir()}


APP_PACKAGES = _app_packages()


def _app_package(parts: tuple[str, ...]) -> str | None:
    """The importable package of an apps/<name>/src/<pkg>/... path."""
    return parts[3] if len(parts) > 3 and parts[2] == "src" else None


def check_file(path: Path) -> list[Violation]:
    rel = path.relative_to(REPO_ROOT)
    parts = rel.parts
    violations: list[Violation] = []
    imports = iter_imports(path)

    in_interfaces = parts[0] == "interfaces"
    in_shared = parts[0] == "shared"
    in_workflows = parts[0] == "workflows" and len(parts) >= 2
    in_apps = parts[0] == "apps" and len(parts) >= 2

    for imp in imports:
        root = root_pkg(imp)

        if in_interfaces and root in LLM_SDKS:
            violations.append(
                Violation(
                    path,
                    imp,
                    "interfaces/* must not import LLM SDKs",
                    "move LLM logic into a workflow; interface should only call build_graph().invoke()",
                )
            )

        if in_apps and root in APP_FORBIDDEN:
            violations.append(
                Violation(
                    path,
                    imp,
                    "apps/* must not import workflows.*, interfaces.* or transport frameworks",
                    "keep Telegram/HTTP code in interfaces/*; pass a callback into the app instead",
                )
            )

        if in_apps and root in APP_PACKAGES and root != _app_package(parts):
            violations.append(
                Violation(
                    path,
                    imp,
                    f"apps/{parts[1]}/* must not import another app ({root})",
                    "extract the shared piece into shared/",
                )
            )

        if in_shared and root in {"workflows", "interfaces"} | APP_PACKAGES:
            violations.append(
                Violation(
                    path,
                    imp,
                    "shared/* must not import workflows.*, apps or interfaces.*",
                    "shared is the bottom layer; remove this import or invert the dependency",
                )
            )

        if in_workflows and root == "workflows":
            this_workflow = parts[1]
            other_workflow = imp.split(".")[1] if "." in imp else None
            if other_workflow and other_workflow != this_workflow:
                violations.append(
                    Violation(
                        path,
                        imp,
                        f"workflows/{this_workflow}/* must not import workflows/{other_workflow}/*",
                        "extract the shared piece into shared/, or call the other workflow via its build_graph() through the interface layer",
                    )
                )

        if in_workflows and root in APP_PACKAGES:
            violations.append(
                Violation(
                    path,
                    imp,
                    "workflows/* must not import apps",
                    "apps sit beside workflows; compose them in an interface",
                )
            )

        if in_workflows and root == "interfaces":
            violations.append(
                Violation(
                    path,
                    imp,
                    "workflows/* must not import interfaces/*",
                    "workflows are below interfaces; invert the dependency",
                )
            )

    return violations


def main() -> int:
    py_files: list[Path] = []
    for top in ("interfaces", "shared", "workflows", "apps"):
        root = REPO_ROOT / top
        if not root.exists():
            continue
        py_files.extend(root.rglob("*.py"))

    all_violations: list[Violation] = []
    for f in py_files:
        all_violations.extend(check_file(f))

    if not all_violations:
        print(f"check_layers: OK ({len(py_files)} files)")
        return 0

    for v in all_violations:
        print(v.format(), file=sys.stderr)
    print(f"check_layers: FAILED — {len(all_violations)} violation(s)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
