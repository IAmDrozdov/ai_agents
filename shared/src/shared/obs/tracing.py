"""Shared OpenTelemetry helpers."""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_OFF, ALWAYS_ON, ParentBased, TraceIdRatioBased

from shared.config import Settings


def service_version(package_name: str, default: str = "0.0.0") -> str:
    """Best-effort package version lookup for service resource metadata."""

    try:
        return version(package_name)
    except PackageNotFoundError:
        return default


def _normalize_otlp_endpoint(raw: str) -> str:
    endpoint = raw.rstrip("/")
    if endpoint.startswith("http://"):
        endpoint = endpoint[len("http://") :]
    elif endpoint.startswith("https://"):
        endpoint = endpoint[len("https://") :]
    return endpoint


def _build_resource(settings: Settings, service_name: str, version_str: str) -> Resource:
    return Resource.create(
        {
            "service.name": service_name,
            "service.version": version_str,
            "service.namespace": settings.otel_service_namespace,
            "deployment.environment": settings.otel_deployment_environment,
        }
    )


def _build_exporter(settings: Settings) -> OTLPSpanExporter:
    headers: dict[str, str] | None = None
    if settings.otel_exporter_otlp_headers:
        items = [
            chunk.strip()
            for chunk in settings.otel_exporter_otlp_headers.split(",")
            if chunk.strip()
        ]
        parsed: dict[str, str] = {}
        for item in items:
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            parsed[key.strip()] = value.strip()
        headers = parsed or None

    return OTLPSpanExporter(
        endpoint=_normalize_otlp_endpoint(settings.otel_exporter_otlp_endpoint),
        insecure=True,
        headers=headers,
    )


def _build_sampler(settings: Settings):
    name = settings.otel_traces_sampler.strip().lower()
    if name == "always_off":
        return ALWAYS_OFF
    if name == "parentbased_always_on":
        return ParentBased(ALWAYS_ON)
    if name == "parentbased_always_off":
        return ParentBased(ALWAYS_OFF)
    if name == "traceidratio":
        ratio_raw = settings.otel_traces_sampler_arg or "1.0"
        try:
            ratio = float(ratio_raw)
        except ValueError:
            ratio = 1.0
        ratio = min(max(ratio, 0.0), 1.0)
        return TraceIdRatioBased(ratio)
    return ALWAYS_ON


def init_tracing_provider(
    *,
    settings: Settings,
    service_name: str,
    version_str: str,
    excluded_env_var: str | None = None,
    excluded_env_value: str | None = None,
) -> bool:
    """Initialize global tracer provider for current process."""

    if excluded_env_var and excluded_env_value:
        os.environ.setdefault(excluded_env_var, excluded_env_value)

    provider = TracerProvider(
        resource=_build_resource(settings, service_name, version_str),
        sampler=_build_sampler(settings),
    )
    provider.add_span_processor(BatchSpanProcessor(_build_exporter(settings)))
    trace.set_tracer_provider(provider)
    return True
