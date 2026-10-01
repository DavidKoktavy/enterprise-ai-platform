"""Evaluation harness — regression gate for the examiner (runs in CI).

Builds a labelled test set by applying known mutations to a compliant
presentation (each mutation = one expected UCP 600 discrepancy), runs the
examiner, and reports precision/recall per rule. CI fails if recall on any
refusal-grade rule drops below the threshold — the same gate applies when a
prompt or model version changes (`--with-llm`, against a live gateway).

    python eval/run_eval.py                 # rules only, offline
    python eval/run_eval.py --with-llm      # + LLM review via $GATEWAY_URL
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "lc-examiner"))

from app.llm import GatewayClient  # noqa: E402
from app.service import examine, parse_request  # noqa: E402

BASE = json.loads((ROOT / "samples" / "presentation_compliant.json").read_text(encoding="utf-8"))


def _m(path: str, value):
    def apply(d):
        node = d
        *parents, leaf = path.split(".")
        for p in parents:
            node = node[p]
        node[leaf] = value(node[leaf]) if callable(value) else value
    return apply


MUTATIONS: list[tuple[str, set[str], list]] = [
    ("baseline", set(), []),
    ("expired", {"EXPIRY", "LATE_PRESENTATION"}, [_m("presentation.presentation_date", "2026-11-02")]),
    ("late_presentation", {"LATE_PRESENTATION"}, [_m("presentation.presentation_date", "2026-10-15")]),
    ("late_shipment", {"LATE_SHIPMENT"}, [_m("presentation.bill_of_lading.on_board_date", "2026-09-27"),
                                          _m("presentation.insurance.effective_date", "2026-09-27")]),
    ("overdrawn", {"OVERDRAWN", "UNDERINSURED"}, [_m("presentation.invoice.amount", "261000.00")]),
    ("within_tolerance", set(), [_m("presentation.invoice.amount", "260400.00"),
                                 _m("presentation.insurance.amount", "290000.00")]),
    ("wrong_currency", {"INVOICE_CURRENCY"}, [_m("presentation.invoice.currency", "USD")]),
    ("wrong_issuer", {"INVOICE_ISSUER"}, [_m("presentation.invoice.issuer", "Baltic Trading Ltd")]),
    ("wrong_addressee", {"INVOICE_ADDRESSEE"}, [_m("presentation.invoice.addressee", "Ostrava Metals s.r.o.")]),
    ("legal_form_variant", set(), [_m("presentation.invoice.issuer", "HANSEATIC MACHINE TOOLS G.m.b.H.")]),
    ("wrong_pol", {"PORT_OF_LOADING"}, [_m("presentation.bill_of_lading.port_of_loading", "Bremerhaven")]),
    ("wrong_pod", {"PORT_OF_DISCHARGE"}, [_m("presentation.bill_of_lading.port_of_discharge", "Rijeka")]),
    ("unclean_bl", {"UNCLEAN_BL"}, [_m("presentation.bill_of_lading.clean", False),
                                     _m("presentation.bill_of_lading.clauses", ["packaging torn"])]),
    ("partial", {"PARTIAL_SHIPMENT"}, [_m("presentation.shipment_count", 2)]),
    ("missing_coo", {"MISSING_DOCUMENTS"}, [_m("presentation.documents_presented",
                                               lambda v: [x for x in v if "Origin" not in x])]),
    ("no_insurance", {"INSURANCE_MISSING"}, [_m("presentation.insurance", None)]),
    ("underinsured", {"UNDERINSURED"}, [_m("presentation.insurance.amount", "250000.00")]),
    ("insurance_late", {"INSURANCE_DATE"}, [_m("presentation.insurance.effective_date", "2026-09-23")]),
    ("insurance_ccy", {"INSURANCE_CURRENCY"}, [_m("presentation.insurance.currency", "CZK")]),
    ("transhipment", {"TRANSHIPMENT"}, [_m("presentation.bill_of_lading.transhipment", True)]),
]

RECALL_THRESHOLD = 1.0  # refusal-grade rules must never be missed on the golden set


async def main(with_llm: bool) -> int:
    gateway = GatewayClient() if with_llm else None
    tp, fp, fn = defaultdict(int), defaultdict(int), defaultdict(int)
    print(f"{'case':22} {'expected':40} {'got':40} ok")
    all_ok = True
    for name, expected, muts in MUTATIONS:
        data = copy.deepcopy(BASE)
        data.pop("mock_llm_response", None)
        for m in muts:
            m(data)
        res = await examine(parse_request(data), gateway, use_llm=with_llm)
        got = {f.rule_id for f in res.findings if f.source == "rule"}
        for r in got & expected:
            tp[r] += 1
        for r in got - expected:
            fp[r] += 1
        for r in expected - got:
            fn[r] += 1
        ok = got == expected
        all_ok &= ok
        print(f"{name:22} {','.join(sorted(expected)) or '-':40} {','.join(sorted(got)) or '-':40} "
              f"{'✓' if ok else '✗'}")

    print("\nper-rule metrics")
    failed = []
    for r in sorted(set(tp) | set(fp) | set(fn)):
        p = tp[r] / (tp[r] + fp[r]) if tp[r] + fp[r] else 1.0
        rc = tp[r] / (tp[r] + fn[r]) if tp[r] + fn[r] else 1.0
        print(f"  {r:20} precision={p:.2f} recall={rc:.2f}")
        if rc < RECALL_THRESHOLD:
            failed.append(r)
    print(f"\ncases: {len(MUTATIONS)}  exact-match: {'all' if all_ok else 'NOT all'}")
    if failed or not all_ok:
        print(f"EVAL FAILED: {failed}")
        return 1
    print("EVAL PASSED")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-llm", action="store_true")
    sys.exit(asyncio.run(main(ap.parse_args().with_llm)))
