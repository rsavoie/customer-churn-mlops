"""Verifica el checklist de pre-demo contra un servicio desplegado (clase 8, lab de integración).

La clase 8 no trae tema nuevo: cada grupo ensambla sus piezas (modelo, API, despliegue,
operación) en una demo desplegada y defendible. Este script corre la parte del **checklist de
pre-demo** que se puede automatizar: le pega a la URL del servicio y confirma que la cadena
responde de punta a punta antes de la defensa.

Chequeos automáticos (contra `--url`):

  1. **Servicio accesible**  : `GET /healthz` responde y el modelo está cargado.
  2. **Contrato publicado**  : `GET /openapi.json` expone `/healthz`, `/predict` y `/batch-score`.
  3. **Predicción real**     : `POST /predict` con un cliente de ejemplo devuelve probabilidad y decisión.
  4. **Validación de entrada**: `POST /predict` con un dato inválido devuelve 422 (el contrato rechaza basura).
  5. **Latencia**            : mide el ida y vuelta de una predicción (informativo; el primero paga arranque en frío).

Lo que NO se puede verificar desde afuera queda como recordatorio para tildar a mano: secretos
sin credenciales en el repo, logs y métrica mirados en la consola, video de respaldo y fallback.

Solo librería estándar: se corre en Cloud Shell sin instalar nada. La salida evita tildes a
propósito, para que se lea igual en cualquier consola (igual que `smoke_load.py`).

Uso:
    python scripts/predemo_check.py                                 # contra localhost:8080
    python scripts/predemo_check.py --url "$SERVICE_URL"            # contra la URL de Cloud Run
    python scripts/predemo_check.py --url "$SERVICE_URL" --fixture data/fixtures/customer-example.json

Devuelve código de salida 0 si pasan todos los chequeos automáticos, 1 si alguno falla.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT / "data" / "fixtures" / "customer-example.json"
DEFAULT_INVALID = ROOT / "data" / "fixtures" / "invalid-example.json"

OK = "[OK]"
FAIL = "[X]"
WARN = "[!]"
INFO = "[i]"
TODO = "[ ]"

# Latencia por encima de esto: probablemente arranque en frio o un servicio lento para una demo.
LATENCY_WARN_MS = 2500.0


def http_get(url: str, timeout: float) -> tuple[int, bytes]:
    """GET simple. Devuelve (status, body). status 0 si no hubo respuesta HTTP."""
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except Exception:  # noqa: BLE001 (red caida, timeout, DNS)
        return 0, b""


def http_post_json(url: str, body: bytes, timeout: float) -> tuple[int, bytes, float]:
    """POST de un JSON. Devuelve (status, body, latencia_ms). status 0 si no hubo respuesta."""
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        status, payload = exc.code, exc.read()
    except Exception:  # noqa: BLE001
        status, payload = 0, b""
    latency_ms = (time.perf_counter() - start) * 1000
    return status, payload, latency_ms


def check_healthz(base: str, timeout: float) -> bool:
    """1. El servicio responde y el modelo esta cargado."""
    status, body = http_get(base + "/healthz", timeout)
    if status == 0:
        print(f"  {FAIL} Servicio accesible: no hubo respuesta de {base}/healthz")
        print(f"       revisa que la URL sea la correcta y que el servicio este desplegado.")
        return False
    if status != 200:
        print(f"  {FAIL} Servicio accesible: /healthz devolvio {status}")
        return False
    try:
        data = json.loads(body)
    except ValueError:
        print(f"  {FAIL} Servicio accesible: /healthz no devolvio JSON")
        return False
    if not data.get("model_loaded"):
        print(f"  {FAIL} Servicio accesible: responde, pero el modelo no esta cargado "
              f"(status={data.get('status')})")
        print(f"       el servicio esta 'degraded': revisa MODEL_PATH y que el modelo este en la imagen.")
        return False
    print(f"  {OK} Servicio accesible: /healthz ok "
          f"(backend={data.get('backend')}, modelo={data.get('model_version')})")
    return True


def check_contract(base: str, timeout: float) -> bool:
    """2. El contrato esta publicado y expone los tres endpoints."""
    status, body = http_get(base + "/openapi.json", timeout)
    if status != 200:
        print(f"  {FAIL} Contrato publicado: /openapi.json devolvio {status}")
        return False
    try:
        paths = set(json.loads(body).get("paths", {}))
    except ValueError:
        print(f"  {FAIL} Contrato publicado: /openapi.json no devolvio JSON")
        return False
    faltan = [p for p in ("/healthz", "/predict", "/batch-score") if p not in paths]
    if faltan:
        print(f"  {FAIL} Contrato publicado: faltan endpoints en el contrato: {faltan}")
        return False
    print(f"  {OK} Contrato publicado: /predict, /batch-score y /healthz en /openapi.json "
          f"(navegable en {base}/docs)")
    return True


def check_prediction(base: str, fixture: Path, timeout: float) -> tuple[bool, float | None]:
    """3. Una prediccion real: probabilidad valida y una decision de negocio."""
    if not fixture.exists():
        print(f"  {FAIL} Prediccion real: no encuentro el ejemplo {fixture}")
        return False, None
    status, body, latency_ms = http_post_json(base + "/predict", fixture.read_bytes(), timeout)
    if status != 200:
        print(f"  {FAIL} Prediccion real: /predict devolvio {status} (esperaba 200)")
        return False, latency_ms
    try:
        data = json.loads(body)
    except ValueError:
        print(f"  {FAIL} Prediccion real: /predict no devolvio JSON")
        return False, latency_ms
    prob = data.get("churn_probability")
    decision = data.get("decision")
    if not isinstance(prob, (int, float)) or not 0.0 <= prob <= 1.0:
        print(f"  {FAIL} Prediccion real: churn_probability fuera de rango: {prob!r}")
        return False, latency_ms
    if decision not in ("retention_queue", "monitor"):
        print(f"  {FAIL} Prediccion real: decision inesperada: {decision!r}")
        return False, latency_ms
    print(f"  {OK} Prediccion real: prob={prob:.3f}, priority={data.get('priority_score')}, "
          f"decision={decision}  <- la ultima milla: la prediccion dispara una accion")
    return True, latency_ms


def check_validation(base: str, invalid_fixture: Path, timeout: float) -> bool:
    """4. El contrato rechaza un dato invalido con 422."""
    if not invalid_fixture.exists():
        print(f"  {WARN} Validacion de entrada: no encuentro {invalid_fixture}, salteo el chequeo")
        return True
    status, _, _ = http_post_json(base + "/predict", invalid_fixture.read_bytes(), timeout)
    if status == 422:
        print(f"  {OK} Validacion de entrada: un dato invalido devuelve 422 (el contrato lo rechaza)")
        return True
    print(f"  {FAIL} Validacion de entrada: un dato invalido devolvio {status} (esperaba 422)")
    return False


def report_latency(latency_ms: float | None) -> None:
    """5. Latencia de una prediccion (informativo, no cuenta como falla)."""
    if latency_ms is None:
        return
    marker = WARN if latency_ms > LATENCY_WARN_MS else INFO
    nota = "  <- puede ser arranque en frio; manda un request de precalentamiento antes de la demo" \
        if latency_ms > LATENCY_WARN_MS else ""
    print(f"  {marker} Latencia de una prediccion: {latency_ms:.0f} ms{nota}")


def print_manual_reminders() -> None:
    """Lo que el script no puede ver desde afuera: queda para tildar a mano."""
    print("")
    print("Para tildar a mano (no se verifican desde afuera):")
    print(f"  {TODO} Secretos y acceso : sin credenciales en el repo; repo compartido con el docente.")
    print(f"  {TODO} Logs y metrica    : una metrica mirada en la consola de Cloud Run (latencia sirve).")
    print(f"  {TODO} Video de respaldo : una grabacion corta de la demo funcionando, por si falla en vivo.")
    print(f"  {TODO} Fallback definido : que devuelve el servicio si el modelo no responde.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verifica el checklist de pre-demo contra un servicio desplegado."
    )
    parser.add_argument("--url", default="http://127.0.0.1:8080", help="Base URL del servicio.")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE,
                        help="Cliente de ejemplo para /predict.")
    parser.add_argument("--invalid-fixture", type=Path, default=DEFAULT_INVALID,
                        help="Ejemplo invalido para verificar el 422.")
    parser.add_argument("--timeout", type=float, default=30.0, help="Timeout por request (s).")
    args = parser.parse_args()

    base = args.url.rstrip("/")
    print(f"Checklist de pre-demo contra {base}")
    print("")

    results: list[bool] = []
    results.append(check_healthz(base, args.timeout))
    results.append(check_contract(base, args.timeout))
    ok_pred, latency_ms = check_prediction(base, args.fixture, args.timeout)
    results.append(ok_pred)
    results.append(check_validation(base, args.invalid_fixture, args.timeout))
    report_latency(latency_ms)

    print_manual_reminders()

    passed = sum(1 for r in results if r)
    total = len(results)
    print("")
    if passed == total:
        print(f"{OK} {passed}/{total} chequeos automaticos en verde. Lo desplegado esta listo para la demo.")
        raise SystemExit(0)
    print(f"{FAIL} {passed}/{total} chequeos automaticos en verde. Revisa los que fallaron antes de la defensa.")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
