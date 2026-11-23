"""Exercise the real checkout process against local failure and export fixtures."""
import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
from socketserver import TCPServer
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from basket import DEFAULT_BASKET

ROOT = Path(__file__).resolve().parent
RECEIPTS = []
OUTCOMES = ('accepted', 'out_of_stock', 'invalid', 'error')


class LocalServer(ThreadingHTTPServer):
    def server_bind(self):
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class Fixture(BaseHTTPRequestHandler):
    mode = 'error'
    records = []
    spans = []

    def log_message(self, *args):
        pass

    def reply(self, status, body):
        self.send_response(status)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if self.mode == 'success':
            return self.reply(200, b'{"available_quantity":20}')
        if self.mode == 'timeout':
            time.sleep(.2)
            return self.reply(200, b'{"available_quantity":20}')
        if self.mode == 'malformed':
            return self.reply(200, b'not json')
        return self.reply(503, b'{"error":"fixture unavailable"}')

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        if self.path.startswith('/insert/jsonline'):
            self.records.extend(json.loads(line) for line in body.splitlines())
        elif self.path.endswith('/v1/traces'):
            request = ExportTraceServiceRequest.FromString(body)
            for resource in request.resource_spans:
                for scope in resource.scope_spans:
                    self.spans.extend(scope.spans)
        self.reply(200, b'{}')


class HttpFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = LocalServer(('127.0.0.1', 0), Fixture)
        threading.Thread(target=cls.fixture.serve_forever, daemon=True).start()
        with socket.socket() as port:
            port.bind(('127.0.0.1', 0))
            cls.port = port.getsockname()[1]
        fixture_url = f'http://127.0.0.1:{cls.fixture.server_port}'
        cls.base = f'http://127.0.0.1:{cls.port}'
        cls.output = tempfile.TemporaryFile(mode='w+')
        cls.child = subprocess.Popen([sys.executable, str(ROOT / 'app.py')], cwd=ROOT,
            env={**os.environ, 'SERVICE':'checkout', 'PORT':str(cls.port), 'BIND_HOST':'127.0.0.1',
                 'INVENTORY_URL':fixture_url, 'INVENTORY_TIMEOUT_SECONDS':'.025',
                 'LOG_URL':fixture_url, 'TRACE_URL':fixture_url},
            stdout=cls.output, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with urlopen(cls.base + '/health', timeout=1):
                    break
            except Exception:
                time.sleep(.1)
        else:
            cls.child.terminate()
            cls.child.wait(timeout=5)
            cls.output.seek(0)
            raise AssertionError(cls.output.read())
        cls.post('/admin/phase?name=fault')

    @classmethod
    def tearDownClass(cls):
        cls.child.terminate()
        try:
            cls.child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.child.kill()
            cls.child.wait()
        cls.fixture.shutdown()
        cls.fixture.server_close()
        cls.output.close()

    @classmethod
    def post(cls, path, body=b''):
        try:
            response = urlopen(Request(cls.base + path, data=body), timeout=3)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def counter(self, name):
        with urlopen(self.base + '/metrics') as response:
            for line in response.read().decode().splitlines():
                if line.startswith(name + ' '):
                    return float(line.split()[-1])
        self.fail('metric absent: ' + name)

    def outcome_counts(self):
        return {outcome: self.counter(f'checkout_outcomes_total{{outcome="{outcome}"}}') for outcome in OUTCOMES}

    def http_checkout_total(self):
        return sum(self.counter(f'app_http_requests_total{{route="/checkout",service="checkout",status="{status}"}}')
                   for status in ('200', '400', '500'))

    def test_each_outcome_counts_once_and_matches_http_total(self):
        with urlopen(self.base + '/metrics') as response:
            exposition = response.read().decode()
        self.assertNotIn('_created', exposition)
        over_demand = json.dumps({'basket':[{**line, 'quantity':4} for line in DEFAULT_BASKET]}).encode()
        steps = [('accepted', 'success', b'', 200), ('out_of_stock', 'success', over_demand, 200),
                 ('invalid', 'success', b'{"basket":[]}', 400), ('error', 'error', b'', 500)]
        deltas = []
        for outcome, mode, body, expected_status in steps:
            with self.subTest(outcome=outcome):
                Fixture.mode = mode
                before = self.outcome_counts()
                status, response = self.post('/checkout', body)
                after = self.outcome_counts()
                self.assertEqual(status, expected_status)
                self.assertEqual(response['outcome'], outcome)
                change = {key: after[key] - before[key] for key in OUTCOMES}
                self.assertEqual(change, {key: 1 if key == outcome else 0 for key in OUTCOMES})
                deltas.append({'outcome': outcome, 'http_status': status, 'counter_deltas': change})
        totals = self.outcome_counts()
        self.assertEqual(sum(totals.values()), self.http_checkout_total())
        RECEIPTS.append({'case':'outcome_counter', 'steps':deltas, 'outcome_totals':totals,
                         'http_checkout_total':self.http_checkout_total(), 'created_series':0})

    def test_http_error_and_timeout_each_count_one_attempt(self):
        for mode in ('error', 'timeout', 'malformed'):
            with self.subTest(mode=mode):
                Fixture.mode = mode
                before = self.counter('checkout_inventory_calls_total')
                failed_before = self.counter('app_http_requests_total{route="/checkout",service="checkout",status="500"}')
                error_before = self.counter('checkout_outcomes_total{outcome="error"}')
                status, response = self.post('/checkout')
                self.assertEqual(status, 500)
                self.assertEqual(response['outcome'], 'error')
                self.assertEqual(self.counter('checkout_outcomes_total{outcome="error"}') - error_before, 1)
                self.assertEqual(self.counter('checkout_inventory_calls_total') - before, 1)
                self.assertEqual(self.counter('app_http_requests_total{route="/checkout",service="checkout",status="500"}') - failed_before, 1)
                trace_id = response['trace_id']
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    records = [r for r in Fixture.records if r['trace_id'] == trace_id]
                    spans = [s for s in Fixture.spans if s.trace_id.hex() == trace_id]
                    if len(records) == 2 and len(spans) == 2:
                        break
                    time.sleep(.05)
                self.assertEqual(len(records), 2)
                self.assertEqual(len(spans), 2)
                root = next(s for s in spans if s.name == 'POST /checkout')
                client = next(s for s in spans if s.name == 'GET /inventory/check')
                self.assertEqual(root.status.code, 2)
                self.assertEqual(client.status.code, 2)
                self.assertEqual(client.parent_span_id, root.span_id)
                decision = next(r for r in records if r['event'] == 'inventory_lookup_decision')
                self.assertEqual(decision['span_id'], client.span_id.hex())
                self.assertEqual(decision['line_id'], 'line-1')
                self.assertEqual(decision['decision'], 'fetch')
                completion = next(r for r in records if r['event'] == 'checkout_completed')
                self.assertEqual(completion['status'], 500)
                self.assertEqual(completion['outcome'], 'error')
                self.assertEqual(completion['severity'], 'ERROR')
                self.assertEqual(decision['severity'], 'INFO')
                for record in records:
                    self.assertFalse({'duration_ms','inventory_calls','phase'}.intersection(record))
                RECEIPTS.append({'case':mode, 'http_status':status, 'response':response,
                                 'attempt_counter_delta':1, 'failure_counter_delta':1, 'logs':records,
                                 'span_count':len(spans), 'root_error':True, 'client_error':True})

    def test_invalid_basket_has_no_inventory_attempt(self):
        before = self.counter('checkout_inventory_calls_total')
        invalid_before = self.counter('checkout_outcomes_total{outcome="invalid"}')
        status, response = self.post('/checkout', b'{"basket":[]}')
        self.assertEqual(status, 400)
        self.assertEqual(response['outcome'], 'invalid')
        self.assertEqual(self.counter('checkout_inventory_calls_total'), before)
        self.assertEqual(self.counter('checkout_outcomes_total{outcome="invalid"}') - invalid_before, 1)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            records = [r for r in Fixture.records if r['trace_id'] == response['trace_id']]
            if records:
                break
            time.sleep(.05)
        completion, = records
        self.assertEqual((completion['event'], completion['outcome'], completion['severity'], completion['status']),
                         ('checkout_completed', 'invalid', 'WARN', 400))
        RECEIPTS.append({'case':'invalid_basket', 'http_status':status, 'response':response, 'attempt_counter_delta':0,
                         'outcome_counter_delta':{'invalid':1}, 'logs':records})

    def test_out_of_stock_is_http_200_with_separate_business_outcome(self):
        Fixture.mode = 'success'
        self.post('/admin/phase?name=fixed')
        body = json.dumps({'basket':[{**line, 'quantity':4} for line in DEFAULT_BASKET]}).encode()
        successful_before = self.counter('app_http_requests_total{route="/checkout",service="checkout",status="200"}')
        failed_before = self.counter('app_http_requests_total{route="/checkout",service="checkout",status="500"}')
        duration_before = self.counter('app_http_request_duration_seconds_sum{route="/checkout",service="checkout"}')
        out_of_stock_before = self.counter('checkout_outcomes_total{outcome="out_of_stock"}')
        status, response = self.post('/checkout', body)
        self.assertEqual(status, 200)
        self.assertEqual(response['outcome'], 'out_of_stock')
        self.assertEqual(self.counter('checkout_outcomes_total{outcome="out_of_stock"}') - out_of_stock_before, 1)
        self.assertEqual(response['items'][0]['required_quantity'], 24)
        self.assertEqual(response['items'][0]['available_quantity'], 20)
        self.assertEqual(self.counter('app_http_requests_total{route="/checkout",service="checkout",status="200"}') - successful_before, 1)
        self.assertEqual(self.counter('app_http_requests_total{route="/checkout",service="checkout",status="500"}'), failed_before)
        duration = self.counter('app_http_request_duration_seconds_sum{route="/checkout",service="checkout"}') - duration_before
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            records = [r for r in Fixture.records if r['trace_id'] == response['trace_id']]
            spans = [s for s in Fixture.spans if s.trace_id.hex() == response['trace_id']]
            if len(records) == 7 and len(spans) == 2:
                break
            time.sleep(.05)
        self.assertEqual(len(records), 7)
        root = next(s for s in spans if s.name == 'POST /checkout')
        self.assertEqual(root.status.code, 0)
        self.assertAlmostEqual(duration, (root.end_time_unix_nano - root.start_time_unix_nano) / 1e9, places=10)
        completion = next(r for r in records if r['event'] == 'checkout_completed')
        self.assertEqual(completion['outcome'], 'out_of_stock')
        self.assertEqual(completion['severity'], 'INFO')
        RECEIPTS.append({'case':'out_of_stock', 'http_status':status, 'response':response,
                         'logs':records, 'http_200_counter_delta':1, 'http_500_counter_delta':0,
                         'metric_duration_seconds':duration,
                         'server_span_duration_seconds':(root.end_time_unix_nano-root.start_time_unix_nano)/1e9})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='evidence/http-checks.json')
    args = parser.parse_args()
    output = ROOT / args.output
    if output.exists():
        raise SystemExit('Refusing to overwrite ' + str(output))
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(HttpFailureTests))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'tested_at_utc':datetime.now(timezone.utc).isoformat(),
                                 'status':'passed' if result.wasSuccessful() else 'failed',
                                 'checks':RECEIPTS}, indent=2) + '\n')
    raise SystemExit(0 if result.wasSuccessful() else 1)
