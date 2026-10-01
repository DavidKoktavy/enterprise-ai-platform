"""Deterministic UCP 600 checks.

The rules engine is the system of record for hard, auditable checks; the LLM is
used only for the inherently fuzzy ones (goods description consistency, unusual
clauses) and can only *add* findings, never remove one. This split keeps the
decision explainable to auditors and regulators.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal

from .models import Finding, LetterOfCredit, Presentation, Severity

Rule = Callable[[LetterOfCredit, Presentation], list[Finding]]
RULES: list[Rule] = []


def rule(fn: Rule) -> Rule:
    RULES.append(fn)
    return fn


def _norm(s: str) -> str:
    s = s.upper()
    s = re.sub(r"[^\w ]", " ", s)
    s = re.sub(r"\s+", " ", s)
    # glue runs of single letters: "G M B H" -> "GMBH", "A S" -> "AS", "S R O" -> "SRO"
    s = re.sub(r"(?<!\w)\w(?: \w(?!\w))+", lambda m: m.group(0).replace(" ", ""), s)
    s = re.sub(r"\b(SRO|AS|GMBH|LTD|LIMITED|CO|INC|LLC|SPA|SA|AG)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _d(rule_id: str, art: str, msg: str, sev: Severity = Severity.discrepancy) -> Finding:
    return Finding(rule_id=rule_id, ucp_article=art, severity=sev, message=msg)


def add_banking_days(start: date, days: int) -> date:
    """Weekends excluded. Production uses the TARGET2 / CZ bank-holiday calendar."""
    d, added = start, 0
    while added < days:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d


@rule
def expiry(lc: LetterOfCredit, p: Presentation) -> list[Finding]:
    if p.presentation_date > lc.expiry_date:
        return [_d("EXPIRY", "6(d)(i), 6(e)",
                   f"Presented {p.presentation_date} after LC expiry {lc.expiry_date}")]
    return []


@rule
def presentation_period(lc: LetterOfCredit, p: Presentation) -> list[Finding]:
    limit = p.bill_of_lading.on_board_date + timedelta(days=lc.presentation_period_days)
    if p.presentation_date > limit:
        return [_d("LATE_PRESENTATION", "14(c)",
                   f"Presented {(p.presentation_date - p.bill_of_lading.on_board_date).days} days "
                   f"after shipment; limit is {lc.presentation_period_days}")]
    return []


@rule
def latest_shipment(lc: LetterOfCredit, p: Presentation) -> list[Finding]:
    if p.bill_of_lading.on_board_date > lc.latest_shipment_date:
        return [_d("LATE_SHIPMENT", "20(a)(ii)",
                   f"On-board date {p.bill_of_lading.on_board_date} later than latest "
                   f"shipment date {lc.latest_shipment_date}")]
    return []


@rule
def invoice_currency(lc: LetterOfCredit, p: Presentation) -> list[Finding]:
    if p.invoice.currency.upper() != lc.currency.upper():
        return [_d("INVOICE_CURRENCY", "18(a)(iii)",
                   f"Invoice in {p.invoice.currency}, credit in {lc.currency}")]
    return []


@rule
def invoice_amount(lc: LetterOfCredit, p: Presentation) -> list[Finding]:
    ceiling = lc.amount * (1 + lc.amount_tolerance_pct / Decimal(100))
    if p.invoice.amount > ceiling:
        return [_d("OVERDRAWN", "18(b), 30(a)",
                   f"Invoice {p.invoice.amount} exceeds credit amount {lc.amount} "
                   f"(+{lc.amount_tolerance_pct}% tolerance = {ceiling:.2f})")]
    return []


@rule
def invoice_parties(lc: LetterOfCredit, p: Presentation) -> list[Finding]:
    out = []
    if _norm(p.invoice.issuer) != _norm(lc.beneficiary):
        out.append(_d("INVOICE_ISSUER", "18(a)(i)",
                      f"Invoice issued by '{p.invoice.issuer}', beneficiary is '{lc.beneficiary}'"))
    if _norm(p.invoice.addressee) != _norm(lc.applicant):
        out.append(_d("INVOICE_ADDRESSEE", "18(a)(ii)",
                      f"Invoice made out to '{p.invoice.addressee}', applicant is '{lc.applicant}'"))
    return out


@rule
def ports(lc: LetterOfCredit, p: Presentation) -> list[Finding]:
    out = []
    if _norm(p.bill_of_lading.port_of_loading) != _norm(lc.port_of_loading):
        out.append(_d("PORT_OF_LOADING", "20(a)(iii)",
                      f"B/L port of loading '{p.bill_of_lading.port_of_loading}' ≠ "
                      f"'{lc.port_of_loading}'"))
    if _norm(p.bill_of_lading.port_of_discharge) != _norm(lc.port_of_discharge):
        out.append(_d("PORT_OF_DISCHARGE", "20(a)(iii)",
                      f"B/L port of discharge '{p.bill_of_lading.port_of_discharge}' ≠ "
                      f"'{lc.port_of_discharge}'"))
    return out


@rule
def transhipment(lc: LetterOfCredit, p: Presentation) -> list[Finding]:
    if not lc.transhipment_allowed and p.bill_of_lading.transhipment:
        # Art. 20(c)(ii): B/L indicating transhipment is acceptable even if prohibited,
        # provided goods were shipped in containers per B/L — examiner must verify.
        return [_d("TRANSHIPMENT", "20(c)",
                   "B/L indicates transhipment though prohibited — acceptable only if goods "
                   "shipped in container/trailer/LASH barge per B/L (Art. 20(c)(ii))",
                   Severity.warning)]
    return []


@rule
def clean_transport_doc(lc: LetterOfCredit, p: Presentation) -> list[Finding]:
    if not p.bill_of_lading.clean:
        return [_d("UNCLEAN_BL", "27",
                   f"Transport document carries clauses: {', '.join(p.bill_of_lading.clauses)}")]
    return []


@rule
def partial_shipments(lc: LetterOfCredit, p: Presentation) -> list[Finding]:
    if not lc.partial_shipments_allowed and p.shipment_count > 1:
        return [_d("PARTIAL_SHIPMENT", "31(a)",
                   f"{p.shipment_count} shipments presented, partial shipments prohibited")]
    return []


@rule
def required_documents(lc: LetterOfCredit, p: Presentation) -> list[Finding]:
    presented = {d.strip().lower() for d in p.documents_presented}
    missing = [d for d in lc.required_documents if d.strip().lower() not in presented]
    if missing:
        return [_d("MISSING_DOCUMENTS", "14(a), 15", f"Missing required documents: {missing}")]
    return []


@rule
def insurance(lc: LetterOfCredit, p: Presentation) -> list[Finding]:
    needs = lc.incoterm.upper() in {"CIF", "CIP"}
    if not needs:
        return []
    ins = p.insurance
    if ins is None:
        return [_d("INSURANCE_MISSING", "28(a)", f"{lc.incoterm} credit but no insurance document")]
    out = []
    minimum = p.invoice.amount * Decimal("1.10")
    if ins.currency.upper() != lc.currency.upper():
        out.append(_d("INSURANCE_CURRENCY", "28(f)(i)",
                      f"Insurance in {ins.currency}, credit in {lc.currency}"))
    if ins.amount < minimum:
        out.append(_d("UNDERINSURED", "28(f)(ii)",
                      f"Insured {ins.amount} < 110% of invoice value ({minimum:.2f})"))
    if ins.effective_date > p.bill_of_lading.on_board_date:
        out.append(_d("INSURANCE_DATE", "28(e)",
                      f"Cover effective {ins.effective_date}, after shipment "
                      f"{p.bill_of_lading.on_board_date}"))
    return out


def run_rules(lc: LetterOfCredit, p: Presentation) -> list[Finding]:
    findings: list[Finding] = []
    for r in RULES:
        findings.extend(r(lc, p))
    return findings
