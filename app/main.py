from __future__ import annotations

from fastapi import FastAPI, HTTPException

from app.model_backend import ModelPrediction, build_backend
from app.observability import configure_logging, log_event, measure_latency
from app.schemas import BatchScoreRequest, BatchScoreResponse, CustomerFeatures, PredictionResponse


app = FastAPI(
    title="MLOps 2026 Customer Churn API",
    version="0.1.0",
    description="API didáctica para el caso guía de Customer Churn.",
)

configure_logging()

_backend = None
RETENTION_THRESHOLD = 0.7


def model_to_dict(model: CustomerFeatures) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def get_backend():
    global _backend
    if _backend is None:
        _backend = build_backend()
    return _backend


def to_response(features: CustomerFeatures, prediction: ModelPrediction) -> PredictionResponse:
    monthly_charges = float(features.MonthlyCharges)
    probability = max(0.0, min(1.0, float(prediction.churn_probability)))
    return PredictionResponse(
        customer_id=features.customerID,
        churn_probability=round(probability, 6),
        churn_prediction=probability >= RETENTION_THRESHOLD,
        priority_score=round(probability * monthly_charges, 6),
        decision="retention_queue" if probability >= RETENTION_THRESHOLD else "monitor",
        backend=prediction.backend,
        model_version=prediction.model_version,
    )


@app.get("/healthz")
def healthz() -> dict:
    try:
        backend = get_backend()
        return {
            "status": "ok",
            "backend": backend.backend_name,
            "model_loaded": True,
            "model_version": backend.model_version,
        }
    except Exception as exc:
        return {
            "status": "degraded",
            "backend": "unavailable",
            "model_loaded": False,
            "detail": str(exc),
        }


def score_one(features: CustomerFeatures) -> PredictionResponse:
    """Corre el modelo y arma la respuesta. Sin logging: lo hacen los endpoints."""
    try:
        prediction = get_backend().predict_one(model_to_dict(features))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return to_response(features, prediction)


@app.post("/predict", response_model=PredictionResponse)
def predict(features: CustomerFeatures) -> PredictionResponse:
    with measure_latency() as timer:
        response = score_one(features)
    # Log estructurado: la decisión y la métrica, nunca las features crudas del cliente.
    log_event(
        "prediction",
        latency_ms=timer["latency_ms"],
        customer_id=response.customer_id,
        churn_probability=response.churn_probability,
        churn_prediction=response.churn_prediction,
        priority_score=response.priority_score,
        decision=response.decision,
        model_version=response.model_version,
        backend=response.backend,
    )
    return response


@app.post("/batch-score", response_model=BatchScoreResponse)
def batch_score(request: BatchScoreRequest) -> BatchScoreResponse:
    with measure_latency() as timer:
        responses = [score_one(features) for features in request.customers]
        responses.sort(key=lambda item: item.priority_score, reverse=True)
    log_event("batch_score", latency_ms=timer["latency_ms"], count=len(responses))
    return BatchScoreResponse(count=len(responses), predictions=responses)
