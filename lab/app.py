"""Two tiny HTTP services. No customer data, payment, or external dependency."""
import atexit
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
import json
import os
import queue
import signal
import threading
import time
from urllib.parse import urlencode, urlsplit, parse_qs
from urllib.request import Request, urlopen

from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST, disable_created_metrics
from opentelemetry import propagate, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from opentelemetry.trace import SpanKind, Status, StatusCode
from basket import BasketValidationError, DEFAULT_BASKET, KEY_FIELDS, STOCK, evaluate_basket
from http_telemetry import HttpTelemetry

SERVICE = os.environ.get("SERVICE", "checkout")
PORT = int(os.environ.get("PORT", "8080" if SERVICE == "checkout" else "8081"))
HOST = os.environ.get("BIND_HOST", "127.0.0.1")
INVENTORY = os.environ.get("INVENTORY_URL", "http://127.0.0.1:8081")
LOG_URL = os.environ.get("LOG_URL", "http://127.0.0.1:9428")
TRACE_URL = os.environ.get("TRACE_URL", "http://127.0.0.1:10428")
INVENTORY_TIMEOUT = float(os.environ.get("INVENTORY_TIMEOUT_SECONDS", "10"))
PHASE = "healthy"

provider = TracerProvider(sampler=ALWAYS_ON,
                         resource=Resource.create({"service.name": SERVICE, "service.version": "book-lab-6"}))
provider.add_span_processor(BatchSpanProcessor(
    OTLPSpanExporter(endpoint=TRACE_URL + "/insert/opentelemetry/v1/traces"),
    schedule_delay_millis=500,
))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("beyond-the-dashboard.lab")
# Expose only the series the book explains; no *_created timestamps.
disable_created_metrics()
requests = Counter("app_http_requests_total", "Finished instrumented HTTP handlers by response status", ["service", "route", "status"])
latency = Histogram("app_http_request_duration_seconds", "HTTP route handler through response flush duration", ["service", "route"],
                    buckets=(.025, .05, .075, .1, .15, .2, .25, .3, .4, .5, 1, 2))
inventory_calls = Counter("checkout_inventory_calls_total", "Inventory HTTP calls from checkout")
# The business answer, separate from the HTTP status: each completed
# POST /checkout response counts once, under the outcome it returned.
OUTCOMES = ("accepted", "out_of_stock", "invalid", "error")
outcomes = Counter("checkout_outcomes_total", "Checkout responses by business outcome", ["outcome"])
route = "/checkout" if SERVICE == "checkout" else "/inventory/check"
for status in ("200", "400", "500"):
    requests.labels(SERVICE, route, status).inc(0)
if SERVICE == "checkout":
    for outcome in OUTCOMES:
        outcomes.labels(outcome).inc(0)
latency.labels(SERVICE, route)
http_telemetry = HttpTelemetry(tracer, requests, latency, SERVICE)
log_queue = queue.Queue(maxsize=10000)


def send_logs():
    while True:
        record = log_queue.get()
        if record is None:
            log_queue.task_done()
            return
        try:
            params = urlencode({"_stream_fields": "service", "_msg_field": "message", "_time_field": "timestamp"})
            request = Request(LOG_URL + "/insert/jsonline?" + params,
                              data=(json.dumps(record) + "\n").encode(),
                              headers={"Content-Type": "application/stream+json"})
            with urlopen(request, timeout=10) as response:
                response.read()
        except Exception as error:
            print(json.dumps({"event": "log_export_failed", "severity": "ERROR", "error": str(error)}), flush=True)
        finally:
            log_queue.task_done()


threading.Thread(target=send_logs, daemon=True).start()


