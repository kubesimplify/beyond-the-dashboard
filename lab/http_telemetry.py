"""One measurement boundary for the lab's two instrumented HTTP routes."""
from contextlib import contextmanager
from dataclasses import dataclass
import time

from opentelemetry import propagate, trace
from opentelemetry.trace import SpanKind, Status, StatusCode


@dataclass
class RequestMeasurement:
    span: object
    status: int = 500


class HttpTelemetry:
    def __init__(self, tracer, requests, latency, service):
        self.tracer = tracer
        self.requests = requests
        self.latency = latency
        self.service = service

    @contextmanager
    def measure(self, method, route, headers):
        # Both signals use these boundaries. Header parsing has already happened;
        # callers leave this context after writing and flushing the response.
        started_at = time.time_ns()
        started_monotonic = time.perf_counter_ns()
        span = self.tracer.start_span(
            method + " " + route, kind=SpanKind.SERVER,
            context=propagate.extract(headers), start_time=started_at,
            attributes={"http.request.method": method, "http.route": route})
        measurement = RequestMeasurement(span)
        with trace.use_span(span, end_on_exit=False, record_exception=False, set_status_on_exception=False):
            try:
                yield measurement
            except Exception as error:
                span.record_exception(error)
                span.set_attribute("error.type", type(error).__name__)
                span.set_status(Status(StatusCode.ERROR, str(error)))
                raise
            finally:
                elapsed_ns = time.perf_counter_ns() - started_monotonic
                span.set_attribute("http.response.status_code", measurement.status)
                if measurement.status >= 500:
                    span.set_status(Status(StatusCode.ERROR))
                span.end(end_time=started_at + elapsed_ns)
                self.requests.labels(self.service, route, str(measurement.status)).inc()
                self.latency.labels(self.service, route).observe(elapsed_ns / 1e9)
