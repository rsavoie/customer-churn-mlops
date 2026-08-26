"""Baja el modelo entrenado del bucket de GCS a models/ (preparación de la clase 5).

Por qué existe: el lab de la clase 4 sube el modelo a `gs://<PROJECT>-churn/models/` y borra
la copia local. La API (`app.main` con `LocalModelBackend`) lo carga **de disco**, así que
antes de levantar `uvicorn` hay que recuperarlo. El mensaje docente es "el modelo vive en la
nube; lo bajamos como paso de preparación".

Correr desde la TERMINAL de Cloud Shell (ADC autentica con el proyecto de la sesión).
Requiere `google-cloud-storage` (ya está en requirements-gcp.txt):

    pip install -r requirements-gcp.txt

Uso:
    python scripts/download_model.py
    PROJECT_ID=mi-proyecto python scripts/download_model.py
    python scripts/download_model.py --project mi-proyecto --bucket otro-bucket

Si no hay GCP a mano, el fallback equivalente es reentrenar el modelo en segundos:
    python scripts/train_baseline.py
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# El modelo es obligatorio; las métricas son un extra útil (misma convención que la notebook
# de la clase 4, que sube ambos a models/).
DEFAULT_BLOBS = [
    "models/churn-baseline.joblib",
    "models/churn-baseline-metrics.json",
]


def resolve_project(explicit: str | None) -> str:
    """Resuelve el Project ID igual que la notebook: flag, luego env, luego gcloud."""
    project = (
        explicit
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("DEVSHELL_PROJECT_ID")
    )
    if not project:
        try:
            project = subprocess.run(
                ["gcloud", "config", "get-value", "project"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        except Exception:  # noqa: BLE001
            project = ""
    if not project or project == "(unset)":
        sys.exit(
            "No pude resolver el proyecto. Pasá --project o exportá GOOGLE_CLOUD_PROJECT."
        )
    return project


def main() -> None:
    parser = argparse.ArgumentParser(description="Baja el modelo de churn de GCS a models/.")
    parser.add_argument("--project", default=None, help="Project ID de GCP (default: env o gcloud).")
    parser.add_argument("--bucket", default=None, help="Nombre del bucket (default: <project>-churn).")
    parser.add_argument("--dest", default=ROOT / "models", type=Path, help="Carpeta destino local.")
    parser.add_argument(
        "--blob",
        action="append",
        dest="blobs",
        help="Objeto a bajar (repetible). Default: el modelo y sus métricas.",
    )
    args = parser.parse_args()

    project = resolve_project(args.project)
    bucket_name = args.bucket or f"{project}-churn"
    blobs = args.blobs or DEFAULT_BLOBS
    args.dest.mkdir(parents=True, exist_ok=True)

    try:
        from google.cloud import storage
    except ImportError:
        sys.exit(
            "Falta google-cloud-storage. Instalalo con: pip install -r requirements-gcp.txt"
        )

    print(f"Proyecto: {project} | Bucket: gs://{bucket_name}")
    client = storage.Client(project=project)
    bucket = client.bucket(bucket_name)

    descargados = 0
    for blob_name in blobs:
        blob = bucket.blob(blob_name)
        destino = args.dest / Path(blob_name).name
        if not blob.exists():
            if blob_name.endswith(".joblib"):
                sys.exit(
                    f"No existe gs://{bucket_name}/{blob_name}. "
                    "¿Corriste el lab de la clase 4? También podés reentrenarlo con "
                    "python scripts/train_baseline.py"
                )
            print(f"  (omito {blob_name}: no está en el bucket)")
            continue
        blob.download_to_filename(destino)
        print(f"  gs://{bucket_name}/{blob_name}  ->  {destino}")
        descargados += 1

    print(f"Listo: {descargados} archivo(s) en {args.dest}.")


if __name__ == "__main__":
    main()
