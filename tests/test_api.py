from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient

import app.main as main_module
from app import observability
from app.model_backend import ModelPrediction


class FakeBackend:
    backend_name = "local"
    model_version = "test-model"

    def predict_one(self, record):
        probability = 0.8 if float(record["MonthlyCharges"]) >= 50 else 0.2
        return ModelPrediction(churn_probability=probability, model_version=self.model_version, backend=self.backend_name)


def example_payload(monthly_charges=70.7):
    return {
        "customerID": "9237-HQITU",
        "gender": "Female",
        "SeniorCitizen": 0,
        "Partner": "No",
        "Dependents": "No",
        "tenure": 2,
        "PhoneService": "Yes",
        "MultipleLines": "No",
        "InternetService": "Fiber optic",
        "OnlineSecurity": "No",
        "OnlineBackup": "No",
        "DeviceProtection": "No",
        "TechSupport": "No",
        "StreamingTV": "No",
        "StreamingMovies": "No",
        "Contract": "Month-to-month",
        "PaperlessBilling": "Yes",
        "PaymentMethod": "Electronic check",
        "MonthlyCharges": monthly_charges,
        "TotalCharges": 151.65,
    }


def make_client(monkeypatch):
    monkeypatch.setattr(main_module, "_backend", FakeBackend())
    return TestClient(main_module.app)


def test_health_reports_loaded_model(monkeypatch):
    client = make_client(monkeypatch)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["model_loaded"] is True


def test_predict_contract(monkeypatch):
    client = make_client(monkeypatch)
    response = client.post("/predict", json=example_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["customer_id"] == "9237-HQITU"
    assert body["churn_probability"] == 0.8
    assert body["churn_prediction"] is True
    assert body["priority_score"] == 56.56
    assert body["decision"] == "retention_queue"
    assert body["backend"] == "local"
    assert body["model_version"] == "test-model"


def test_invalid_payload_returns_422(monkeypatch):
    client = make_client(monkeypatch)
    payload = example_payload()
    payload.pop("MonthlyCharges")
    response = client.post("/predict", json=payload)
    assert response.status_code == 422


def test_batch_score_is_sorted_by_priority(monkeypatch):
    client = make_client(monkeypatch)
    response = client.post(
        "/batch-score",
        json={"customers": [example_payload(29.85), example_payload(70.7)]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert body["predictions"][0]["priority_score"] > body["predictions"][1]["priority_score"]


def test_predict_emits_structured_log_without_pii(monkeypatch):
    events = []
    monkeypatch.setattr(main_module, "log_event", lambda event, **fields: events.append((event, fields)))
    client = make_client(monkeypatch)
    client.post("/predict", json=example_payload())
    assert events, "el endpoint debe emitir un evento estructurado"
    event, fields = events[0]
    assert event == "prediction"
    assert "latency_ms" in fields
    assert fields["decision"] in ("retention_queue", "monitor")
    # Regla de la clase 7: nunca loguear features crudas del cliente (evitar PII).
    for leaked in ("gender", "PaymentMethod", "MonthlyCharges", "tenure", "TotalCharges"):
        assert leaked not in fields


def test_log_event_is_valid_json_line():
    records: list[str] = []
    handler = logging.Handler()
    handler.emit = lambda record: records.append(record.getMessage())
    observability.logger.addHandler(handler)
    try:
        observability.log_event("prediction", latency_ms=1.2, decision="monitor")
    finally:
        observability.logger.removeHandler(handler)
    payload = json.loads(records[-1])
    assert payload["event"] == "prediction"
    assert payload["latency_ms"] == 1.2
    assert payload["decision"] == "monitor"


def test_break_model_toggle_degrades_service(monkeypatch):
    # Simula el "despliegue roto" del rollback: sin fake backend, build_backend debe fallar.
    monkeypatch.setenv("BREAK_MODEL", "1")
    monkeypatch.setattr(main_module, "_backend", None)
    client = TestClient(main_module.app)
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["model_loaded"] is False
    assert client.post("/predict", json=example_payload()).status_code == 503
