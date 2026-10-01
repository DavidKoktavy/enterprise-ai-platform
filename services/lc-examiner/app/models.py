"""Domain model for documentary credit (LC) examination."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field, PrivateAttr


class LetterOfCredit(BaseModel):
    lc_number: str
    issue_date: date
    expiry_date: date
    currency: str = Field(min_length=3, max_length=3)
    amount: Decimal
    # Art. 30(a): "about"/"approximately" allows ±10 %; otherwise explicit tolerance
    amount_tolerance_pct: Decimal = Decimal("0")
    applicant: str
    beneficiary: str
    port_of_loading: str
    port_of_discharge: str
    latest_shipment_date: date
    partial_shipments_allowed: bool = True
    transhipment_allowed: bool = True
    presentation_period_days: int = 21  # Art. 14(c) default
    incoterm: str = "CIF"
    goods_description: str
    required_documents: list[str]


class Invoice(BaseModel):
    issuer: str
    addressee: str
    currency: str
    amount: Decimal
    goods_description: str


class BillOfLading(BaseModel):
    on_board_date: date
    port_of_loading: str
    port_of_discharge: str
    transhipment: bool = False
    clean: bool = True
    clauses: list[str] = []


class InsuranceDocument(BaseModel):
    currency: str
    amount: Decimal
    effective_date: date


class Presentation(BaseModel):
    presentation_id: str
    lc_number: str
    presentation_date: date
    shipment_count: int = 1
    documents_presented: list[str]
    invoice: Invoice
    bill_of_lading: BillOfLading
    insurance: InsuranceDocument | None = None


class ExaminationRequest(BaseModel):
    lc: LetterOfCredit
    presentation: Presentation
    # Offline demo only: canned LLM output passed to the mock provider
    _mock_llm: str | None = PrivateAttr(default=None)


class Severity(StrEnum):
    discrepancy = "discrepancy"  # grounds for refusal
    warning = "warning"          # needs examiner attention, not a refusal ground


class Finding(BaseModel):
    rule_id: str
    ucp_article: str
    severity: Severity
    message: str
    source: str = "rule"  # rule | llm


class ExaminationResult(BaseModel):
    lc_number: str
    presentation_id: str
    status: str  # COMPLIANT | DISCREPANT
    findings: list[Finding]
    examination_deadline: date  # Art. 14(b): 5 banking days following presentation
    llm_used: bool
    llm_model: str | None = None
    needs_human_review: bool = True  # four-eyes principle: AI recommends, examiner decides
    examined_at: datetime
