"""Query the lab's three databases over HTTP, using Python's standard library.

    .venv/bin/python query.py metrics 'sum(rate(app_http_requests_total[1m]))'
    .venv/bin/python query.py logs 'service:=checkout event:=checkout_completed'
    .venv/bin/python query.py search checkout --last 15m --min-duration 200ms
    .venv/bin/python query.py trace TRACE_ID

Metrics go to VictoriaMetrics' Prometheus-compatible query API. Logs go to
VictoriaLogs' LogsQL API. Traces go to the Jaeger-compatible query API that
VictoriaTraces serves: there is no Jaeger in the lab, only the same HTTP API.
"""
import argparse
from datetime import datetime, timezone
import json
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

METRICS = "http://127.0.0.1:8428"
LOGS = "http://127.0.0.1:9428"
TRACES = "http://127.0.0.1:10428"


class QueryError(Exception):
    pass


def get(url):
    try:
        with urlopen(url, timeout=20) as response:
            return response.read()
    except HTTPError as error:
        # Show what the database said, not only the status code.
        message = error.read().decode(errors="replace").strip()
        raise QueryError(f"HTTP {error.code} from {url.split('?')[0]}: {message}") from error
    except URLError as error:
        raise QueryError(f"Cannot reach {url.split('?')[0]}: {error.reason}. Is the lab running?") from error


def metrics(expression, timestamp=None):
    params = {"query": expression}
    if timestamp is not None:
        params["time"] = timestamp
    return json.loads(get(METRICS + "/api/v1/query?" + urlencode(params)))


def logs(expression, start=None, end=None):
    params = {"query": expression}
    if start is not None:
        params["start"], params["end"] = start, end
    body = get(LOGS + "/select/logsql/query?" + urlencode(params))
    return [json.loads(line) for line in body.splitlines() if line.strip()]


def get_trace(trace_id):
    if len(trace_id) != 32 or any(c not in "0123456789abcdef" for c in trace_id):
        raise ValueError("Expected a 32-character lowercase hexadecimal trace ID")
    return json.loads(get(TRACES + "/select/jaeger/api/traces/" + trace_id))


def timestamp(value):
    """Require an explicit timezone for readable search windows."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Use an ISO timestamp with a UTC offset, such as 2026-10-16T10:00:00+00:00")
    return parsed.astimezone(timezone.utc).timestamp()


def seconds(value):
    """15m, 1h, or 30s as a number of seconds."""
    match = re.fullmatch(r"(\d+)([smh])", value)
    if not match:
        raise ValueError("Use a duration such as 30s, 15m, or 1h")
    return int(match[1]) * {"s": 1, "m": 60, "h": 3600}[match[2]]


def search_traces(service, start, end, min_duration="200ms", operation="POST /checkout", limit=100):
    start_unix, end_unix = timestamp(start), timestamp(end)
    if end_unix <= start_unix:
        raise ValueError("Search end must be after start")
    params = {"service": service, "operation": operation,
              "start": round(start_unix * 1_000_000), "end": round(end_unix * 1_000_000),
              "minDuration": min_duration, "limit": limit}
    return json.loads(get(TRACES + "/select/jaeger/api/traces?" + urlencode(params)))


def iso(unix):
    return datetime.fromtimestamp(unix, timezone.utc).isoformat(timespec="milliseconds")


def trace_rows(result):
    """One line per trace: start time, root duration, span count, trace ID."""
    rows = []
    for document in result.get("data", []):
        root = next(span for span in document["spans"] if not span.get("references"))
        rows.append((root["startTime"], root["duration"] / 1000, len(document["spans"]), document["traceID"]))
    return sorted(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Query the lab's metrics, logs, and traces.")
    parser.add_argument("signal", choices=("metrics", "logs", "trace", "search"))
    parser.add_argument("query", help="a MetricsQL or LogsQL query, a trace ID, or a service name to search")
    parser.add_argument("--last", default="15m", help="search window ending now, such as 15m or 1h")
    parser.add_argument("--start", help="search window start, with a timezone, instead of --last")
    parser.add_argument("--end", help="search window end, with a timezone, instead of --last")
    parser.add_argument("--min-duration", default="200ms")
    parser.add_argument("--operation", default="POST /checkout")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--json", action="store_true", help="print the full search reply")
    args = parser.parse_args()
    if bool(args.start) != bool(args.end):
        parser.error("give both --start and --end, or neither and use --last")
    try:
        if args.signal == "search":
            start = args.start or iso(time.time() - seconds(args.last))
            end = args.end or iso(time.time())
            result = search_traces(args.query, start, end, args.min_duration, args.operation, args.limit)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                rows = trace_rows(result)
                print(f"{len(rows)} traces from {start} to {end}")
                for started, duration_ms, spans, trace_id in rows:
                    print(f"{iso(started / 1_000_000)[11:23]}  {duration_ms:7.1f} ms  {spans:3d} spans  {trace_id}")
        else:
            result = {"metrics": metrics, "logs": logs, "trace": get_trace}[args.signal](args.query)
            print(json.dumps(result, indent=2))
    except (QueryError, ValueError) as error:
        sys.exit(str(error))
