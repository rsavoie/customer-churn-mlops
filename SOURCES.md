# Fuentes y reproducibilidad, Customer Churn

Este archivo deja trazado el origen del caso **Customer Churn** para poder reproducirlo en una
máquina local, en Cloud Shell o en GCP.

## Resumen reproducible

- Caso guía: **Customer Churn** sobre un dataset de telecomunicaciones.
- Dataset canónico local: `data/raw/Telco-Customer-Churn.csv`.
- Archivo de checksum: `data/raw/Telco-Customer-Churn.csv.sha256`.
- SHA-256 esperado: `16320c9c1ec72448db59aa0a26a0b95401046bef5d02fd3aeb906448e3055e91`.
- Tamaño local observado: **970.457 bytes**.
- Forma esperada: **7.043 registros** y **21 columnas**.
- Label: `Churn`, con `Yes` como clase positiva.
- Identificador: `customerID`, conservado para trazabilidad y excluido del entrenamiento.

## Fuente de datos

- Repositorio IBM: <https://github.com/IBM/telco-customer-churn-on-icp4d>
- CSV crudo: <https://raw.githubusercontent.com/IBM/telco-customer-churn-on-icp4d/master/data/Telco-Customer-Churn.csv>
- Licencia del repositorio fuente: Apache 2.0, <https://github.com/IBM/telco-customer-churn-on-icp4d/blob/master/LICENSE>
- Estado de la fuente al consultar: repositorio archivado por IBM el **2024-07-22**, de solo lectura.

La copia local del CSV queda versionada en este repo para no depender de que el branch `master` del
origen siga disponible o mantenga exactamente los mismos bytes. Si en el futuro se refresca el dataset
desde el origen, comparar primero el hash y registrar el cambio en este archivo.

## Reglas del caso

- `Churn=Yes` se transforma en clase positiva.
- `customerID` no entra al entrenamiento.
- `MonthlyCharges` se usa como aproximación simple de valor mensual.
- `priority_score = churn_probability * MonthlyCharges`.
- La decisión inicial es `retention_queue` cuando `churn_probability >= 0.7`; en el resto, `monitor`.

## Transformaciones

El archivo `data/raw/Telco-Customer-Churn.csv` se conserva como dato crudo. Las transformaciones viven
en código reproducible:

- `scripts/verify_dataset.py` valida columnas, cantidad de filas, clases y checksum.
- `scripts/train_baseline.py` limpia `TotalCharges`, separa train/test, excluye `customerID` y entrena una regresión logística baseline.
- `scripts/score_batch.py` produce scoring local y ordena por prioridad de negocio.
- `app/main.py` expone `/healthz`, `/predict` y `/batch-score`.

## Reproducción local

Desde la raíz del repo:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt

python scripts\verify_dataset.py
python scripts\train_baseline.py
python scripts\score_batch.py --input data\fixtures\batch-input.csv
pytest -q
```

El verificador debe imprimir:

```text
OK dataset: 7043 filas, 21 columnas.
Churn Yes: 1869 | Churn No: 5174
SHA-256: 16320c9c1ec72448db59aa0a26a0b95401046bef5d02fd3aeb906448e3055e91
```

Para reconstruir el CSV desde la fuente original en Windows:

```powershell
Invoke-WebRequest `
  -Uri "https://raw.githubusercontent.com/IBM/telco-customer-churn-on-icp4d/master/data/Telco-Customer-Churn.csv" `
  -OutFile "data\raw\Telco-Customer-Churn.csv"

Get-FileHash "data\raw\Telco-Customer-Churn.csv" -Algorithm SHA256
python scripts\verify_dataset.py
```

## Reproducción en GCP

El runbook operativo está en `gcp/runbook.md`. La notebook guiada `notebooks/c04_vertex_cloudshell.ipynb`
recorre el flujo en Cloud Shell. El flujo reproducible esperado es:

1. Autenticarse con `gcloud` y seleccionar proyecto.
2. Definir `PROJECT_ID`, `REGION`, `BUCKET`, `REPO`, `SERVICE` e `IMAGE`.
3. Habilitar APIs de Vertex AI, Artifact Registry, Cloud Build y Cloud Run.
4. Verificar localmente el CSV con `python scripts/verify_dataset.py`.
5. Subir a Cloud Storage el CSV y el archivo `.sha256`.
6. Usar Vertex AI para dataset tabular, entrenamiento, evaluación, registro y batch inference.
7. Usar FastAPI + Docker + Cloud Run para serving propio, logs, revisiones y rollback.
8. Ejecutar cleanup al terminar para evitar costos residuales.

Comandos mínimos de trazabilidad en Cloud Shell:

```bash
python scripts/verify_dataset.py
sha256sum data/raw/Telco-Customer-Churn.csv

gcloud storage cp data/raw/Telco-Customer-Churn.csv "gs://${BUCKET}/raw/Telco-Customer-Churn.csv"
gcloud storage cp data/raw/Telco-Customer-Churn.csv.sha256 "gs://${BUCKET}/raw/Telco-Customer-Churn.csv.sha256"
gcloud storage ls "gs://${BUCKET}/raw/"
```

## Fuentes técnicas GCP consultadas

Google Cloud está migrando parte de la documentación histórica de Vertex AI hacia URLs bajo
**Gemini Enterprise Agent Platform**. Por eso se deja registrada la URL actual consultada.

- Clasificación y regresión tabular: <https://docs.cloud.google.com/gemini-enterprise-agent-platform/machine-learning/tabular-data/classification-regression/overview>
- Batch inference: <https://docs.cloud.google.com/gemini-enterprise-agent-platform/machine-learning/predictions/get-batch-predictions>
- Model Registry: <https://docs.cloud.google.com/gemini-enterprise-agent-platform/machine-learning/model-registry/introduction>
- Model Monitoring: <https://docs.cloud.google.com/gemini-enterprise-agent-platform/machine-learning/model-monitoring/overview>
- Artifact Registry + Cloud Run: <https://docs.cloud.google.com/artifact-registry/docs/integrate-cloud-run>
- Logs de Cloud Run: <https://docs.cloud.google.com/run/docs/logging>
- Rollback y tráfico por revisiones en Cloud Run: <https://docs.cloud.google.com/run/docs/rollouts-rollbacks-traffic-migration>

## Modelos entrenados

Los modelos entrenados localmente quedan en `models/` y se ignoran por Git; se regeneran con
`python scripts/train_baseline.py`.
