from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "raw" / "Telco-Customer-Churn.csv"
EXPECTED_SHA256 = "16320c9c1ec72448db59aa0a26a0b95401046bef5d02fd3aeb906448e3055e91"
EXPECTED_COLUMNS = [
    "customerID",
    "gender",
    "SeniorCitizen",
    "Partner",
    "Dependents",
    "tenure",
    "PhoneService",
    "MultipleLines",
    "InternetService",
    "OnlineSecurity",
    "OnlineBackup",
    "DeviceProtection",
    "TechSupport",
    "StreamingTV",
    "StreamingMovies",
    "Contract",
    "PaperlessBilling",
    "PaymentMethod",
    "MonthlyCharges",
    "TotalCharges",
    "Churn",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_dataset(path: Path, check_hash: bool = True) -> dict[str, int | str]:
    file_hash = sha256_file(path)
    if check_hash and file_hash != EXPECTED_SHA256:
        raise AssertionError(f"SHA-256 inesperado: {file_hash}")

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames or []
        if columns != EXPECTED_COLUMNS:
            raise AssertionError(f"Columnas inesperadas: {columns}")
        rows = list(reader)

    yes_count = sum(1 for row in rows if row["Churn"] == "Yes")
    no_count = sum(1 for row in rows if row["Churn"] == "No")
    if len(rows) != 7043:
        raise AssertionError(f"Se esperaban 7043 registros y se encontraron {len(rows)}.")
    if yes_count == 0 or no_count == 0:
        raise AssertionError("La columna Churn no contiene ambas clases.")
    return {
        "rows": len(rows),
        "columns": len(columns),
        "churn_yes": yes_count,
        "churn_no": no_count,
        "sha256": file_hash,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verifica el dataset canónico de Churn.")
    parser.add_argument(
        "--input",
        default=DEFAULT_INPUT,
        type=Path,
        help="Ruta al CSV crudo.",
    )
    parser.add_argument(
        "--skip-hash",
        action="store_true",
        help="Valida forma y label sin comparar contra el checksum canónico.",
    )
    args = parser.parse_args()
    stats = verify_dataset(args.input, check_hash=not args.skip_hash)
    print(f"OK dataset: {stats['rows']} filas, {stats['columns']} columnas.")
    print(f"Churn Yes: {stats['churn_yes']} | Churn No: {stats['churn_no']}")
    print(f"SHA-256: {stats['sha256']}")


if __name__ == "__main__":
    main()
