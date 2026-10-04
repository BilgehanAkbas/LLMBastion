"""Exercise the real Groq adapter with synthetic malformed SDK responses offline."""
import argparse
import io
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-only", action="store_true")
    args = parser.parse_args()
    os.chdir(ROOT)
    with tempfile.TemporaryDirectory(prefix="llmbastion-invalid-response-") as directory:
        os.environ.update(APP_ENV="development", DATABASE_URL="sqlite:///" + Path(directory, "audit.db").as_posix(),
                          LLM_PROVIDER="groq", RATE_LIMIT_BACKEND="memory", LOG_LEVEL="WARNING")
        from fastapi.testclient import TestClient
        import app.main as main_module
        from app.main import create_app
        from app.database import SessionLocal, engine
        from app.models import DetectorResult, GatewayRequest
        from app.providers.groq_provider import GroqProvider
        from app.routers import gateway
        from app.core.observability import StructuredJsonFormatter

        def completion(content):
            return NS(choices=[NS(message=NS(content=content))])

        canary = "synthetic-invalid-response-canary"
        fixtures = [
            ("null_content", completion(None)),
            ("empty_content", completion("")),
            ("whitespace_content", completion(" \n\t ")),
            ("empty_choices", NS(choices=[])),
            ("null_completion", None),
            ("missing_message", NS(choices=[NS()])),
            ("missing_choices", NS()),
            ("null_choices", NS(choices=None)),
            ("missing_content", NS(choices=[NS(message=NS())])),
            ("numeric_content", completion(12345)),
            ("float_content", completion(1.5)),
            ("bool_content", completion(True)),
            ("empty_object_content", completion({})),
            ("list_content", completion([])),
            ("text_object_content", completion({"text": "hello"})),
            ("object_content", completion({"unexpected": canary})),
        ]
        if args.timeout_only:
            import groq
            import httpx
            request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
            fixtures = [("sdk_timeout", groq.APITimeoutError(request=request))]
        buffer = io.StringIO()
        handler = logging.StreamHandler(buffer)
        handler.setFormatter(StructuredJsonFormatter())
        app_logger = logging.getLogger("app")
        app_logger.addHandler(handler)
        app_logger.setLevel(logging.INFO)
        adapter = GroqProvider(api_key="synthetic-test-key", model=gateway.GROQ_MODEL)
        rows = []
        try:
            with patch.object(gateway, "provider", adapter), patch.object(main_module, "gateway_provider", adapter), TestClient(create_app()) as client:
                for name, fixture in fixtures:
                    client.portal.call(adapter.close)
                    buffer.seek(0)
                    buffer.truncate(0)
                    create = AsyncMock(side_effect=fixture) if isinstance(fixture, Exception) else AsyncMock(return_value=fixture)
                    sdk = NS(close=AsyncMock(), chat=NS(completions=NS(create=create)))
                    with patch("groq.AsyncGroq", return_value=sdk) as constructor, patch.object(gateway.data_guard, "analyze", wraps=gateway.data_guard.analyze) as output_guard:
                        response = client.post("/api/v1/chat", json={"message": "Python'da list nedir?"})
                    body = response.json()
                    request_id = response.headers["X-Request-ID"]
                    with SessionLocal() as db:
                        audit = db.query(GatewayRequest).filter_by(request_id=request_id).one()
                        detectors = db.query(DetectorResult).filter_by(request_id=request_id).all()
                        provider_result = next(d for d in detectors if d.detector_name == "provider")
                        evidence = json.loads(provider_result.evidence)
                        persisted = json.dumps([d.evidence for d in detectors])
                    privacy = canary not in persisted + buffer.getvalue() + json.dumps(body)
                    safe_rejection = response.status_code == 502 and audit.action == "ERROR" and not body.get("response") and output_guard.call_count == 0
                    rows.append({"case_id": name, "mode": "synthetic_sdk_response", "provider": "groq", "model": adapter.model,
                                 "final_http_status": response.status_code, "audit_action": audit.action,
                                 "provider_error_type": evidence.get("error_type"), "provider_adapter_calls": constructor.call_count,
                                 "sdk_completion_calls": create.call_count,
                                 "provider_latency_ms": provider_result.latency_ms,
                                 "gateway_latency_ms": audit.latency_ms,
                                 "upstream_http_calls": 0, "data_guard_calls": output_guard.call_count,
                                 "response_returned": bool(body.get("response")), "privacy_check": privacy,
                                 "safe_rejection": safe_rejection, "passed": safe_rejection and privacy})
            report = {"runtime_changed": False, "summary": {"passed": sum(r["passed"] for r in rows), "total": len(rows)}, "cases": rows}
            destination = ROOT / "reports" / ("provider_timeout_security.json" if args.timeout_only else "invalid_provider_response_security.json")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report, indent=2))
            return 0 if all(r["passed"] for r in rows) else 1
        finally:
            app_logger.removeHandler(handler)
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
