"""Cloud Function que conecta el disparador con el pipeline (clase 8 bonus: orquestación).

Es el **pegamento** entre Pub/Sub y Vertex AI Pipelines. Vertex no se suscribe solo a un topic;
algo tiene que escuchar el mensaje y llamar a la API. Esta función hace exactamente eso: está
suscripta al topic `churn-retrain` y, ante cada mensaje (lo publique Cloud Scheduler por tiempo,
`drift_gate.py` por drift, o un evento externo), lanza una corrida del pipeline.

Es una Cloud Function de 2da gen (corre sobre Cloud Run) con trigger de Pub/Sub, así que recibe
un CloudEvent. Usa el template **ya compilado y subido al bucket** (ver `vertex_pipeline.py --stage`).

Deploy (ver pipeline/trigger/README.md):
    gcloud functions deploy churn-retrain-trigger \
      --gen2 --runtime python312 --region us-central1 \
      --source pipeline/functions --entry-point trigger_retrain \
      --trigger-topic churn-retrain \
      --set-env-vars REGION=us-central1,BUCKET=${BUCKET},GATE_MIN=0.80
"""
import os

import functions_framework
from google.cloud import aiplatform


def _resolve_project() -> str:
    for key in ("BUCKET_PROJECT", "GCP_PROJECT", "GOOGLE_CLOUD_PROJECT", "PROJECT_ID"):
        value = os.environ.get(key)
        if value:
            return value
    import google.auth

    _, project = google.auth.default()
    if not project:
        raise RuntimeError("No pude resolver el proyecto (ni env ni credenciales por defecto).")
    return project


@functions_framework.cloud_event
def trigger_retrain(cloud_event) -> None:
    """Se dispara con cada mensaje al topic churn-retrain y lanza el pipeline."""
    project = _resolve_project()
    region = os.environ.get("REGION", "us-central1")
    bucket = os.environ.get("BUCKET", f"{project}-churn")
    gate_min = float(os.environ.get("GATE_MIN", "0.80"))
    template = f"gs://{bucket}/pipeline-root/churn_pipeline.json"

    aiplatform.init(project=project, location=region, staging_bucket=f"gs://{bucket}")
    job = aiplatform.PipelineJob(
        display_name="churn-retrain",
        template_path=template,
        pipeline_root=f"gs://{bucket}/pipeline-root",
        parameter_values={"bucket": bucket, "gate_min": gate_min},
        enable_caching=True,
    )
    job.submit()
    print(f"PipelineJob lanzado desde Pub/Sub: {job.resource_name}")
