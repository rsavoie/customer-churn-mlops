"""Costura de observabilidad de la API (clase 7).

Un solo lugar donde vive el "qué logueamos". La API emite **una línea JSON por evento**
a `stdout`. Cloud Run captura `stdout` y lo manda a Cloud Logging, así que estas líneas
aparecen tal cual en `gcloud run services logs read`: cada request queda con su latencia y su
decisión, listas para filtrar y graficar.

Regla de oro de esta clase: **se loguea la decisión y la métrica, nunca los campos crudos del
cliente**. El payload de features puede traer datos personales; el log guarda el `customer_id`
(un identificador opaco de cuenta), la probabilidad y la decisión, no los atributos del cliente.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from contextlib import contextmanager
from typing import Any, Iterator

# Logger dedicado de la API. No propaga al root para no duplicar líneas con el logger de uvicorn.
logger = logging.getLogger("churn.api")

_configured = False


def configure_logging() -> None:
    """Deja el logger emitiendo JSON crudo a stdout. Idempotente."""
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    _configured = True


@contextmanager
def measure_latency() -> Iterator[dict[str, float]]:
    """Mide el tiempo de pared del bloque y deja los milisegundos en el dict que entrega."""
    holder: dict[str, float] = {"latency_ms": 0.0}
    start = time.perf_counter()
    try:
        yield holder
    finally:
        holder["latency_ms"] = round((time.perf_counter() - start) * 1000, 2)


def log_event(event: str, **fields: Any) -> None:
    """Emite un evento estructurado. `event` nombra el tipo; el resto son campos libres.

    No pasar features crudas del cliente: solo IDs opacos, métricas y decisiones.
    """
    payload = {"event": event, **fields}
    logger.info(json.dumps(payload, ensure_ascii=False))
