"""Check that HTTP metrics and spans describe the same completed work."""
import unittest
from unittest.mock import patch

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from prometheus_client import CollectorRegistry, Counter, Histogram

from http_telemetry import HttpTelemetry


class HttpBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.exporter = InMemorySpanExporter()
        self.provider = TracerProvider()
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.registry = CollectorRegistry()
        self.requests = Counter('test_requests', 'Requests', ['service', 'route', 'status'], registry=self.registry)
        self.latency = Histogram('test_duration_seconds', 'Duration', ['service', 'route'], registry=self.registry)
        self.telemetry = HttpTelemetry(self.provider.get_tracer('test'), self.requests, self.latency, 'checkout')

    def tearDown(self):
        self.provider.shutdown()

    def test_request_includes_response_work_and_uses_one_duration(self):
        clock = [1_000_000_000]
        with patch('http_telemetry.time.time_ns', return_value=100_000_000_000), \
             patch('http_telemetry.time.perf_counter_ns', side_effect=lambda: clock[0]):
            with self.telemetry.measure('POST', '/checkout', {}) as request:
                clock[0] += 40_000_000  # Application operation.
                request.status = 200
                self.assertEqual(self.exporter.get_finished_spans(), ())
                self.assertIsNone(self.registry.get_sample_value('test_requests_total',
                    {'service':'checkout', 'route':'/checkout', 'status':'200'}))
                clock[0] += 10_000_000  # Serialization and response write/flush.
        span, = self.exporter.get_finished_spans()
        seconds = (span.end_time - span.start_time) / 1e9
        self.assertEqual(seconds, .05)
        self.assertEqual(self.registry.get_sample_value('test_duration_seconds_sum',
                         {'service':'checkout', 'route':'/checkout'}), seconds)
        self.assertEqual(self.registry.get_sample_value('test_requests_total',
                         {'service':'checkout', 'route':'/checkout', 'status':'200'}), 1)

    def test_write_failure_keeps_response_status_and_marks_trace_error(self):
        with self.assertRaises(BrokenPipeError):
            with self.telemetry.measure('POST', '/checkout', {}) as request:
                request.status = 200
                raise BrokenPipeError('caller disconnected')
        span, = self.exporter.get_finished_spans()
        self.assertEqual(span.status.status_code.name, 'ERROR')
        self.assertEqual(span.attributes['http.response.status_code'], 200)
        self.assertEqual(span.attributes['error.type'], 'BrokenPipeError')
        self.assertEqual(len(span.events), 1)
        self.assertEqual(self.registry.get_sample_value('test_requests_total',
                         {'service':'checkout', 'route':'/checkout', 'status':'200'}), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
