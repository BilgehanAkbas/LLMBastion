"""Local gateway latency with real Groq SDK + synthetic HTTP transport, no network."""
import asyncio
import io
import json
import logging
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CANARY = "synthetic-private-upstream-detail"


def main():
    os.chdir(ROOT)
    with tempfile.TemporaryDirectory(prefix="llmbastion-provider-latency-") as directory:
        os.environ.update(APP_ENV="development", DATABASE_URL="sqlite:///" + Path(directory, "audit.db").as_posix(),
                          GROQ_TIMEOUT_SECONDS="20", GROQ_MAX_RETRIES="0", RATE_LIMIT_BACKEND="memory",
                          RATE_LIMIT_REQUESTS="100", LOG_LEVEL="WARNING")
        import groq
        import httpx
        from fastapi.testclient import TestClient
        import app.main as main_module
        from app.core.observability import StructuredJsonFormatter
        from app.database import SessionLocal, engine
        from app.models import DetectorResult, GatewayRequest
        from app.providers.factory import build_provider
        from app.routers import gateway

        gateway.semantic_guard.ensure_ready()
        real_constructor = groq.AsyncGroq
        output_analyze = gateway.data_guard.analyze
        buffer = io.StringIO()
        handler = logging.StreamHandler(buffer)
        handler.setFormatter(StructuredJsonFormatter())
        logger = logging.getLogger("app")
        logger.addHandler(handler)
        rows = []
        try:
            for retries in (0, 2):
                state = {"scenario": "normal", "attempts": 0}
                async def handle(request):
                    state["attempts"] += 1
                    await asyncio.sleep(0.01)
                    if state["scenario"] == "timeout":
                        raise httpx.ReadTimeout(CANARY, request=request)
                    if state["scenario"] in ("429", "500"):
                        return httpx.Response(int(state["scenario"]), json={"error": {"message": CANARY}},
                                              headers={"retry-after": "0.02"})
                    return httpx.Response(200, json={
                        "id": "synthetic", "object": "chat.completion", "created": 0, "model": "synthetic-model",
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": "Synthetic normal answer"}, "finish_reason": "stop"}],
                    })
                def construct(**kwargs):
                    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
                    return real_constructor(**kwargs, http_client=client)
                provider = build_provider("groq", groq_api_key="synthetic-key", groq_model="synthetic-model",
                                          groq_timeout_seconds=20, groq_max_retries=retries)
                constructor = Mock(side_effect=construct)
                with patch.object(gateway, "provider", provider), patch.object(main_module, "gateway_provider", provider), \
                        patch("groq.AsyncGroq", constructor), \
                        patch.object(groq._base_client.AsyncAPIClient, "_calculate_retry_timeout", return_value=0.02), \
                        TestClient(main_module.create_app()) as client:
                    # Warm the guards, DB connection and pooled SDK client before timing.
                    client.post("/api/v1/chat", json={"message": "Python'da list nedir?"})
                    for scenario in ("normal", "timeout", "429", "500"):
                        state["scenario"] = scenario
                        for trial in range(3):
                            state["attempts"] = 0
                            buffer.seek(0)
                            buffer.truncate(0)
                            started = time.perf_counter()
                            with patch.object(gateway.data_guard, "analyze", wraps=output_analyze) as output_guard:
                                response = client.post("/api/v1/chat", json={"message": "Python'da list nedir?"})
                            elapsed = (time.perf_counter() - started) * 1000
                            body = response.json()
                            with SessionLocal() as db:
                                request_id = response.headers["X-Request-ID"]
                                audit = db.query(GatewayRequest).filter_by(request_id=request_id).one()
                                detectors = db.query(DetectorResult).filter_by(request_id=request_id).all()
                                telemetry = next(d for d in detectors if d.detector_name == "provider")
                                evidence = json.dumps([d.evidence for d in detectors])
                            normal = scenario == "normal"
                            privacy = CANARY not in json.dumps(body) + evidence + buffer.getvalue()
                            passed = response.status_code == (200 if normal else 502)
                            passed &= audit.action == ("ALLOW" if normal else "ERROR")
                            passed &= output_guard.call_count == (1 if normal else 0)
                            passed &= state["attempts"] == (1 if normal else retries + 1)
                            passed &= bool(body.get("response")) == normal and privacy
                            rows.append({"scenario": scenario, "trial": trial + 1, "max_retries": retries,
                                         "sdk_http_attempts": state["attempts"], "http_status": response.status_code,
                                         "audit_action": audit.action, "data_guard_calls": output_guard.call_count,
                                         "provider_latency_ms": round(telemetry.latency_ms, 3),
                                         "gateway_latency_ms": round(elapsed, 3), "privacy_check": privacy,
                                         "client_constructor_calls": constructor.call_count, "passed": bool(passed)})
            summary = []
            for retries in (0, 2):
                for scenario in ("normal", "timeout", "429", "500"):
                    selected = [r for r in rows if r["max_retries"] == retries and r["scenario"] == scenario]
                    summary.append({"max_retries": retries, "scenario": scenario,
                                    "http_attempts_per_request": selected[0]["sdk_http_attempts"],
                                    "mean_provider_latency_ms": round(statistics.mean(r["provider_latency_ms"] for r in selected), 3),
                                    "mean_gateway_latency_ms": round(statistics.mean(r["gateway_latency_ms"] for r in selected), 3)})
            report = {"synthetic_only": True, "network_calls": 0, "runtime_policy": {"timeout_seconds": 20, "max_retries": 0},
                      "comparison_retries": 2, "synthetic_attempt_delay_ms": 10, "synthetic_retry_backoff_ms": 20,
                      "real_timeout_duration_measured": False, "total_deadline_implemented": True, "total_deadline_seconds": gateway.GROQ_TOTAL_DEADLINE_SECONDS,
                      "summary": summary, "passed": sum(r["passed"] for r in rows), "total": len(rows), "cases": rows}
            destination = ROOT / "reports/provider_latency_policy.json"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"passed": report["passed"], "total": report["total"], "summary": summary}, indent=2))
            return 0 if all(r["passed"] for r in rows) else 1
        finally:
            logger.removeHandler(handler)
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
