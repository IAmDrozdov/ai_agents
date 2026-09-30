#!/usr/bin/env bash
# Fails when the git history or the staged files contain a secret (trufflehog, offline).
set -euo pipefail
cd "$(dirname "$0")/.."
command -v trufflehog >/dev/null || { echo "ERROR: trufflehog is not installed (brew install trufflehog)" >&2; exit 1; }
trufflehog git "file://$PWD" --no-verification --no-update --fail
staged=()
while IFS= read -r -d '' f; do staged+=("$f"); done < <(git diff --cached --name-only -z --diff-filter=ACM)
[ ${#staged[@]} -eq 0 ] || trufflehog filesystem "${staged[@]}" --no-verification --no-update --fail
