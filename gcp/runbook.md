# Runbook GCP, Customer Churn

Este runbook acompaña el hilo conductor de Churn en las clases 4 a 7. Está escrito para la **terminal**
de Cloud Shell (con `gcloud` autenticado).

> Para el lab de la clase 4 dentro del **editor** de Cloud Shell, usar la notebook
> `notebooks/c04_vertex_cloudshell.ipynb`, que habla con la nube por las librerías Python de Google
> (`google-cloud-storage`). Motivo: el kernel del editor no hereda el entorno de la sesión y `gcloud`
> desde ahí queda sin proyecto ni auth. Los comandos `gcloud` de este runbook son para la terminal.

## Variables base

```bash
export PROJECT_ID="$(gcloud config get-value project)"
export REGION="us-central1"
export BUCKET="${PROJECT_ID}-churn"
export REPO="mlops-2026"
export SERVICE="churn-api"
export IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE}:latest"
```

## APIs necesarias

Las APIs se habilitan **por proyecto**: un proyecto nuevo nace con casi todo apagado, así que hay que
prenderlas de nuevo en cada proyecto. Habilitar una API es gratis (se paga el uso, no tenerla encendida).

Ver qué está habilitado (por si ya estaban):

```bash
gcloud services list --enabled
```

**Clase 4** (dato a la nube, entrenamiento y batch) — el mínimo son dos:

```bash
gcloud services enable aiplatform.googleapis.com storage.googleapis.com
```

**Clases 6-7** (imagen, build y Cloud Run), cuando lleguen:

```bash
gcloud services enable artifactregistry.googleapis.com cloudbuild.googleapis.com run.googleapis.com
```

> `gcloud services enable` y `gcloud services list` son idénticos en bash (Cloud Shell) y en PowerShell
> (local): solo cambia el shell alrededor, no la línea de gcloud. Requiere billing vinculado al proyecto.

## Dataset en Cloud Storage

Verificar primero la copia local canónica:

```bash
python scripts/verify_dataset.py
sha256sum data/raw/Telco-Customer-Churn.csv
```

El SHA-256 esperado está documentado en `SOURCES.md` y en `data/raw/Telco-Customer-Churn.csv.sha256`.

```bash
gcloud storage buckets create "gs://${BUCKET}" --location="${REGION}" || true
gcloud storage cp data/raw/Telco-Customer-Churn.csv "gs://${BUCKET}/raw/Telco-Customer-Churn.csv"
gcloud storage cp data/raw/Telco-Customer-Churn.csv.sha256 "gs://${BUCKET}/raw/Telco-Customer-Churn.csv.sha256"
gcloud storage ls "gs://${BUCKET}/raw/"
```

## Clase 4, Vertex AI y batch

**El lab en vivo** corre en la notebook `notebooks/c04_vertex_cloudshell.ipynb` (editor de Cloud Shell):
sube el dato, entrena a mano (sklearn, segundos), scorea batch y arma el ranking. Deja el bucket con
`raw/`, `models/` y `scored/`. Ese es el camino que se corre en clase.

**AutoML gestionado (opcional, "para que lo veas").** Vertex puede entrenar solo desde un dataset
tabular. El flujo conceptual:

1. Crear un dataset tabular en Vertex desde `gs://${BUCKET}/raw/Telco-Customer-Churn.csv`.
2. Entrenar clasificación binaria con `Churn` como target.
3. Revisar las métricas de evaluación (ROC AUC, PR AUC, precision/recall).
4. Registrar el modelo en el Model Registry.
5. Ejecutar batch prediction sobre los clientes.
6. Ordenar por `churn_probability * MonthlyCharges`.

> **Importante:** corré esto por **SDK, desde la TERMINAL** (no el editor), con los scripts de abajo.
> La opción "AutoML en canalizaciones" de la consola usa un template KFP de Google que **falla** por un
> bug propio (`parse-pipeline-inputs`, "Failed to find property `output:Output`"). El SDK usa otro
> backend (`TrainingPipeline` legacy) y sí funciona. Además, el AutoML tarda ~2 h y consume crédito,
> por eso se pre-hornea, no se corre en vivo.

Preparación (una vez):

