"""Chequeo de drift offline con PSI (clase 7, observabilidad).

Compara la distribución de cada feature entre una **referencia** (los datos con los que se
entrenó) y una ventana **de producción** (lo que está llegando ahora). Reporta el
Population Stability Index (PSI) por feature, la métrica estándar para responder la pregunta de
la clase 1: *"¿el mundo que modelé sigue siendo el mismo?"* (el "limón que se pudre despacito").

Interpretación clásica del PSI:
    < 0.10   estable
    0.10-0.25   atención: empezó a moverse
    > 0.25   drift fuerte: el modelo está viendo otra población

Sin `--current`, simula una ventana de producción desplazada (clientes más nuevos y más caros,
más propensos a churn) resampleando la referencia con una semilla fija: reproducible y sirve para
mostrar el efecto en clase sin depender de datos nuevos.

Uso:
    python scripts/check_drift.py                          # referencia vs ventana simulada
    python scripts/check_drift.py --current mi-ventana.csv # referencia vs datos reales
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE = ROOT / "data" / "raw" / "Telco-Customer-Churn.csv"
DEFAULT_FEATURES = ["tenure", "MonthlyCharges", "TotalCharges", "Contract"]
NUMERIC = {"tenure", "MonthlyCharges", "TotalCharges"}
EPS = 1e-6


def verdict(psi: float) -> str:
    if psi < 0.10:
        return "estable"
    if psi < 0.25:
        return "atencion"
    return "DRIFT"


def psi_from_props(ref_prop: pd.Series, cur_prop: pd.Series) -> float:
    """PSI = sum((cur - ref) * ln(cur / ref)) sobre bines alineados."""
    total = 0.0
    for bin_key in ref_prop.index:
        ref_p = max(float(ref_prop.get(bin_key, 0.0)), EPS)
        cur_p = max(float(cur_prop.get(bin_key, 0.0)), EPS)
        total += (cur_p - ref_p) * math.log(cur_p / ref_p)
    return total


def psi_numeric(ref: pd.Series, cur: pd.Series, bins: int = 10) -> float:
    ref = pd.to_numeric(ref, errors="coerce").dropna()
    cur = pd.to_numeric(cur, errors="coerce").dropna()
    quantiles = [i / bins for i in range(bins + 1)]
    edges = sorted(set(ref.quantile(quantiles).tolist()))
    if len(edges) < 2:  # feature casi constante
        return 0.0
    edges[0], edges[-1] = -math.inf, math.inf
    ref_binned = pd.cut(ref, bins=edges, include_lowest=True)
    cur_binned = pd.cut(cur, bins=edges, include_lowest=True)
    ref_prop = ref_binned.value_counts(normalize=True, sort=False)
    cur_prop = cur_binned.value_counts(normalize=True, sort=False)
    return psi_from_props(ref_prop, cur_prop)


def psi_categorical(ref: pd.Series, cur: pd.Series) -> float:
    ref_prop = ref.astype(str).value_counts(normalize=True)
    cur_prop = cur.astype(str).value_counts(normalize=True)
    categories = ref_prop.index.union(cur_prop.index)
    ref_prop = ref_prop.reindex(categories, fill_value=0.0)
    cur_prop = cur_prop.reindex(categories, fill_value=0.0)
    return psi_from_props(ref_prop, cur_prop)


def simulate_production(reference: pd.DataFrame, seed: int = 7) -> pd.DataFrame:
    """Ventana de producción sintética con drift plausible: un nuevo período que capta clientes
    más nuevos y más caros, sumado a un aumento de precios. Dos drivers reales de drift."""
    charges = pd.to_numeric(reference["MonthlyCharges"], errors="coerce").fillna(0.0)
    tenure = pd.to_numeric(reference["tenure"], errors="coerce").fillna(0.0)
    # Peso concentrado en cargos altos y antigüedad baja (ambos normalizados a [0, 1]).
    w_charges = (charges - charges.min()) / (charges.max() - charges.min() + EPS)
    w_tenure = 1 - (tenure - tenure.min()) / (tenure.max() - tenure.min() + EPS)
    weights = 0.15 + 1.6 * w_charges + 1.6 * w_tenure
    sample = reference.sample(n=len(reference), replace=True, weights=weights, random_state=seed).copy()
    # Aumento de precios del período (+4%): empuja MonthlyCharges (y arrastra TotalCharges).
    sample["MonthlyCharges"] = pd.to_numeric(sample["MonthlyCharges"], errors="coerce") * 1.04
    sample["TotalCharges"] = pd.to_numeric(sample["TotalCharges"], errors="coerce") * 1.04
    return sample


def main() -> None:
    parser = argparse.ArgumentParser(description="Chequeo de drift (PSI) para Customer Churn.")
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--current", type=Path, default=None, help="CSV de producción; si falta, se simula.")
    parser.add_argument("--features", nargs="*", default=DEFAULT_FEATURES)
    args = parser.parse_args()

    reference = pd.read_csv(args.reference)
    if args.current is not None:
        current = pd.read_csv(args.current)
        origen = str(args.current)
    else:
        current = simulate_production(reference)
        origen = "ventana simulada (clientes nuevos y caros)"

    print(f"Referencia : {args.reference}  ({len(reference)} filas)")
    print(f"Produccion : {origen}  ({len(current)} filas)")
    print("")
    print(f"  {'feature':<16} {'PSI':>8}   veredicto")
    print(f"  {'-' * 16} {'-' * 8}   {'-' * 9}")
    peor = 0.0
    for feature in args.features:
        if feature not in reference.columns or feature not in current.columns:
            print(f"  {feature:<16} {'--':>8}   (no está en ambos sets)")
            continue
        if feature in NUMERIC:
            psi = psi_numeric(reference[feature], current[feature])
        else:
            psi = psi_categorical(reference[feature], current[feature])
        peor = max(peor, psi)
        print(f"  {feature:<16} {psi:8.3f}   {verdict(psi)}")

    print("")
    if peor >= 0.25:
        print(f"  -> PSI maximo {peor:.3f}: hay drift. Revisar el modelo y considerar reentrenar.")
    elif peor >= 0.10:
        print(f"  -> PSI maximo {peor:.3f}: empezo a moverse. Vigilar de cerca.")
    else:
        print(f"  -> PSI maximo {peor:.3f}: poblacion estable.")


if __name__ == "__main__":
    main()
