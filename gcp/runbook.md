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

## Clase 5, la API (serving local)

El lab corre en la **terminal** de Cloud Shell. Como el repo lo clonaron en la clase 4 y esta
clase suma `scripts/download_model.py`, arrancá actualizándolo:

```bash
cd customer-churn-mlops/
git pull
```

Antes de bajar nada, confirmá que la terminal está en la **misma cuenta y proyecto de la clase 4**.
Si no, `download_model.py` apuntaría al bucket de otro proyecto y fallaría con **403** (sin acceso) o
"no existe el modelo":

```bash
gcloud config get-value account   # tiene que ser tu cuenta de la clase 4
gcloud config get-value project   # tiene que ser tu proyecto de la clase 4
# Si el proyecto no es el correcto, fijalo (poné TU Project ID):
# gcloud config set project TU_PROYECTO_DE_LA_CLASE_4
```

El modelo quedó en el bucket al cerrar la clase 4 (la notebook lo subió a `models/` y borró la
copia local), así que el primer paso es **recuperarlo**:

```bash
python scripts/download_model.py
# Si el bucket no tiene el modelo (lo borraste, o corriste la notebook con otro dato), regeneralo
# corriendo de nuevo la notebook de la clase 4. Sin GCP a mano, el fallback local:
# python scripts/train_baseline.py
```

Levantá la API. El puerto **8080** es el que abre el **Web Preview** de Cloud Shell con un
click (botón "Vista previa en la Web", arriba a la derecha):

```bash
export MODEL_BACKEND="local"
export MODEL_PATH="models/churn-baseline.joblib"
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Con la API viva, el contrato se explora solo en **`/docs`** (Swagger UI que genera FastAPI):
abrí el Web Preview y agregá `/docs` a la URL.

Predicción online de un cliente:

```bash
curl -s -X POST "http://127.0.0.1:8080/predict" \
  -H "Content-Type: application/json" \
  --data @data/fixtures/customer-example.json
```

Scoring batch (devuelve la lista ordenada por `priority_score`):

```bash
curl -s -X POST "http://127.0.0.1:8080/batch-score" \
  -H "Content-Type: application/json" \
  --data @data/fixtures/batch-request.json
```

Validación del contrato: un payload con un campo mal tipado (acá `MonthlyCharges` como texto)
devuelve **422** con el detalle, **sin** tocar el modelo:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST "http://127.0.0.1:8080/predict" \
  -H "Content-Type: application/json" \
  --data @data/fixtures/invalid-example.json
```

Salud del servicio:

```bash
curl -s "http://127.0.0.1:8080/healthz"
```

> A diferencia de la clase 6, acá no queda nada desplegado: `uvicorn` es un proceso; al cerrar
> Cloud Shell se apaga y no genera costo. El servicio permanente con `https` público llega en
> la clase 6 con Cloud Run.

## Clase 6, Docker y Cloud Run

Entrenar el modelo local antes de construir la imagen:

```bash
python scripts/train_baseline.py
```

> **Por qué el modelo tiene que estar antes del build.** La imagen hornea el modelo
> (`COPY models ./models` en el `Dockerfile`), así que el `.joblib` tiene que existir en `models/`
> cuando se sube el contexto. El repo incluye un **`.gcloudignore`** justo para esto: sin él,
> `gcloud builds submit` cae de vuelta en `.gitignore` (que excluye `models/*.joblib`) y hornearía
> una imagen **sin modelo** → el servicio arranca pero `/healthz` devuelve `model_loaded: false`.
> El `.gcloudignore` mantiene el `.joblib` en el contexto y deja afuera lo que la imagen no necesita.

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

Arranca donde terminó la clase 6: la API ya está desplegada en Cloud Run. Recuperá la URL:

```bash
export SERVICE_URL="$(gcloud run services describe "${SERVICE}" --region "${REGION}" --format='value(status.url)')"
```

Si el repo estaba clonado de antes, actualizalo para traer las piezas nuevas de observabilidad
(`app/observability.py`, `scripts/smoke_load.py`, `scripts/check_drift.py`):

```bash
cd customer-churn-mlops/
git pull
```

### 1. Generar carga y medir latencia

`smoke_load.py` dispara N requests y reporta p50/p95/p99. El primer request paga el arranque en
frío (cold start) de Cloud Run; los siguientes salen tibios. Además, deja tráfico para leer en los logs.

```bash
python scripts/smoke_load.py --url "${SERVICE_URL}" --n 100
```

### 2. Leer logs estructurados

La API emite una línea JSON por predicción (latencia y decisión, sin datos personales). Cloud
Logging **parsea ese JSON a campos consultables** (`jsonPayload`), así que en vez de un `grep` se
filtra por campo y se piden las columnas que importan:

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND jsonPayload.event="prediction"' \
  --project "${PROJECT_ID}" --limit 6 \
  --format="table(jsonPayload.latency_ms, jsonPayload.decision, jsonPayload.churn_probability, jsonPayload.customer_id)"