```bash
pip install -q "google-cloud-aiplatform>=1.70,<2"

# Crear el dataset tabular 'churn' en la consola (Vertex -> Conjuntos de datos -> Crear ->
# Tabular -> importar el CSV de gs://${BUCKET}/raw/Telco-Customer-Churn.csv) y anotar su ID.

# La cuenta de servicio de Compute necesita leer/escribir el bucket:
export SA="$(gcloud projects describe ${PROJECT_ID} --format='value(projectNumber)')-compute@developer.gserviceaccount.com"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA}" --role="roles/storage.admin" --condition=None
```

Entrenar y scorear (asíncronos; el training corre server-side ~2 h, no depende de Cloud Shell):

```bash
DATASET_ID=<id-del-dataset> python scripts/train_automl.py
# Cuando el modelo 'churn-automl' aparezca en Registro de modelos con su evaluacion:
MODEL_ID=<id-del-modelo> python scripts/batch_predict_automl.py
```

La salida del batch queda en `gs://${BUCKET}/automl-batch/`. En el dry-run el AutoML sacó **ROC AUC
0.895** (mejor que el baseline sklearn `0.842`), a costa de ~2 h y crédito.

**Demo local equivalente** (a mano, sin nube):

```bash
python scripts/verify_dataset.py
python scripts/train_baseline.py
python scripts/score_batch.py --input data/fixtures/batch-input.csv
```

## Clase 5, API local

```bash
export MODEL_BACKEND="local"
export MODEL_PATH="models/churn-baseline.joblib"
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Prueba:

```bash
curl -s -X POST "http://127.0.0.1:8000/predict" \
  -H "Content-Type: application/json" \
  --data @data/fixtures/customer-example.json
```

## Clase 6, Docker y Cloud Run

Entrenar el modelo local antes de construir la imagen:

```bash
python scripts/train_baseline.py
```

Crear Artifact Registry:

```bash
gcloud artifacts repositories create "${REPO}" \
  --repository-format=docker \
  --location="${REGION}" \
  --description="Artefactos MLOps 2026" || true
```

Construir y publicar:

```bash
gcloud builds submit --tag "${IMAGE}" .
```

Desplegar en Cloud Run:

```bash
gcloud run deploy "${SERVICE}" \
  --image "${IMAGE}" \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars MODEL_BACKEND=local,MODEL_PATH=/app/models/churn-baseline.joblib
```

Probar el servicio:

```bash
export SERVICE_URL="$(gcloud run services describe "${SERVICE}" --region "${REGION}" --format='value(status.url)')"
curl -s "${SERVICE_URL}/healthz"
curl -s -X POST "${SERVICE_URL}/predict" \
  -H "Content-Type: application/json" \
  --data @data/fixtures/customer-example.json
```

## Clase 7, operación

Mirar logs:

```bash
gcloud run services logs read "${SERVICE}" --region "${REGION}" --limit 50
```

Ver revisiones:

```bash
gcloud run revisions list --service "${SERVICE}" --region "${REGION}"
```

Rollback por tráfico, reemplazando `REVISION_BUENA`:

```bash
gcloud run services update-traffic "${SERVICE}" \
  --region "${REGION}" \
  --to-revisions REVISION_BUENA=100
```

Monitoreo gestionado en Vertex AI:

- Para endpoint de Vertex: activar Model Monitoring sobre el endpoint y definir umbrales de drift/skew.
- Para Cloud Run: usar Cloud Logging, métricas de latencia, tasa de error, conteo de requests y muestras de payload sin datos sensibles.

Nota 2026: parte de la documentación histórica de Vertex AI aparece hoy bajo URLs de **Gemini Enterprise Agent Platform**. Las fuentes técnicas vigentes usadas para este runbook están listadas en `SOURCES.md`.

## Cleanup

Usar cleanup al final de la clase cuando los recursos ya no se necesiten:

```bash
gcloud run services delete "${SERVICE}" --region "${REGION}" --quiet
gcloud artifacts docker images delete "${IMAGE}" --quiet || true
```

Si se creó un endpoint en Vertex AI, undeploy y delete desde la consola o con `gcloud ai endpoints`.
