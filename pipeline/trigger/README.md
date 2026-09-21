# El disparador del pipeline

Un pipeline es un grafo de pasos **y un disparador**. El grafo ya lo tenés
(`pipeline/vertex_pipeline.py`); acá va el disparador: **quién decide cuándo corre**. La
pregunta más difícil del tema, y la respuesta es siempre la misma: *lo decidís vos según tu
caso*. Hay cuatro formas típicas.

## 1. A mano (un botón)

El disparo más honesto para empezar: vos corrés el comando o apretás "Run" en la consola de
Vertex. Sirve para el TFI y para la demo.

```bash
python pipeline/vertex_pipeline.py
```

## 2. Por tiempo (Cloud Scheduler)

El reloj dispara. Útil cuando el dato se actualiza en un ciclo conocido: "reentrenar todos los
lunes a la madrugada". Cloud Scheduler publica un mensaje a un topic de Pub/Sub según un cron.

```bash
gcloud services enable pubsub.googleapis.com cloudscheduler.googleapis.com

gcloud pubsub topics create churn-retrain

gcloud scheduler jobs create pubsub churn-retrain-weekly \
  --location "$REGION" \
  --schedule "0 3 * * 1" \
  --time-zone "America/Argentina/Buenos_Aires" \
  --topic churn-retrain \
  --message-body "scheduled-retrain"
```

Lo mismo, declarado como infraestructura como código, está en `pipeline/terraform/` (recomendado:
la infra versionada en git en vez de clickeada).

## 3. Por evento (Pub/Sub)

Un evento externo dispara: llegó un archivo nuevo al bucket, cerró una fecha, se cargó un lote.
El evento publica al topic y una **Cloud Function** suscripta lanza el pipeline. Ejemplo de la
función (esbozo, no hace falta desplegarla para el TFI):

```python
# functions/main.py  (Cloud Function suscripta al topic churn-retrain)
import os
from google.cloud import aiplatform

def trigger_retrain(event, context):
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    bucket = f"{project}-churn"
    aiplatform.init(project=project, location="us-central1", staging_bucket=f"gs://{bucket}")
    aiplatform.PipelineJob(
        display_name="churn-retrain",
        template_path="gs://%s/pipeline-root/churn_pipeline.json" % bucket,
        pipeline_root=f"gs://{bucket}/pipeline-root",
        parameter_values={"bucket": bucket, "gate_min": 0.80},
    ).submit()
```

## 4. Por drift (el sistema se cuida solo)

El disparador es la salud del modelo. La operación de la clase 7 (PSI, `scripts/check_drift.py`)
detecta que "el mundo que modelé ya no es el mismo" y dispara el reentrenamiento **sin que nadie
mire**. Esto es Continuous Training, y es lo que cierra el loop del caso.

`pipeline/trigger/drift_gate.py` reusa el chequeo de PSI pero devuelve un código de salida (0
estable, 1 drift). Un cron corre el chequeo y, si hay drift, publica al topic:

```bash
# corre cada día; si detecta drift, dispara el pipeline
python pipeline/trigger/drift_gate.py || gcloud pubsub topics publish churn-retrain --message drift
```

> El disparo por drift no reemplaza al programado: conviene tener los dos. El reloj garantiza un
> piso de frescura; el drift reacciona cuando algo cambia antes de tiempo.
