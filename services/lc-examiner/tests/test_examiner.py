import json
from pathlib import Path

import httpx
import pytest

from app.llm import GatewayClient
from app.rules import add_banking_days, run_rules
from app.service import examine, parse_request

SAMPLES = Path(__file__).resolve().parents[3] / "samples"


def load(name):
    return parse_request((SAMPLES / name).read_text(encoding="utf-8"))


def ids(findings):
    return {f.rule_id for f in findings}


def test_compliant_presentation_has_no_findings():
    req = load("presentation_compliant.json")
    assert run_rules(req.lc, req.presentation) == []


def test_discrepant_presentation_rules():
    req = load("presentation_discrepant.json")
    assert ids(run_rules(req.lc, req.presentation)) == {
        "LATE_PRESENTATION", "OVERDRAWN", "UNDERINSURED", "MISSING_DOCUMENTS", "UNCLEAN_BL",
    }


def test_tolerance_applies():
    req = load("presentation_compliant.json")
    req.presentation.invoice.amount = req.lc.amount * 105 / 100  # exactly +5 %
    req.presentation.insurance.amount = req.presentation.invoice.amount * 2
    assert "OVERDRAWN" not in ids(run_rules(req.lc, req.presentation))


def test_name_normalisation_ignores_legal_form_and_punctuation():
    req = load("presentation_compliant.json")
    req.presentation.invoice.addressee = "MORAVIA STEELWORKS, a. s."
    assert run_rules(req.lc, req.presentation) == []


def test_transhipment_is_warning_not_refusal():
    req = load("presentation_compliant.json")
    req.presentation.bill_of_lading.transhipment = True
    (f,) = run_rules(req.lc, req.presentation)
    assert f.rule_id == "TRANSHIPMENT" and f.severity == "warning"


def test_banking_days_skip_weekend():
    from datetime import date
    # Wed 30 Sep 2026 + 5 banking days = Wed 7 Oct 2026
    assert add_banking_days(date(2026, 9, 30), 5) == date(2026, 10, 7)


def _gateway_stub(content: str, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-data-classification"] == "confidential"
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(
            status,
            json={"model": "chat-reasoning",
                  "choices": [{"message": {"role": "assistant", "content": content}}]},
        )
    return GatewayClient("http://gw", "k", transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_llm_adds_goods_description_finding():
    req = load("presentation_discrepant.json")
    llm = json.dumps({"findings": [{"ucp_article": "18(c)", "severity": "discrepancy",
                                    "message": "goods do not correspond"}]})
    res = await examine(req, _gateway_stub(llm))
    assert res.status == "DISCREPANT"
    assert res.llm_used and res.llm_model == "chat-reasoning"
    assert any(f.source == "llm" and f.ucp_article == "18(c)" for f in res.findings)
    assert res.needs_human_review


@pytest.mark.asyncio
async def test_malformed_llm_output_is_ignored_rules_still_apply():
    req = load("presentation_discrepant.json")
    res = await examine(req, _gateway_stub("not json at all"))
    assert not res.llm_used
    assert res.status == "DISCREPANT"
    assert all(f.source == "rule" for f in res.findings)


@pytest.mark.asyncio
async def test_gateway_outage_degrades_gracefully():
    req = load("presentation_compliant.json")
    res = await examine(req, _gateway_stub("", status=503))
    assert res.status == "COMPLIANT" and not res.llm_used
