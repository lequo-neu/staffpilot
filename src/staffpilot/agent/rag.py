"""Small BM25 retriever over the case rules, assumptions and metric definitions.

The corpus is a few pages, so lexical retrieval is enough and needs no API key.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from importlib import resources
import math
import re


_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "how",
        "if",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "what",
        "when",
        "which",
        "who",
        "why",
        "will",
        "with",
        "does",
        "do",
        "can",
    ]
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


@dataclass
class Passage:
    source: str
    heading: str
    text: str
    score: float = 0.0

    @property
    def citation(self) -> str:
        return f"{self.source} / {self.heading}"


def load_passages() -> list[Passage]:
    """Split each knowledge file into one passage per second level heading."""
    passages = []
    folder = resources.files("staffpilot").joinpath("knowledge")
    for entry in sorted(folder.iterdir(), key=lambda e: e.name):
        if not entry.name.endswith(".md"):
            continue
        heading, lines = "", []
        for line in entry.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                if heading and lines:
                    passages.append(Passage(entry.name, heading, " ".join(lines).strip()))
                heading, lines = line[3:].strip(), []
            elif heading and line.strip():
                lines.append(line.strip())
        if heading and lines:
            passages.append(Passage(entry.name, heading, " ".join(lines).strip()))
    return passages


class Retriever:
    def __init__(self, passages: list[Passage] | None = None, k1: float = 1.4, b: float = 0.75) -> None:
        self.passages = passages or load_passages()
        self.k1, self.b = k1, b
        self._docs = [tokenize(f"{p.heading} {p.heading} {p.text}") for p in self.passages]
        self._lengths = [len(d) for d in self._docs]
        self._avg = sum(self._lengths) / max(len(self._docs), 1)
        frequency = Counter(t for doc in self._docs for t in set(doc))
        n = len(self._docs)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in frequency.items()}
        self._counts = [Counter(doc) for doc in self._docs]

    def search(self, query: str, k: int = 3) -> list[Passage]:
        terms = tokenize(query)
        scored = []
        for i, counts in enumerate(self._counts):
            score = 0.0
            for term in terms:
                tf = counts.get(term, 0)
                if tf:
                    norm = (
                        tf
                        * (self.k1 + 1)
                        / (tf + self.k1 * (1 - self.b + self.b * self._lengths[i] / self._avg))
                    )
                    score += self._idf.get(term, 0.0) * norm
            if score > 0:
                p = self.passages[i]
                scored.append(Passage(p.source, p.heading, p.text, score))
        return sorted(scored, key=lambda p: -p.score)[:k]
