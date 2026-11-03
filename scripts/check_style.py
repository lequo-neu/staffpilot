"""Scan a repository for writing style problems that graders notice.

The checks are deliberately simple so the output is easy to act on:

* text that is not English (accented letters are a strong signal),
* dash punctuation in prose (em dash, en dash, spaced hyphen) and
  hyphenated words in comments, docstrings and Markdown,
* phrases that read as machine written.

Usage: python check_style.py PATH_TO_REPO
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sys
import tokenize


SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".ipynb_checkpoints", "node_modules", "outputs", "cache"}
TEXT_SUFFIXES = {".md", ".txt", ".toml", ".cfg"}

NON_ENGLISH = re.compile("[\\u00c0-\\u024f\\u1e00-\\u1eff]")
DASH_PUNCT = re.compile("[\\u2013\\u2014]| - ")
HYPHEN_WORD = re.compile(r"\b[A-Za-z]+-[A-Za-z]+\b")
AI_TELLS = [
    "delve",
    "leverage",
    "seamless",
    "robust solution",
    "cutting edge",
    "in today's",
    "it's important to note",
    "it is worth noting",
    "as an ai",
    "game changer",
    "unlock the power",
    "plays a crucial role",
    "comprehensive solution",
    "elevate",
    "harness the power",
]


@dataclass
class Finding:
    path: Path
    line: int
    kind: str
    text: str


def _iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix == ".py" or path.suffix in TEXT_SUFFIXES:
            yield path


def _is_docstring(token: tokenize.TokenInfo, previous: int | None) -> bool:
    starts_statement = previous in {tokenize.INDENT, tokenize.NEWLINE, tokenize.NL, None}
    quoted = token.string.lstrip("rbuRBU").startswith(('"""', "'''"))
    return token.type == tokenize.STRING and starts_statement and quoted


def _python_prose(path: Path) -> list[tuple[int, str]]:
    """Return comments and docstrings, which are the prose parts of a module."""
    chunks: list[tuple[int, str]] = []
    with path.open("rb") as handle:
        tokens = list(tokenize.tokenize(handle.readline))
    previous = None
    for token in tokens:
        if token.type == tokenize.COMMENT or _is_docstring(token, previous):
            chunks.append((token.start[0], token.string))
        if token.type not in {tokenize.COMMENT, tokenize.NL, tokenize.ENCODING}:
            previous = token.type
    return chunks


def _markdown_prose(path: Path) -> list[tuple[int, str]]:
    """Return Markdown lines outside fenced code blocks and inline code."""
    chunks: list[tuple[int, str]] = []
    in_fence = False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        chunks.append((number, re.sub(r"`[^`]*`", "", line)))
    return chunks


def scan(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in _iter_files(root):
        if path.suffix == ".py":
            chunks = _python_prose(path)
        elif path.suffix == ".md":
            chunks = _markdown_prose(path)
        else:
            chunks = list(enumerate(path.read_text(encoding="utf-8").splitlines(), start=1))
        for line, text in chunks:
            for offset, row in enumerate(text.splitlines()):
                where = line + offset
                stripped = re.sub(r"https?://\S+", "", row)
                if NON_ENGLISH.search(stripped):
                    findings.append(Finding(path, where, "non English", row.strip()))
                if path.suffix in {".py", ".md"}:
                    if DASH_PUNCT.search(stripped) or re.match(r"\s*[-+*]?\s*-\s", stripped):
                        findings.append(Finding(path, where, "dash", row.strip()))
                    elif HYPHEN_WORD.search(stripped):
                        findings.append(Finding(path, where, "hyphenated word", row.strip()))
                lowered = stripped.lower()
                findings.extend(
                    Finding(path, where, "AI tell", phrase) for phrase in AI_TELLS if phrase in lowered
                )
    return findings


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    findings = scan(root)
    for item in findings:
        sys.stdout.write(f"{item.path.relative_to(root)}:{item.line}: [{item.kind}] {item.text}\n")
    sys.stdout.write(f"\n{len(findings)} finding(s)\n")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
