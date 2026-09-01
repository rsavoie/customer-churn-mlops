"""Genera carga contra la API y mide latencia (clase 7, observabilidad).

Dispara N requests a `/predict` y reporta la distribución de latencia (p50/p95/p99) y los
errores. Sirve para dos cosas en clase:

  1. **Ver latencia de verdad**, no un número teórico: el primer request paga el arranque en
     frío de Cloud Run (cold start) y los siguientes salen tibios.
  2. **Producir tráfico** para después leerlo en los logs (`gcloud run services logs read`).

Solo librería estándar: se corre en Cloud Shell sin instalar nada.

Uso:
    python scripts/smoke_load.py                                  # 50 requests a localhost:8080
    python scripts/smoke_load.py --url "$SERVICE_URL" --n 100     # contra la URL de Cloud Run
    python scripts/smoke_load.py --url "$SERVICE_URL" --concurrency 8
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PAYLOAD = ROOT / "data" / "fixtures" / "customer-example.json"


def percentile(values: list[float], pct: float) -> float:
    """Percentil por interpolación lineal (sin numpy). `pct` en [0, 100]."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def one_request(url: str, body: bytes) -> tuple[float, int]:
    """Devuelve (latencia_ms, status). status 0 si ni siquiera hubo respuesta HTTP."""
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except Exception:  # noqa: BLE001 (red caída, timeout, etc.)
        status = 0
    latency_ms = (time.perf_counter() - start) * 1000
    return latency_ms, status


def main() -> None:
    parser = argparse.ArgumentParser(description="Carga y latencia contra la API de churn.")
    parser.add_argument("--url", default="http://127.0.0.1:8080", help="Base URL del servicio.")
    parser.add_argument("--endpoint", default="/predict", help="Ruta a golpear.")
    parser.add_argument("--n", type=int, default=50, help="Cantidad de requests.")
    parser.add_argument("--concurrency", type=int, default=1, help="Requests en paralelo.")
    parser.add_argument("--payload", type=Path, default=DEFAULT_PAYLOAD, help="JSON del cuerpo.")
    args = parser.parse_args()

    target = args.url.rstrip("/") + args.endpoint
    body = args.payload.read_bytes()

    print(f"Disparando {args.n} requests a {target} (concurrencia {args.concurrency})...")
    wall_start = time.perf_counter()
    if args.concurrency > 1:
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            results = list(pool.map(lambda _: one_request(target, body), range(args.n)))
    else:
        results = [one_request(target, body) for _ in range(args.n)]
    wall_s = time.perf_counter() - wall_start

    latencies = [latency for latency, _ in results]
    statuses = [status for _, status in results]
    ok = sum(1 for s in statuses if 200 <= s < 300)
    errors = len(statuses) - ok

    print("")
    print(f"  requests   : {len(results)}")
    print(f"  ok (2xx)   : {ok}")
    print(f"  errores    : {errors}")
    print(f"  throughput : {len(results) / wall_s:.1f} req/s  ({wall_s:.2f}s total)")
    print("  latencia (ms):")
    print(f"    min  : {min(latencies):8.1f}")
    print(f"    p50  : {statistics.median(latencies):8.1f}")
    print(f"    p95  : {percentile(latencies, 95):8.1f}")
    print(f"    p99  : {percentile(latencies, 99):8.1f}")
    print(f"    max  : {max(latencies):8.1f}   <- suele ser el arranque en frio (cold start)")
    if errors:
        codes = sorted({s for s in statuses if not (200 <= s < 300)})
        print(f"  codigos de error: {codes}")


if __name__ == "__main__":
    main()
