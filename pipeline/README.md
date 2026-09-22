# Orquestación del pipeline de Churn

Hasta acá, los pasos del caso (verificar el dato, entrenar, evaluar, scorear, desplegar) se
corrían **a mano, uno atrás del otro**. Este módulo los **orquesta**: los ata en un grafo con
dependencias y un disparador, para que corran solos y en orden, con un **gate de calidad** que
puede cortar la cadena si el modelo no llega.

Es la pieza que **une todas las partes** de las clases 4 a 7: el mismo caso, ahora como una sola
cañería que se puede disparar sola y reentrenar cuando el mundo cambia.

```
verificar dato  ->  entrenar  ->  [gate: ROC AUC >= umbral]  ->  promover modelo
```

El orquestador es "el jefe de orquesta que no toca ningún instrumento": no entrena ni scorea,
solo dispara cada paso en orden y decide si el siguiente corre.

## Las dos versiones

| Archivo | Qué es | Dónde corre |
|---|---|---|
| `run_local.py` | El "modulito": encadena los scripts del repo con un gate | Tu máquina o Cloud Shell, sin nube |
| `vertex_pipeline.py` | El mismo grafo como pipeline gestionado (KFP v2) | Vertex AI Pipelines |

Empezá por el local para entender el concepto; subí a Vertex cuando quieras el grafo gestionado
(artefactos versionados, caché de pasos, linaje, y el DAG dibujado en la consola).

### 1. Pipeline local

```bash
python pipeline/run_local.py                 # corre la cadena entera
python pipeline/run_local.py --gate-min 0.99 # fuerza que el gate corte (demo)
```

### 2. Pipeline en Vertex AI Pipelines (KFP v2)

```bash
pip install -r requirements-gcp.txt          # trae kfp y google-cloud-aiplatform

python pipeline/vertex_pipeline.py --compile # solo compila el JSON (no toca la nube)
python pipeline/vertex_pipeline.py           # compila y lanza en Vertex
```

El grafo queda visible en la consola: **Vertex AI → Pipelines**. Cada paso es un componente que
corre en su contenedor; Vertex cachea los que no cambiaron.

### 3. El disparador

Quién dispara el pipeline (a mano, por tiempo, por evento, por drift) está en
[`trigger/README.md`](trigger/README.md). Los tres disparadores automáticos publican a un topic
de Pub/Sub, y la **Cloud Function** `functions/main.py` es el pegamento que consume el mensaje y
hace `PipelineJob.submit()` — **es la que cierra el loop**. El disparo por **drift**
(`trigger/drift_gate.py`) detecta que la población cambió y reentrena solo (Continuous Training).

### 4. Infraestructura como código

El topic de Pub/Sub y el job de Cloud Scheduler se declaran con Terraform en
[`terraform/`](terraform/), en vez de clickearlos en la consola.

```bash
cd pipeline/terraform
terraform init && terraform validate
terraform apply -var project=$PROJECT_ID
```

## Cómo lo aplican en su TFI

1. Dejen cada paso como un **script atómico** que hace una cosa (ya los tienen en `scripts/`).
2. Escriban un **runner** que los encadene en orden, con un **gate** que corte si el modelo no llega.
3. Decidan **quién dispara** el pipeline en su caso (reloj, evento, drift) y déjenlo escrito.

No hace falta subir a Vertex para aprobar: un `run_local.py` bien hecho ya demuestra que
entendieron la orquestación. Vertex es el paso siguiente cuando el grafo crece.
