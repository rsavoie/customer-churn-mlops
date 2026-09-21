"""Orquestador local del pipeline de Churn (clase 8 bonus: orquestación).

Encadena los pasos que hoy se corren a mano, uno atrás del otro, en un solo comando y
en el orden correcto, con un **gate de calidad** en el medio que puede **cortar la cadena**:

    verificar dato  ->  entrenar  ->  [GATE: ROC AUC >= umbral]  ->  scorear batch

Es el "modulito" del que hablábamos: los mismos scripts atómicos de siempre
(`scripts/verify_dataset.py`, `scripts/train_baseline.py`, `scripts/score_batch.py`),
pero orquestados. El orquestador no entrena ni scorea: solo dispara cada paso en orden y
decide si el siguiente corre (el "jefe de orquesta que no toca ningún instrumento").

Es la versión **liviana y sin nube**: sirve para entender el concepto antes de subirlo a
Vertex AI Pipelines (`pipeline/vertex_pipeline.py`). Un pipeline es un grafo de pasos con
dependencias y un disparador; acá el disparador sos vos corriendo el comando.

Uso:
    python pipeline/run_local.py                 # corre la cadena entera
    python pipeline/run_local.py --gate-min 0.80 # umbral del gate (default 0.80)
    python pipeline/run_local.py --gate-min 0.99 # fuerza que el gate CORTE (demo)
    python pipeline/run_local.py --skip-verify   # saltea la verificación del dato

El gate lee `models/churn-baseline-metrics.json` (lo que deja `train_baseline.py`). Con el
baseline actual (ROC AUC ~0.84) el umbral 0.80 pasa; subilo por encima de 0.84 para ver la
cadena cortarse antes de scorear, que es el punto: un pipeline serio no promueve un modelo
que no llega.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
METRICS_PATH = ROOT / "models" / "churn-baseline-metrics.json"
DEFAULT_GATE_MIN_ROC_AUC = 0.80


def banner(step: int, total: int, title: str) -> None:
    print("")
    print("=" * 68)
    print(f"  PASO {step}/{total}  ->  {title}")
    print("=" * 68)


def run_step(title: str, command: list[str]) -> None:
    """Corre un paso del pipeline como subproceso. Si falla, corta la cadena."""
    print(f"$ {' '.join(str(part) for part in command)}")
    started = time.perf_counter()
    result = subprocess.run(command, cwd=ROOT)
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        sys.exit(
            f"\n[X] El paso '{title}' falló (código {result.returncode}). "
            "El pipeline corta acá; no se ejecutan los pasos siguientes."
        )
    print(f"[OK] {title}  ({elapsed:.1f}s)")


def quality_gate(gate_min: float) -> float:
    """Gate de calidad: lee las métricas del modelo recién entrenado y decide si sigue.

    Es el paso que convierte una cadena de scripts en un pipeline con criterio: si el
    modelo no llega al umbral, NO se promueve ni se scorea. Devuelve el ROC AUC leído.
    """
    if not METRICS_PATH.exists():
        sys.exit(f"[X] No encontré las métricas en {METRICS_PATH}. ¿Corrió el entrenamiento?")
    metrics = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    roc_auc = float(metrics.get("roc_auc", 0.0))
    print(f"    ROC AUC del modelo : {roc_auc:.4f}")
    print(f"    Umbral del gate    : {gate_min:.4f}")
    if roc_auc < gate_min:
        sys.exit(
            f"\n[X] GATE: ROC AUC {roc_auc:.4f} < umbral {gate_min:.4f}. "
            "El modelo no llega, así que el pipeline corta: no se scorea ni se promueve. "
            "En producción, acá se dispararía una alerta en vez de degradar el servicio."
        )
    print(f"[OK] GATE en verde: {roc_auc:.4f} >= {gate_min:.4f}. El modelo puede promoverse.")
    return roc_auc


def main() -> None:
    parser = argparse.ArgumentParser(description="Orquestador local del pipeline de Churn.")
    parser.add_argument(
        "--gate-min",
        type=float,
        default=DEFAULT_GATE_MIN_ROC_AUC,
        help="ROC AUC mínimo para promover el modelo (default 0.80).",
    )
    parser.add_argument("--skip-verify", action="store_true", help="Saltea la verificación del dataset.")
    parser.add_argument("--input", default=None, help="CSV de entrenamiento (default: el canónico del repo).")
    args = parser.parse_args()

    python = sys.executable
    total = 4
    started = time.perf_counter()

    print("Pipeline local de Churn — el mismo grafo que hoy corren a mano, ahora encadenado:")
    print("  verificar dato  ->  entrenar  ->  [gate ROC AUC]  ->  scorear batch")

    step = 1
    if args.skip_verify:
        print("\n(omito la verificación del dataset por --skip-verify)")
    else:
        banner(step, total, "Verificar el dataset (integridad del dato)")
        verify_cmd = [python, "scripts/verify_dataset.py"]
        if args.input:
            verify_cmd += ["--input", args.input]
        run_step("verificar dataset", verify_cmd)
    step += 1

    banner(step, total, "Entrenar el modelo baseline")
    train_cmd = [python, "scripts/train_baseline.py"]
    if args.input:
        train_cmd += ["--input", args.input]
    run_step("entrenar modelo", train_cmd)
    step += 1

    banner(step, total, "Gate de calidad (¿el modelo llega al umbral?)")
    roc_auc = quality_gate(args.gate_min)
    step += 1

    banner(step, total, "Scorear el batch y armar el ranking de retención")
    run_step("scorear batch", [python, "scripts/score_batch.py"])

    elapsed = time.perf_counter() - started
    print("")
    print("-" * 68)
    print(f"Pipeline COMPLETO en {elapsed:.1f}s. Modelo (ROC AUC {roc_auc:.4f}) promovido y batch scoreado.")
    print("Este es el grafo que en la nube corre solo: ver pipeline/vertex_pipeline.py.")


if __name__ == "__main__":
    main()
