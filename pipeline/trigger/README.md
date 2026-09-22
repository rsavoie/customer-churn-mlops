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
El evento publica al topic y una **Cloud Function** suscripta lanza el pipeline.

## El pegamento: la Cloud Function

Los tres disparadores de arriba (tiempo, evento, drift) hacen lo mismo: **publican un mensaje al
topic `churn-retrain`**. Pero Vertex no se suscribe solo a un topic; hace falta algo que escuche el
mensaje y llame a la API. Ese pegamento es la **Cloud Function** `pipeline/functions/main.py`: está
suscripta al topic y, ante cada mensaje, hace `PipelineJob.submit()`. **Es la que cierra el loop.**

Necesita el template **compilado y en el bucket** (la función no tiene el repo a mano). Dos pasos:

```bash
# 1. Compilar y subir el template al bucket
python pipeline/vertex_pipeline.py --stage

# 2. Desplegar la función (2da gen, trigger de Pub/Sub sobre el topic)
gcloud functions deploy churn-retrain-trigger \
  --gen2 --runtime python312 --region "$REGION" \
  --source pipeline/functions --entry-point trigger_retrain \
  --trigger-topic churn-retrain \
  --set-env-vars REGION="$REGION",BUCKET="$BUCKET",GATE_MIN=0.80
```

> **Permisos:** la cuenta de servicio de ejecución de la función necesita `roles/aiplatform.user`
> (lanzar pipelines) y acceso al bucket (`roles/storage.admin`), igual que la SA de Compute del
> pipeline. Si el deploy usa la SA de Compute por defecto y ya le diste `storage.admin` (ver el
> runbook), solo falta `aiplatform.user`.

Con la función desplegada, el loop queda **cerrado de verdad**: el reloj / el drift / un evento
publican al topic → la función los consume → el pipeline corre. Probalo a mano:

```bash
gcloud pubsub topics publish churn-retrain --message "prueba"
# y mirá el nuevo run en Vertex AI -> Pipelines
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