```

> `gcloud run services logs read "${SERVICE}" --region "${REGION}"` muestra el flujo de requests
> (acceso). Las líneas JSON del app viajan a `jsonPayload`, no a texto plano, por eso los eventos
> de predicción se consultan con `gcloud logging read`.

### 3. Ver revisiones

Cada despliegue crea una revisión. Se listan con:

```bash
gcloud run revisions list --service "${SERVICE}" --region "${REGION}"
```

### 4. Romper a propósito: desplegar una revisión mala

El toggle `BREAK_MODEL=1` simula un despliegue roto (la carga del modelo falla). **Correr esto en
PowerShell si estás en Windows local** (Git Bash mangla los valores con `/` de `--set-env-vars`);
en Cloud Shell va tal cual:

```bash
gcloud run deploy "${SERVICE}" \
  --image "${IMAGE}" \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars MODEL_BACKEND=local,MODEL_PATH=/app/models/churn-baseline.joblib,BREAK_MODEL=1
```

Detectarlo, como lo detectaría el monitoreo: `/healthz` pasa a `degraded` y `/predict` corta con 503.

```bash
curl -s "${SERVICE_URL}/healthz"
python scripts/smoke_load.py --url "${SERVICE_URL}" --n 20   # ahora los códigos son 503
```

### 5. Rollback por tráfico

Sin reconstruir nada: se manda el 100% del tráfico a la última revisión buena (la de antes de
`BREAK_MODEL`). Ver el nombre en `revisions list` y reemplazar `REVISION_BUENA`:

```bash
gcloud run services update-traffic "${SERVICE}" \
  --region "${REGION}" \
  --to-revisions REVISION_BUENA=100
curl -s "${SERVICE_URL}/healthz"   # vuelve a "ok"
```

### 6. Drift offline (PSI)

Responde "¿el mundo que modelé sigue siendo el mismo?" sin infraestructura extra:

```bash
python scripts/check_drift.py   # referencia vs ventana de producción simulada
```

### 7. Monitoreo gestionado (la opción de plataforma)

- **Cloud Run**: Cloud Logging + métricas de latencia, tasa de error y conteo de requests (las que
  acabamos de ver a mano ya vienen en el dashboard del servicio).
- **Vertex AI**: si el modelo se sirve como endpoint de Vertex, activar **Model Monitoring** sobre
  el endpoint y definir umbrales de drift/skew (lo que hicimos con PSI, gestionado). Nunca muestrear
  payloads con datos sensibles.

Nota 2026: parte de la documentación histórica de Vertex AI aparece hoy bajo URLs de **Gemini Enterprise Agent Platform**. Las fuentes técnicas vigentes usadas para este runbook están listadas en `SOURCES.md`.

## Clase 8, integración y pre-demo

La clase 8 no despliega ni construye algo nuevo: ensambla las piezas de las clases 4 a 7 en una demo
desplegada y defendible, y verifica el **checklist de pre-demo** antes del coloquio.

Si el servicio quedó borrado en el cleanup de la clase 7, redesplegalo (mismos comandos de la clase 6)
y recuperá la URL:

```bash
gcloud run deploy "${SERVICE}" \
  --image "${IMAGE}" \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars MODEL_BACKEND=local,MODEL_PATH=/app/models/churn-baseline.joblib
export SERVICE_URL="$(gcloud run services describe "${SERVICE}" --region "${REGION}" --format='value(status.url)')"
```

### Verificar el checklist de pre-demo

`predemo_check.py` corre contra la URL la parte automatizable del checklist: que el servicio responda
con el modelo cargado, que el **contrato** esté publicado, que una **predicción real** devuelva
probabilidad y decisión, y que un dato inválido devuelva **422**. Solo librería estándar; corre en
Cloud Shell sin instalar nada.

```bash
python scripts/predemo_check.py --url "${SERVICE_URL}"
```

Devuelve código 0 si los cuatro chequeos pasan, 1 si alguno falla (por ejemplo, un servicio en
`degraded`, o una revisión rota que quedó sirviendo tráfico). Los puntos que no se ven desde afuera,
secretos sin credenciales en el repo, logs y una métrica mirados en la consola, video de respaldo y
fallback, quedan en la salida como recordatorio para tildar a mano.

> Antes de la demo, mandá un request de precalentamiento (o corré `predemo_check.py` dos veces): el
> primero paga el arranque en frío y el segundo muestra la latencia tibia real.

## Cleanup

Usar cleanup al final de la clase cuando los recursos ya no se necesiten:

```bash
gcloud run services delete "${SERVICE}" --region "${REGION}" --quiet
gcloud artifacts docker images delete "${IMAGE}" --quiet || true
```

Si se creó un endpoint en Vertex AI, undeploy y delete desde la consola o con `gcloud ai endpoints`.

> **Clase 7, ojo:** hoy queda un servicio corriendo (a diferencia de las clases 4 y 5). Con el
> escala a cero casi no cuesta, pero **lo que prendés, cuesta**: si no lo vas a usar, borralo con el
> comando de arriba. Si lo dejás vivo para el TFI, verificá que la **revisión buena** es la que sirve
> el tráfico (sin `BREAK_MODEL`): `curl -s "${SERVICE_URL}/healthz"` tiene que devolver `ok`.
