from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import pandas as pd


FEATURE_COLUMNS = [
    "gender",
    "SeniorCitizen",
    "Partner",
    "Dependents",
    "tenure",
    "PhoneService",
    "MultipleLines",
    "InternetService",
    "OnlineSecurity",
    "OnlineBackup",
    "DeviceProtection",
    "TechSupport",
    "StreamingTV",
    "StreamingMovies",
    "Contract",
    "PaperlessBilling",
    "PaymentMethod",
    "MonthlyCharges",
    "TotalCharges",
]

NUMERIC_COLUMNS = ["SeniorCitizen", "tenure", "MonthlyCharges", "TotalCharges"]
CATEGORICAL_COLUMNS = [c for c in FEATURE_COLUMNS if c not in NUMERIC_COLUMNS]
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "churn-baseline.joblib"


@dataclass(frozen=True)
class ModelPrediction:
    churn_probability: float
    model_version: str
    backend: str


def normalize_features(record: dict[str, Any]) -> dict[str, Any]:
    normalized = {column: record.get(column) for column in FEATURE_COLUMNS}
    if normalized["TotalCharges"] in ("", None):
        normalized["TotalCharges"] = 0.0
    return normalized


def features_to_frame(records: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame([normalize_features(record) for record in records], columns=FEATURE_COLUMNS)
    for column in NUMERIC_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["TotalCharges"] = frame["TotalCharges"].fillna(0.0)
    return frame


class LocalModelBackend:
    backend_name = "local"

    def __init__(self, model_path: Path | str = DEFAULT_MODEL_PATH) -> None:
        self.model_path = Path(model_path)
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"No existe el modelo local en {self.model_path}. "
                "Entrenalo con: python scripts/train_baseline.py"
            )
        payload = joblib.load(self.model_path)
        if isinstance(payload, dict) and "pipeline" in payload:
            self.pipeline = payload["pipeline"]
            self.metadata = payload.get("metadata", {})
        else:
            self.pipeline = payload
            self.metadata = {}
        self.model_version = str(self.metadata.get("model_version", self.model_path.stem))

    def predict_one(self, record: dict[str, Any]) -> ModelPrediction:
        frame = features_to_frame([record])
        probability = positive_class_probability(self.pipeline, frame)
        return ModelPrediction(
            churn_probability=probability,
            model_version=self.model_version,
            backend=self.backend_name,
        )


class VertexModelBackend:
    backend_name = "vertex"

    def __init__(
        self,
        project: str | None = None,
        region: str | None = None,
        endpoint_id: str | None = None,
    ) -> None:
        self.project = project or os.getenv("GOOGLE_CLOUD_PROJECT")
        self.region = region or os.getenv("REGION", "us-central1")
        self.endpoint_id = endpoint_id or os.getenv("VERTEX_ENDPOINT_ID")
        if not self.project or not self.endpoint_id:
            raise ValueError("Para MODEL_BACKEND=vertex se requieren GOOGLE_CLOUD_PROJECT y VERTEX_ENDPOINT_ID.")

        from google.cloud import aiplatform

        aiplatform.init(project=self.project, location=self.region)
        endpoint_name = self.endpoint_id
        if not endpoint_name.startswith("projects/"):
            endpoint_name = f"projects/{self.project}/locations/{self.region}/endpoints/{self.endpoint_id}"
        self.endpoint = aiplatform.Endpoint(endpoint_name=endpoint_name)
        self.model_version = endpoint_name.rsplit("/", 1)[-1]

    def predict_one(self, record: dict[str, Any]) -> ModelPrediction:
        frame = features_to_frame([record])
        instance = frame.iloc[0].to_dict()
        response = self.endpoint.predict(instances=[instance])
        raw_prediction = response.predictions[0]
        probability = extract_churn_probability(raw_prediction)
        return ModelPrediction(
            churn_probability=probability,
            model_version=self.model_version,
            backend=self.backend_name,
        )


def positive_class_probability(pipeline: Any, frame: pd.DataFrame) -> float:
    probabilities = pipeline.predict_proba(frame)[0]
    classes = list(getattr(pipeline, "classes_", []))
    positive_candidates = [1, "1", "Yes", "Churn", True]
    for candidate in positive_candidates:
        if candidate in classes:
            return float(probabilities[classes.index(candidate)])
    if len(probabilities) == 2:
        return float(probabilities[1])
    raise ValueError(f"No se pudo identificar la clase positiva en {classes}.")


def extract_churn_probability(raw_prediction: Any) -> float:
    if isinstance(raw_prediction, dict):
        for key in ("churn_probability", "probability", "score"):
            if key in raw_prediction:
                return float(raw_prediction[key])
        classes = raw_prediction.get("classes") or raw_prediction.get("labels")
        scores = raw_prediction.get("scores") or raw_prediction.get("probabilities")
        if classes and scores:
            for positive in ("Yes", "Churn", "1", 1, True):
                if positive in classes:
                    return float(scores[classes.index(positive)])
        if "value" in raw_prediction:
            return float(raw_prediction["value"])
    if isinstance(raw_prediction, (list, tuple)) and len(raw_prediction) == 2:
        return float(raw_prediction[1])
    if isinstance(raw_prediction, (int, float)):
        return float(raw_prediction)
    raise ValueError(f"No se pudo interpretar la predicción de Vertex: {raw_prediction!r}")


def build_backend() -> LocalModelBackend | VertexModelBackend:
    # Interruptor didáctico (clase 7): simula un despliegue roto para practicar el rollback.
    # Con BREAK_MODEL activo la carga falla → /healthz devuelve "degraded" y /predict corta con 503,
    # sin tocar el código ni el modelo. Se prende al desplegar la "revisión mala" y se apaga al volver.
    if os.getenv("BREAK_MODEL", "").strip().lower() in ("1", "true", "yes", "on"):
        raise RuntimeError(
            "BREAK_MODEL activo: despliegue roto simulado (clase 7). "
            "Volvé a la revisión buena con: gcloud run services update-traffic."
        )
    backend = os.getenv("MODEL_BACKEND", "local").lower()
    if backend == "vertex":
        return VertexModelBackend()
    if backend == "local":
        model_path = Path(os.getenv("MODEL_PATH", str(DEFAULT_MODEL_PATH)))
        return LocalModelBackend(model_path)
    raise ValueError("MODEL_BACKEND debe ser local o vertex.")
