"""Fact ledger, placeholder rendering and the number check.

Language models are asked to write `{{fact_name}}` instead of numbers. The ledger
fills those in from tool output, and `verify` rejects any number left in the text
that the tools did not produce. This is what keeps answers grounded in the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re


_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")
_LEFTOVER = re.compile(r"\{\{(.*?)\}\}")
_SINGLE = re.compile(r"(?<!\{)\{([^{}\n]+)\}(?!\})")
_JSON = re.compile(r"^\s*[\[{]\s*\"")
_EMPTY_BULLET = re.compile(r"^\s*\*[^\w\n]*$", re.MULTILINE)
_NUMBER = re.compile(
    r"(?<![A-Za-z_])\$?\d[\d,]*(?:\.\d+)?\s*(?:%|percent|million|billion|thousand|[kKmMbB](?![a-z]))?"
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD_SCALE = {"thousand": 1e3, "million": 1e6, "billion": 1e9}
MONEY_KEYS = ("cost", "value", "salary", "uplift", "budget", "revenue", "threshold")
RATE_KEYS = ("rate", "share", "utilization", "change", "index", "cv", "uplift_pct")


def _format(key: str, value: float) -> str:
    lowered = key.lower()
    if lowered.endswith("year"):
        return f"{value:.0f}"
    if any(k in lowered for k in RATE_KEYS) and abs(value) <= 5:
        return f"{value * 100:.1f}%"
    if any(k in lowered for k in MONEY_KEYS):
        sign = "-" if value < 0 else ""
        if abs(value) >= 1e6:
            return f"{sign}${abs(value) / 1e6:,.1f}M"
        return f"{sign}${abs(value):,.0f}"
    if float(value).is_integer() or abs(value) >= 100:
        return f"{value:,.0f}"
    return f"{value:,.1f}"


def _parse_number(token: str) -> tuple[float, float] | None:
    """Return the value of a printed number and half of its last printed digit, as an error bound."""
    raw = token.strip().lower().replace("$", "").replace(",", "")
    scale = 1.0
    for word, factor in _WORD_SCALE.items():
        if raw.endswith(word):
            raw, scale = raw[: -len(word)].strip(), factor
            break
    if raw.endswith("percent"):
        raw, scale = raw[: -len("percent")].strip(), 0.01
    elif raw.endswith("%"):
        raw, scale = raw[:-1].strip(), 0.01
    elif raw and raw[-1] in "kmb":
        raw, scale = raw[:-1].strip(), {"k": 1e3, "m": 1e6, "b": 1e9}[raw[-1]]
    try:
        value = float(raw)
    except ValueError:
        return None
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    return value * scale, 0.5 * 10 ** (-decimals) * scale


@dataclass
class FactLedger:
    facts: dict[str, float] = field(default_factory=dict)

    def add(self, prefix: str, values: dict[str, float]) -> None:
        for key, value in values.items():
            if isinstance(value, bool) or value is None:
                continue
            if isinstance(value, int | float) and math.isfinite(float(value)):
                self.facts[f"{prefix}.{key}" if prefix else key] = float(value)

    def formatted(self) -> dict[str, str]:
        return {key: _format(key, value) for key, value in self.facts.items()}

    def render(self, text: str) -> tuple[str, list[str]]:
        """Replace placeholders. Returns the text and the names that were not found."""
        missing: list[str] = []
        formatted = self.formatted()

        def swap(match: re.Match[str]) -> str:
            name = match.group(1)
            if name in formatted:
                return formatted[name]
            missing.append(name)
            return match.group(0)

        rendered = _PLACEHOLDER.sub(swap, text)
        # Anything still in double braces (a number such as {{5,343}}, or text) is not a fact
        # name. The reader must never see braces, so it counts as missing too.
        missing += [m.strip() for m in _LEFTOVER.findall(rendered) if m.strip() not in missing]
        # The same holds for single braces, for a fact name written without any braces
        # (France.hires), for a tool call sent back as JSON and for an empty bullet.
        missing += [f"{{{m}}}" for m in _SINGLE.findall(rendered)]
        prefixes = "|".join(sorted({re.escape(k.split(".")[0]) for k in formatted} | {"[A-Z][A-Za-z]+"}))
        file_types = r"(?!(?:md|csv|txt|json|toml|xlsx|pdf|html|py)\b)"
        missing += re.findall(rf"(?<![\w.{{])(?:{prefixes})\.{file_types}[a-z][a-z_]+(?!\w)", rendered)
        if _JSON.match(rendered):
            missing.append("JSON instead of sentences")
        if _EMPTY_BULLET.search(rendered):
            missing.append("an empty bullet")
        return rendered, missing

    def verify(self, text: str, context: str = "", countries: list[str] | None = None) -> list[str]:
        """Return numbers in `text` that no fact, and nothing in `context`, supports.

        `context` holds the question and tool notes (for example retrieved rule text),
        which are legitimate sources too. When `countries` is given, a sentence that
        names a country may only use that country's facts or facts that belong to no
        country, so a German figure written next to France is rejected.
        """
        context_values = [p[0] for p in (_parse_number(t) for t in _NUMBER.findall(context)) if p is not None]
        keys = {c.replace(" ", "_"): c for c in countries or []}
        unsupported = []
        for sentence in _SENTENCE.split(text):
            named = {
                k for k, c in keys.items() if re.search(rf"(?<![A-Za-z]){re.escape(c)}(?![A-Za-z])", sentence)
            }
            allowed = [
                value
                for key, value in self.facts.items()
                if not named or key.split(".")[0] in named or key.split(".")[0] not in keys
            ]
            allowed += context_values
            for token in _NUMBER.findall(sentence):
                parsed = _parse_number(token)
                if parsed is None:
                    continue
                value, precision = parsed
                # Small counts, years and month numbers are part of normal writing.
                if value.is_integer() and (abs(value) <= 12 or 1990 <= value <= 2100):
                    continue
                if any(_close(value, precision, a) for a in allowed):
                    continue
                unsupported.append(token.strip())
        return unsupported


def _close(value: float, precision: float, allowed: float) -> bool:
    """True when `value`, printed with `precision`, could be a rounding of `allowed`.

    Signs are not read from the text, so magnitudes are compared. A share such as
    0.991 may also be written as 99.1, so shares (magnitude up to 5) are tried in percent.
    """
    targets = [abs(allowed)] + ([abs(allowed) * 100] if abs(allowed) <= 5 else [])
    return any(abs(abs(value) - target) <= precision * 1.0001 + 1e-9 for target in targets)
