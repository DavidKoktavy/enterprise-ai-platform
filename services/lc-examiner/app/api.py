"""Synchronous HTTP API (for UIs / ad-hoc checks) + K8s probes.

The Kafka worker (app.worker) is the primary, asynchronous integration path.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Query, Request

from .llm import GatewayClient
from .models import ExaminationResult
from .service import examine, parse_request

app = FastAPI(title="LC Examiner", version="1.0.0")
_gateway = GatewayClient() if os.getenv("GATEWAY_URL") else None


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.post("/v1/examine", response_model=ExaminationResult)
async def examine_endpoint(request: Request, use_llm: bool = Query(True)):
    req = parse_request(await request.body())
    return await examine(req, _gateway, use_llm=use_llm)
