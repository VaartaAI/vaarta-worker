"""
OpenTelemetry bootstrap.

Sends logs (and later metrics + traces) to whatever OTLP endpoint is
configured in the standard env vars:
    OTEL_EXPORTER_OTLP_ENDPOINT  e.g. https://otlp-gateway-prod-ap-south-1.grafana.net/otlp
    OTEL_EXPORTER_OTLP_HEADERS   e.g. Authorization=Basic%20...

The OTel SDK reads these on its own, so we don't pass them explicitly.

Call configure_observability(service_name=...) once at process startup,
AFTER configure_logging() has set up structlog. Logs emitted via structlog
or stdlib logging will then also be shipped to the OTLP endpoint.
"""
from __future__ import annotations
import atexit
import os
import logging

from opentelemetry import _logs, metrics
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk.metrics import (
    Counter, Histogram, ObservableCounter, ObservableGauge,
    ObservableUpDownCounter, UpDownCounter, MeterProvider,
)
from opentelemetry.sdk.metrics.export import (
    AggregationTemporality, PeriodicExportingMetricReader,
)
from opentelemetry.sdk.metrics.view import DropAggregation, View
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.resources import Resource


_configured = False


def configure_observability(service_name: str) -> bool:
    """
    Set up OTLP log + metric shipping. Returns True if configured, False if
    disabled (no OTLP endpoint set — local dev fallback).

    Idempotent — calling it twice in the same process is a no-op (so importing
    multiple workers doesn't trigger the "provider already set" warning).
    """
    global _configured
    if _configured:
        return True

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        return False  # no OTLP configured; stay on stdout-only

    resource = Resource.create({
        "service.name": service_name,
        "service.namespace": "vaarta",
    })

    # ── Logs ────────────────────────────────────────────────────────────
    log_provider = LoggerProvider(resource=resource)
    log_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    _logs.set_logger_provider(log_provider)

    # Bridge stdlib logging → OTLP. Anything that goes through `logging` —
    # which includes structlog when wired through stdlib — gets shipped.
    handler = LoggingHandler(level=logging.NOTSET, logger_provider=log_provider)
    logging.getLogger().addHandler(handler)

    # ── Metrics ─────────────────────────────────────────────────────────
    # Grafana Cloud (Mimir backend, Prometheus-compatible) requires
    # CUMULATIVE temporality for everything. DELTA gets rejected with
    # "invalid temporality and type combination".
    cumulative = AggregationTemporality.CUMULATIVE
    cumulative_temporality = {
        Counter: cumulative, UpDownCounter: cumulative, Histogram: cumulative,
        ObservableCounter: cumulative, ObservableUpDownCounter: cumulative,
        ObservableGauge: cumulative,
    }
    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(preferred_temporality=cumulative_temporality),
        export_interval_millis=15_000,   # push every 15s
    )
    # Drop SDK-self metrics (e.g. otel.sdk.metric_reader.collection.duration).
    # Grafana Cloud's OTLP gateway rejects them with "invalid temporality and
    # type combination", which corrupts the whole batch.
    drop_otel_self_metrics = View(
        instrument_name="otel.sdk.*",
        aggregation=DropAggregation(),
    )
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[metric_reader],
        views=[drop_otel_self_metrics],
    )
    metrics.set_meter_provider(meter_provider)

    # One-shot workers (ingest/trend/migrate) exit before either processor
    # flushes. Force a flush + shutdown so we don't lose the last batch.
    atexit.register(log_provider.shutdown)
    atexit.register(meter_provider.shutdown)

    _configured = True
    return True
