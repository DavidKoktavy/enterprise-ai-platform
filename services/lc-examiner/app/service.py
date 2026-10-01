from __future__ import annotations

import json
from datetime import UTC, datetime

from .llm import GatewayClient
from .models import ExaminationRequest, ExaminationResult, Severity
from .rules import add_banking_days, run_rules


async def examine(
    req: ExaminationRequest, gateway: GatewayClient | None, use_llm: bool = True
) -> ExaminationResult:
    lc, p = req.lc, req.presentation
    findings = run_rules(lc, p)
    llm_model = None
    if use_llm and gateway is not None:
        # In offline/mock mode, a sample may carry the expected LLM output so the
        # whole pipeline is demonstrable without Azure credentials.
        hint = req._mock_llm
        llm_findings, llm_model = await gateway.review(
            lc, p, request_id=p.presentation_id, mock_hint=hint
        )
        findings.extend(llm_findings)
    status = (
        "DISCREPANT" if any(f.severity == Severity.discrepancy for f in findings) else "COMPLIANT"
    )
    return ExaminationResult(
        lc_number=lc.lc_number,
        presentation_id=p.presentation_id,
        status=status,
        findings=findings,
        examination_deadline=add_banking_days(p.presentation_date, 5),
        llm_used=llm_model is not None,
        llm_model=llm_model,
        needs_human_review=True,
        examined_at=datetime.now(UTC),
    )


def parse_request(raw: bytes | str | dict) -> ExaminationRequest:
    data = json.loads(raw) if isinstance(raw, (bytes, str)) else dict(raw)
    mock = data.pop("mock_llm_response", None)
    req = ExaminationRequest.model_validate(data)
    if mock is not None:
        req._mock_llm = json.dumps(mock)
    return req
