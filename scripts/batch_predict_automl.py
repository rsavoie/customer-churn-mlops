"""Batch prediction del modelo AutoML `churn-automl` con el SDK de Vertex AI.

Scorea todos los clientes del CSV en Cloud Storage y deja el resultado en
gs://<bucket>/automl-batch/. Correr desde la TERMINAL de Cloud Shell (auth por ADC).

Uso:
    python3 scripts/batch_predict_automl.py
    MODEL_ID=<id> python3 scripts/batch_predict_automl.py
"""
from __future__ import annotations

import os

from google.cloud import aiplatform

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("DEVSHELL_PROJECT_ID") or "mlops-itba-2026"
REGION = os.environ.get("REGION", "us-central1")
BUCKET = os.environ.get("BUCKET", f"gs://{PROJECT}-churn")
MODEL_ID = os.environ.get("MODEL_ID")  # churn-automl, especifico de TU proyecto
if not MODEL_ID:
    raise SystemExit(
        "Falta MODEL_ID. Cuando 'churn-automl' aparezca en Registro de modelos, corre:\n"
        "    MODEL_ID=<id-de-tu-modelo> python3 scripts/batch_predict_automl.py"
    )

aiplatform.init(project=PROJECT, location=REGION, staging_bucket=BUCKET)

model = aiplatform.Model(MODEL_ID)
print("Modelo:", model.display_name, MODEL_ID)

job = model.batch_predict(
    job_display_name="churn-automl-batch",
    gcs_source=f"{BUCKET}/raw/Telco-Customer-Churn.csv",
    gcs_destination_prefix=f"{BUCKET}/automl-batch",
    instances_format="csv",
    predictions_format="csv",
    sync=False,
)

try:
    job.wait_for_resource_creation()
except Exception as exc:  # noqa: BLE001
    print("(no se pudo esperar la creacion:", exc, ")")

print("Batch job:", getattr(job, "resource_name", "(ver en la consola)"))
print("Salida:", f"{BUCKET}/automl-batch/")
print("Monitorear en: "
      f"https://console.cloud.google.com/vertex-ai/batch-predictions?project={PROJECT}")

os._exit(0)  # el submit fue async; salimos sin colgar en el hilo de polling
