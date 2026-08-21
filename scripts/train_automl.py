"""Entrena un modelo AutoML Tabular con el SDK de Vertex AI.

Por qué por SDK y no por la consola: la opción "AutoML en canalizaciones" usa un
template KFP de Google que falla por un bug propio (parse-pipeline-inputs no encuentra
el output de get-artifact-resource-name). Este camino usa el backend legacy
`TrainingPipeline`, que evita ese template.

Correr desde la TERMINAL de Cloud Shell (ahí el SDK autentica por ADC con el proyecto
de la sesión). Requiere: pip install "google-cloud-aiplatform>=1.70,<2".

Uso:
    python3 scripts/train_automl.py            # reusa el dataset ya creado (DATASET_ID)
    DATASET_ID=<id> python3 scripts/train_automl.py
"""
from __future__ import annotations

import os

from google.cloud import aiplatform

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("DEVSHELL_PROJECT_ID") or "mlops-2026-itba"
REGION = os.environ.get("REGION", "us-central1")
BUCKET = os.environ.get("BUCKET", f"gs://{PROJECT}-churn")
# Dataset tabular 'churn' ya creado en Vertex (ver Conjuntos de datos).
DATASET_ID = os.environ.get("DATASET_ID", "7441626913061208064")

aiplatform.init(project=PROJECT, location=REGION, staging_bucket=BUCKET)

print(f"Proyecto: {PROJECT} | Region: {REGION} | Dataset: {DATASET_ID}")

ds = aiplatform.TabularDataset(DATASET_ID)

job = aiplatform.AutoMLTabularTrainingJob(
    display_name="churn-automl",
    optimization_prediction_type="classification",
    optimization_objective="maximize-au-roc",
)

# sync=False: submit y volver enseguida; el entrenamiento corre server-side ~1-2 h,
# no depende de que Cloud Shell siga abierto.
model = job.run(
    dataset=ds,
    target_column="Churn",
    budget_milli_node_hours=1000,  # 1 node-hour (minimo)
    model_display_name="churn-automl",
    disable_early_stopping=False,
    sync=False,
)

# Con sync=False el resource_name aparece cuando se crea el training pipeline.
try:
    job.wait_for_resource_creation()
except Exception as exc:  # noqa: BLE001
    print("(no se pudo esperar la creacion del recurso:", exc, ")")

print("Training pipeline:", getattr(job, "resource_name", "(ver en la consola)"))
print(
    "Monitorear en: "
    f"https://console.cloud.google.com/vertex-ai/training/training-pipelines?project={PROJECT}"
)
print("Cuando termine, el modelo 'churn-automl' aparece en Registro de modelos con su evaluacion.")
