"""Compuerta de drift para disparar el reentrenamiento (clase 8 bonus: orquestación).

Reusa el chequeo de PSI de `scripts/check_drift.py`, pero en vez de solo imprimir el veredicto
**devuelve un código de salida**: 0 si la población está estable, 1 si hay drift por encima del
umbral. Ese exit code es lo que un disparador (un cron, un job de Cloud Scheduler, un paso de
CI) usa para decidir si lanza el pipeline de reentrenamiento.

Cierra el loop que pidió la clase: operación (clase 7) detecta que "el mundo cambió" y, sin que
nadie mire, dispara el entrenamiento (Continuous Training).

Uso:
    python pipeline/trigger/drift_gate.py                 # referencia vs ventana simulada
    python pipeline/trigger/drift_gate.py --threshold 0.25
    python pipeline/trigger/drift_gate.py --current ventana-real.csv

    # patrón de disparo (bash): si hay drift, publica a Pub/Sub y Vertex reentrena
    python pipeline/trigger/drift_gate.py || gcloud pubsub topics publish churn-retrain --message drift
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.check_drift import (  # noqa: E402
    DEFAULT_FEATURES,
    DEFAULT_REFERENCE,
    NUMERIC,
    psi_categorical,
    psi_numeric,
    simulate_production,
    verdict,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compuerta de drift (PSI) con código de salida.")
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--current", type=Path, default=None, help="CSV de producción; si falta, se simula.")
    parser.add_argument("--features", nargs="*", default=DEFAULT_FEATURES)
    parser.add_argument("--threshold", type=float, default=0.25, help="PSI que dispara reentrenamiento.")
    args = parser.parse_args()

    reference = pd.read_csv(args.reference)
    current = pd.read_csv(args.current) if args.current is not None else simulate_production(reference)

    peor = 0.0
    for feature in args.features:
        if feature not in reference.columns or feature not in current.columns:
            continue
        if feature in NUMERIC:
            psi = psi_numeric(reference[feature], current[feature])
        else:
            psi = psi_categorical(reference[feature], current[feature])
        peor = max(peor, psi)
        print(f"  {feature:<16} PSI={psi:7.3f}  {verdict(psi)}")

    print(f"PSI máximo = {peor:.3f} | umbral de disparo = {args.threshold:.3f}")
    if peor >= args.threshold:
        print("DRIFT: el mundo cambió. Disparar reentrenamiento.")
        sys.exit(1)
    print("Estable: no hace falta reentrenar.")
    sys.exit(0)


if __name__ == "__main__":
    main()
