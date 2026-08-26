# Customer Churn, caso guía MLOps 2026

Este demo convierte el caso clásico de **Customer Churn** en hilo conductor técnico para las clases 4 a 7.

La idea docente es simple: en Canvas definimos qué decisión quiere tomar CRM; después vamos construyendo el sistema que hace posible esa decisión. Primero entrenamos y scoreamos en batch, después exponemos una API, luego la empaquetamos y finalmente la operamos.

## Qué contiene

- `data/raw/Telco-Customer-Churn.csv`: dataset canónico de IBM.
- `SOURCES.md`: manifiesto de fuentes, hash y reproducción local/GCP.
- `notebooks/c04_vertex_cloudshell.ipynb`: notebook del **lab de la clase 4** (Cloud Shell): dato a la nube, entrenamiento, scoring batch y ranking.
- `notebooks/churn_baseline_smoke.ipynb`: notebook corto de entrenamiento y scoring local; es el puente Canvas→sistema de las clases 2 y 3, distinto del lab de la clase 4.
- `scripts/verify_dataset.py`: chequeo de forma del dataset.
- `scripts/train_baseline.py`: baseline local con regresión logística.
- `scripts/download_model.py`: baja el modelo del bucket a `models/` (preparación de la **clase 5**, cuando la copia local ya no está).
- `scripts/score_batch.py`: scoring batch local y ranking por prioridad.
- `scripts/train_automl.py` y `scripts/batch_predict_automl.py`: demo AutoML gestionado por SDK de Vertex (se corre desde la terminal; ver `gcp/runbook.md` §Clase 4).
- `app/`: API FastAPI con `/healthz`, `/predict` y `/batch-score`.
- `gcp/runbook.md`: comandos parametrizados para Vertex AI, Artifact Registry y Cloud Run.

## Lectura pedagógica del caso

El usuario del sistema es el **equipo de CRM**. La predicción no vale por sí misma: vale porque ordena una acción concreta de retención.

- **Etiqueta**: `Churn`, con `Yes` como clase positiva.
- **Salida del modelo**: `churn_probability`.
- **Prioridad operativa**: `priority_score = churn_probability * MonthlyCharges`.
- **Decisión inicial**: `retention_queue` cuando `churn_probability >= 0.7`; `monitor` en el resto.

En clase, esto permite sostener una pregunta por bloque:

| Clase | Pregunta | Artefacto que queda |
|---|---|---|
| 3 | ¿Qué decisión quiere tomar CRM? | Canvas de Churn completo |
| 4 | ¿Cómo paso de datos a scoring batch? | Modelo tabular y ranking mensual |
| 5 | ¿Cómo consumo el score desde otro sistema? | Contrato HTTP estable |
| 6 | ¿Cómo llevo esa API a la nube? | Imagen Docker y servicio Cloud Run |
| 7 | ¿Cómo sé si esto sigue funcionando? | Logs, métricas, drift y rollback |

## Setup local

Desde esta carpeta:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Verificá el dataset:

```powershell
python scripts\verify_dataset.py
```

Entrená el baseline local:

```powershell
python scripts\train_baseline.py
```

Scoreá el fixture batch:

```powershell
python scripts\score_batch.py --input data\fixtures\batch-input.csv
```

Levantá la API:

```powershell
$env:MODEL_BACKEND = "local"
$env:MODEL_PATH = "models\churn-baseline.joblib"
uvicorn app.main:app --reload --port 8000
```

Probá un request:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/predict" `
  -ContentType "application/json" `
  -InFile "data\fixtures\customer-example.json"
```

## Stack GCP

El stack recomendado para la cursada es mixto:

- **Vertex AI** para el flujo gestionado de dataset, entrenamiento, evaluación, registro, batch prediction y endpoint si se quiere mostrar serving gestionado.
- **FastAPI + Docker + Cloud Run** para explicar contratos, empaquetado, despliegue reproducible, revisiones, logs y rollback.

Los comandos están en [`gcp/runbook.md`](gcp/runbook.md).

## Fuentes y reproducción

La fuente de datos, la licencia, el checksum y las referencias GCP quedan trazadas en [`SOURCES.md`](SOURCES.md). El objetivo es que una edición futura pueda reconstruir el demo sin depender de memoria oral, URLs personales o project IDs hardcodeados.

## Limpieza operativa

Antes de cerrar una clase con GCP, revisar que no queden endpoints, batch jobs o servicios generando costo sin intención docente. El runbook incluye comandos de cleanup.