def emit(event, severity="INFO", **fields):
    context = trace.get_current_span().get_span_context()
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), "service": SERVICE,
              "event": event, "message": event.replace("_", " "), "severity": severity,
              "trace_id": format(context.trace_id, "032x"),
              "span_id": format(context.span_id, "016x"), **fields}
    print(json.dumps(record), flush=True)
    try:
        log_queue.put_nowait(record)
    except queue.Full:
        print(json.dumps({"event": "log_queue_full", "severity": "WARN"}), flush=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, status, payload, content_type="application/json"):
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        self.wfile.flush()

    def serve_route(self, route, action):
        try:
            with http_telemetry.measure(self.command, route, self.headers) as request:
                status, payload = action(request.span)
                request.status = status
                self.respond(status, payload)
        except (BrokenPipeError, ConnectionResetError) as error:
            # A failed write is recorded on the HTTP span. The status counter
            # describes the response status, not successful client receipt.
            print(json.dumps({"event": "http_response_failed", "severity": "ERROR",
                              "service": SERVICE, "error": str(error)}), flush=True)

    def do_GET(self):
        parsed = urlsplit(self.path)
        path = parsed.path
        if path == "/health":
            return self.respond(200, {"service": SERVICE, "status": "ok"})
        if path == "/metrics":
            return self.respond(200, generate_latest(), CONTENT_TYPE_LATEST)
        if SERVICE == "inventory" and path == "/inventory/check":
            def inventory(span):
                time.sleep(.04)  # Fixed teaching workload, not a product benchmark.
                params = parse_qs(parsed.query)
                key = tuple(params.get(field, [""])[0] for field in KEY_FIELDS)
                available = STOCK.get(key, 0)
                emit("stock_snapshot_read", **dict(zip(KEY_FIELDS, key)))
                return 200, {"available_quantity": available}
            return self.serve_route(path, inventory)
        self.respond(404, {"error": "unknown route"})

    def do_POST(self):
        global PHASE
        parsed = urlsplit(self.path)
        if parsed.path == "/admin/phase" and SERVICE == "checkout":
            phase = parse_qs(parsed.query).get("name", [""])[0]
            if phase not in ("healthy", "fault", "fixed"):
                return self.respond(400, {"error": "phase must be healthy, fault, or fixed"})
            PHASE = phase
            return self.respond(200, {"phase": PHASE})
        if parsed.path != "/checkout" or SERVICE != "checkout":
            return self.respond(404, {"error": "unknown route"})
        return self.serve_route("/checkout", self.checkout)

    def checkout(self, span):
        phase = PHASE
        failure = {}
        status = 200
        result = {"outcome": "error", "items": []}
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 65536:
                raise BasketValidationError("request body exceeds 64 KiB")
            try:
                payload = json.loads(self.rfile.read(length)) if length else {"basket": DEFAULT_BASKET}
            except (ValueError, UnicodeDecodeError) as error:
                raise BasketValidationError("request body must be JSON") from error
            if not isinstance(payload, dict):
                raise BasketValidationError("request body must be an object")

            def decision(line, scope, choice):
                emit("inventory_lookup_decision", line_id=line["line_id"],
                     **{field: line[field] for field in KEY_FIELDS},
                     lookup_scope=scope, decision=choice)

            def fetch(line, scope):
                with tracer.start_as_current_span("GET /inventory/check", kind=SpanKind.CLIENT,
                                                  attributes={"http.request.method": "GET", "server.address": "inventory"}) as child:
                    decision(line, scope, "fetch")
                    headers = {}
                    propagate.inject(headers)
                    inventory_calls.inc()
                    query = urlencode({field: line[field] for field in KEY_FIELDS})
                    with urlopen(Request(INVENTORY + "/inventory/check?" + query, headers=headers), timeout=INVENTORY_TIMEOUT) as response:
                        snapshot = json.load(response)
                        child.set_attribute("http.response.status_code", response.status)
                        return int(snapshot["available_quantity"])

            result = evaluate_basket(payload.get("basket"), phase == "fault", fetch,
                                     lambda line, scope: decision(line, scope, "reuse"))
        except BasketValidationError as error:
            status = 400
            result = {"outcome": "invalid", "items": []}
            failure = {"error_type": type(error).__name__, "error_message": str(error)}
        except Exception as error:
            status = 500
            failure = {"error_type": type(error).__name__, "error_message": str(error)}
            span.record_exception(error)
            span.set_status(Status(StatusCode.ERROR, str(error)))
        # A business outcome such as out_of_stock is a valid HTTP 200 response.
        # This event records the application result before the response is sent.
        severity = "ERROR" if status >= 500 else "WARN" if status >= 400 else "INFO"
        emit("checkout_completed", severity=severity, status=status, outcome=result["outcome"], **failure)
        span.set_attribute("checkout.outcome", result["outcome"])
        outcomes.labels(result["outcome"]).inc()
        return status, {"status": "ok" if status == 200 else "failed", **result,
                        "trace_id": format(span.get_span_context().trace_id, "032x")}


def shutdown():
    provider.force_flush(timeout_millis=5000)
    provider.shutdown()
    log_queue.join()


atexit.register(shutdown)
signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(SystemExit(0)))
class LocalHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer resolves a hostname for CGI support that this app never uses.
        # Avoid making a localhost lab depend on the host's reverse DNS service.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


server = LocalHTTPServer((HOST, PORT), Handler)
print(json.dumps({"event": "listening", "severity": "INFO", "service": SERVICE, "address": HOST, "port": PORT}), flush=True)
try:
    server.serve_forever()
finally:
    server.server_close()
