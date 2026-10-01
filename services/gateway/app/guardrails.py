"""Guardrails applied to every prompt before it leaves the bank's perimeter.

* PII redaction with validation (checksums) to keep false positives low:
  Czech birth numbers (rodné číslo), IBANs (mod-97), payment cards (Luhn),
  e-mail addresses and Czech phone numbers.
* Heuristic prompt-injection detection. This is a first line of defence only;
  in Azure it is complemented by Azure AI Content Safety Prompt Shields.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- validators -------------------------------------------------------------


def valid_rodne_cislo(digits: str) -> bool:
    """Czech/Slovak birth number checksum + plausible date."""
    if len(digits) not in (9, 10) or not digits.isdigit():
        return False
    yy, mm, dd = int(digits[0:2]), int(digits[2:4]), int(digits[4:6])
    for offset in (0, 20, 50, 70):  # +50 women, +20/+70 extended series since 2004
        if 1 <= mm - offset <= 12:
            break
    else:
        return False
    if not 1 <= dd <= 31:
        return False
    if len(digits) == 9:  # issued before 1954, no checksum
        return yy < 54
    n = int(digits)
    if n % 11 == 0:
        return True
    # historic exception: remainder 10 -> check digit 0
    return int(digits[:9]) % 11 == 10 and digits[9] == "0"


def valid_iban(raw: str) -> bool:
    s = raw.replace(" ", "").upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", s):
        return False
    rearranged = s[4:] + s[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    return int(numeric) % 97 == 1


def valid_luhn(raw: str) -> bool:
    digits = [int(c) for c in raw if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# --- detectors --------------------------------------------------------------

_PATTERNS: list[tuple[str, re.Pattern[str], object]] = [
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,4})?\b"), valid_iban),
    ("CARD", re.compile(r"\b(?:\d[ -]?){12,18}\d\b"), valid_luhn),
    (
        "BIRTH_NUMBER",
        re.compile(r"\b\d{6}/?\d{3,4}\b"),
        lambda s: valid_rodne_cislo(s.replace("/", "")),
    ),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), None),
    ("PHONE", re.compile(r"(?<!\d)(?:\+420 ?)?[1-9]\d{2} ?\d{3} ?\d{3}(?!\d)"), None),
]

_INJECTION = [
    r"ignore (all|any|the)? ?(previous|prior|above) (instructions|prompts?)",
    r"disregard (the|your) (system|previous) (prompt|instructions)",
    r"you are now (in )?(developer|dan|jailbreak) mode",
    r"reveal (your|the) (system prompt|instructions|hidden prompt)",
    r"zapomeň na (všechny )?(předchozí|dosavadní) instrukce",
    r"ignoruj (všechny )?(předchozí|výše uvedené) (instrukce|pokyny)",
]
_INJECTION_RE = re.compile("|".join(_INJECTION), re.IGNORECASE)


@dataclass
class RedactionResult:
    text: str
    findings: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.findings.values())


def redact(text: str) -> RedactionResult:
    findings: dict[str, int] = {}
    for label, pattern, validator in _PATTERNS:

        def _sub(m: re.Match[str], label: str = label, validator: object = validator) -> str:
            if validator is not None and not validator(m.group(0)):  # type: ignore[operator]
                return m.group(0)
            findings[label] = findings.get(label, 0) + 1
            return f"[{label}]"

        text = pattern.sub(_sub, text)
    return RedactionResult(text=text, findings=findings)


def detect_prompt_injection(text: str) -> str | None:
    m = _INJECTION_RE.search(text)
    return m.group(0) if m else None
