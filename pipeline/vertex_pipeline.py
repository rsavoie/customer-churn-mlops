"""Pipeline de Churn en Vertex AI Pipelines (KFP v2) — clase 8 bonus: orquestación.

El mismo grafo que `pipeline/run_local.py`, pero **gestionado por la nube**: cada paso es un
**componente** que corre en su propio contenedor, Vertex arma el DAG, versiona los artefactos,
cachea los pasos que no cambiaron y dibuja el grafo en la consola.

    verificar dato  ->  entrenar  ->  [gate ROC AUC]  ->  promover modelo al bucket

Nota (el hilo que dejó abierto la clase 4): el runbook evita la opción "AutoML en
canalizaciones" de la consola porque su template KFP de Google falla por un bug propio. Este
pipeline es KFP v2 **escrito a mano** sobre los pasos livianos (sklearn), otro camino que sí
funciona y corre en minutos.

Uso:
    python pipeline/vertex_pipeline.py --compile         # solo compila el JSON (no toca la nube)
    python pipeline/vertex_pipeline.py                   # compila y lanza en Vertex
    python pipeline/vertex_pipeline.py --gate-min 0.80   # umbral del gate de calidad

Requiere `kfp>=2` para compilar y `google-cloud-aiplatform` para lanzar (ver requirements-gcp.txt).
El proyecto se resuelve por flag, luego env (GOOGLE_CLOUD_PROJECT), luego `gcloud config`, igual
que scripts/download_model.py.

Nota para quien edite: los componentes KFP NO pueden usar `from __future__ import annotations`
(convierte las anotaciones en strings y rompe la introspección de tipos de KFP).
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

from kfp import compiler, dsl
from kfp.dsl import Input, Model, Output

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT / "pipeline" / "churn_pipeline.json"
RAW_BLOB = "raw/Telco-Customer-Churn.csv"
MODEL_BLOB = "models/churn-baseline.joblib"

# Columnas del caso (mismas que app/model_backend.py). Se repiten acá a propósito: cada
# componente corre aislado en su contenedor y no puede importar el código del repo.
FEATURE_COLUMNS = [
    "gender", "SeniorCitizen", "Partner", "Dependents", "tenure", "PhoneService",
    "MultipleLines", "InternetService", "OnlineSecurity", "OnlineBackup", "DeviceProtection",
    "TechSupport", "StreamingTV", "StreamingMovies", "Contract", "PaperlessBilling",
    "PaymentMethod", "MonthlyCharges", "TotalCharges",
]
NUMERIC_COLUMNS = ["SeniorCitizen", "tenure", "MonthlyCharges", "TotalCharges"]
CATEGORICAL_COLUMNS = [c for c in FEATURE_COLUMNS if c not in NUMERIC_COLUMNS]

DATA_PACKAGES = ["pandas", "gcsfs", "fsspec"]
TRAIN_PACKAGES = ["pandas", "scikit-learn", "joblib", "gcsfs", "fsspec"]


@dsl.component(base_image="python:3.11", packages_to_install=DATA_PACKAGES)
def verify_data(bucket: str, expected_rows: int = 7043) -> str:
    """Paso 1: integridad del dato. Lee el CSV del bucket y valida forma y label."""
    import pandas as pd

    gcs_csv_uri = f"gs://{bucket}/raw/Telco-Customer-Churn.csv"
    frame = pd.read_csv(gcs_csv_uri)
    if len(frame) != expected_rows:
        raise ValueError(f"Se esperaban {expected_rows} filas y hay {len(frame)}.")
    if "Churn" not in frame.columns:
        raise ValueError("Falta la columna Churn.")
    print(f"OK dataset: {len(frame)} filas, {len(frame.columns)} columnas.")
    return gcs_csv_uri


@dsl.component(base_image="python:3.11", packages_to_install=TRAIN_PACKAGES)
def train_model(
    gcs_csv_uri: str,
    model: Output[Model],
    feature_columns: list,
    numeric_columns: list,
    categorical_columns: list,
) -> float:
    """Paso 2: entrena el baseline (LogisticRegression) y devuelve el ROC AUC."""
    import joblib
    import pandas as pd
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    frame = pd.read_csv(gcs_csv_uri)
    frame["TotalCharges"] = pd.to_numeric(frame["TotalCharges"], errors="coerce").fillna(0.0)
    features = frame[feature_columns].copy()
    target = frame["Churn"].map({"No": 0, "Yes": 1}).astype(int)

    numeric = Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())])
    categorical = Pipeline(
        [("imputer", SimpleImputer(strategy="most_frequent")),
         ("encoder", OneHotEncoder(handle_unknown="ignore", sparse_output=False))]
    )
    preprocessor = ColumnTransformer(
        [("numeric", numeric, numeric_columns), ("categorical", categorical, categorical_columns)]
    )
    estimator = Pipeline(
        [("preprocessor", preprocessor),
         ("classifier", LogisticRegression(max_iter=1000, class_weight="balanced"))]
    )

    x_train, x_test, y_train, y_test = train_test_split(
        features, target, test_size=0.2, random_state=42, stratify=target
    )
    estimator.fit(x_train, y_train)
    roc_auc = float(roc_auc_score(y_test, estimator.predict_proba(x_test)[:, 1]))
    joblib.dump({"pipeline": estimator, "metadata": {"roc_auc": roc_auc}}, model.path)
    print(f"Modelo entrenado. ROC AUC = {roc_auc:.4f}")
    return roc_auc


@dsl.component(base_image="python:3.11")
def quality_gate(roc_auc: float, gate_min: float) -> bool:
    """Paso 3: el gate. Si el modelo no llega al umbral, FALLA y corta el pipeline."""
    print(f"ROC AUC={roc_auc:.4f} | umbral={gate_min:.4f}")
    if roc_auc < gate_min:
        raise ValueError(
            f"GATE: ROC AUC {roc_auc:.4f} < umbral {gate_min:.4f}. No se promueve el modelo."
        )
    print("GATE en verde: el modelo puede promoverse.")
    return True


@dsl.component(base_image="python:3.11", packages_to_install=["gcsfs", "fsspec"])
def promote_model(bucket: str, model: Input[Model], approved: bool) -> str:
    """Paso 4: promueve el modelo aprobado al bucket, donde la API lo lee.

    En una plataforma gestionada, este paso es 'registrar en Vertex Model Registry'. Acá lo
    copiamos a gs://<bucket>/models/, que es de donde el servicio de Cloud Run baja el modelo:
    así el pipeline cierra el loop con el despliegue de las clases 5-6.
    """
    import shutil

    import gcsfs

    if not approved:
        raise ValueError("El modelo no fue aprobado por el gate; no se promueve.")
    destino = f"gs://{bucket}/models/churn-baseline.joblib"
    fs = gcsfs.GCSFileSystem()
    with open(model.path, "rb") as origen, fs.open(destino, "wb") as remoto:
        shutil.copyfileobj(origen, remoto)
    print(f"Modelo promovido a {destino}")
    return destino


@dsl.pipeline(name="churn-retrain", description="Pipeline de reentrenamiento de Churn (MLOps 2026).")
def churn_pipeline(bucket: str, gate_min: float = 0.80) -> None:
    verificado = verify_data(bucket=bucket)
    entrenado = train_model(
        gcs_csv_uri=verificado.output,
        feature_columns=FEATURE_COLUMNS,
        numeric_columns=NUMERIC_COLUMNS,
        categorical_columns=CATEGORICAL_COLUMNS,
    )
    aprobado = quality_gate(roc_auc=entrenado.outputs["Output"], gate_min=gate_min)
    promote_model(bucket=bucket, model=entrenado.outputs["model"], approved=aprobado.output)


def resolve_project(explicit: str | None) -> str:
    """Resuelve el Project ID: flag, luego env, luego gcloud (igual que download_model.py)."""
    project = explicit or os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("DEVSHELL_PROJECT_ID")
    if not project:
        try:
            project = subprocess.run(
                ["gcloud", "config", "get-value", "project"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
        except Exception:  # noqa: BLE001
            project = ""
    if not project or project == "(unset)":
        sys.exit("No pude resolver el proyecto. Pasá --project o exportá GOOGLE_CLOUD_PROJECT.")
    return project


def stage_template(project: str, bucket: str) -> str:
    """Sube el template compilado a gs://<bucket>/pipeline-root/, para que lo use la Cloud
    Function del disparador (pipeline/functions/main.py). El submit directo usa el local; la
    Function necesita el template en GCS porque no tiene el repo a mano."""
    from google.cloud import storage

    destino = "pipeline-root/churn_pipeline.json"
    client = storage.Client(project=project)
    client.bucket(bucket).blob(destino).upload_from_filename(str(TEMPLATE_PATH))
    uri = f"gs://{bucket}/{destino}"
    print(f"Template subido a {uri} (lo usa la Cloud Function del trigger).")
    return uri


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline de Churn en Vertex AI Pipelines (KFP v2).")
    parser.add_argument("--compile", action="store_true", help="Solo compila el JSON, sin lanzar.")
    parser.add_argument("--stage", action="store_true", help="Compila y sube el template al bucket (para el trigger).")
    parser.add_argument("--project", default=None, help="Project ID (default: env o gcloud).")
    parser.add_argument("--region", default=os.environ.get("REGION", "us-central1"))
    parser.add_argument("--bucket", default=None, help="Bucket (default: <project>-churn).")
    parser.add_argument("--gate-min", type=float, default=0.80, help="ROC AUC mínimo del gate.")
    args = parser.parse_args()

    compiler.Compiler().compile(pipeline_func=churn_pipeline, package_path=str(TEMPLATE_PATH))
    print(f"Pipeline compilado en {TEMPLATE_PATH}")
    if args.compile:
        return

    project = resolve_project(args.project)
    bucket = args.bucket or f"{project}-churn"

    if args.stage:
        stage_template(project, bucket)
        return

    from google.cloud import aiplatform

    aiplatform.init(project=project, location=args.region, staging_bucket=f"gs://{bucket}")
    job = aiplatform.PipelineJob(
        display_name="churn-retrain",
        template_path=str(TEMPLATE_PATH),
        pipeline_root=f"gs://{bucket}/pipeline-root",
        parameter_values={"bucket": bucket, "gate_min": args.gate_min},
        enable_caching=True,
    )
    print(f"Lanzando el pipeline en Vertex (proyecto {project}, región {args.region})...")
    job.submit()
    print("Pipeline lanzado. Seguí el grafo en la consola: Vertex AI -> Pipelines.")


if __name__ == "__main__":
    main()
