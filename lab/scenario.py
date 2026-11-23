"""Record the lab run used in the book: the reader's steps, with every API response saved.

It sends one checkout, then runs traffic.py's three steps (v1, v2, v2.1) back to back,
checks every signal as it goes, and writes the evidence the book quotes.
"""
import argparse
from datetime import datetime, timezone
import json
import hashlib
import math
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from query import METRICS, logs, metrics, get_trace, search_traces
from traffic import CHECKOUT, VERSIONS, closing, opening, post, send, switch
from basket import DEFAULT_BASKET, STOCK, evaluate_basket, stock_key

ROOT = Path(__file__).resolve().parent
RATE = 'sum(rate(app_http_requests_total{service="checkout"}[10s]))'
ERROR = 'sum(rate(app_http_requests_total{service="checkout",status=~"5.."}[10s]))/' + RATE + '*100'
P95 = 'histogram_quantile(0.95,sum by(le)(rate(app_http_request_duration_seconds_bucket{service="checkout"}[10s])))'
# Dependency and business views of the same phases. Each is evaluated at the
# phase's settled query time; timing values are observations, not pass criteria.
INVENTORY_RATE = 'sum(rate(app_http_requests_total{service="inventory"}[10s]))'
INVENTORY_P95 = ('histogram_quantile(0.95, sum by (le) (rate('
                 'app_http_request_duration_seconds_bucket{service="inventory"}[10s])))')
CALLS_PER_CHECKOUT = ('sum(rate(checkout_inventory_calls_total[10s])) / '
                      'sum(rate(app_http_requests_total{service="checkout",route="/checkout"}[10s]))')
WITHIN_200MS = ('sum(rate(app_http_request_duration_seconds_bucket{service="checkout",le="0.2"}[10s])) / '
                'sum(rate(app_http_request_duration_seconds_count{service="checkout"}[10s]))')
ERROR_RATIO = ('sum(rate(app_http_requests_total{service="checkout",status=~"5.."}[10s])) / '
               'sum(rate(app_http_requests_total{service="checkout"}[10s]))')
OUTCOME_RATES = 'sum by (outcome) (rate(checkout_outcomes_total[10s]))'
OUTCOME_TOTALS = 'sum by (outcome) (checkout_outcomes_total)'
OUTCOMES = ("accepted", "out_of_stock", "invalid", "error")
VERSION_OF = {phase: version for version, phase in VERSIONS.items()}
PAUSE = 15  # seconds between the end of one version's traffic and the start of the next
# First queries a reader types in VMUI, evaluated during v1.
SELECTOR = 'app_http_requests_total{service="checkout"}'
BASICS = [("selector", SELECTOR), ("rate", 'rate(app_http_requests_total{service="checkout"}[10s])'),
          ("sum_rate", RATE), ("sum_by_status", 'sum by (status) (rate(app_http_requests_total{service="checkout"}[10s]))')]
# How many checkouts made each kind of stock lookup, from the decision logs alone.
LOG_STATS = "service:=checkout event:=inventory_lookup_decision | stats by (lookup_scope) count_uniq(trace_id) as checkouts"
ALERTS = 'ALERTS{alertname="CheckoutSlow"}'
VMALERT = "http://127.0.0.1:8880"


def post_body(path, body):
    """POST a raw body and return (HTTP status, JSON reply), including 4xx replies."""
    request = Request(CHECKOUT + path, data=body, headers={"Content-Type": "application/json"})
    try:
        response = urlopen(request, timeout=15)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.load(response)


def checkout_metrics_text():
    with urlopen(CHECKOUT + "/metrics", timeout=10) as response:
        return response.read().decode()


def checkout_counters():
    """Read the business outcome counter and the HTTP /checkout counter directly."""
    outcomes, http = {}, {}
    for line in checkout_metrics_text().splitlines():
        if line.startswith("checkout_outcomes_total{"):
            outcomes[line.split('outcome="', 1)[1].split('"', 1)[0]] = float(line.split()[-1])
        elif line.startswith("app_http_requests_total{") and 'route="/checkout"' in line:
            http[line.split('status="', 1)[1].split('"', 1)[0]] = float(line.split()[-1])
    assert set(outcomes) == set(OUTCOMES), outcomes
    return outcomes, http


def vector_by(result, label):
    return {row["metric"].get(label, ""): float(row["value"][1]) for row in result["data"]["result"]}


def nearest_rank_p95(values):
    values = sorted(values)
    return values[math.ceil(.95 * len(values)) - 1]


def write(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def scalar(result):
    rows = result["data"]["result"]
    return float(rows[0]["value"][1]) if rows else None


def check_parentage(trace, expected_calls):
    document = trace["data"][0]
    spans = document["spans"]
    by_id = {span["spanID"]: span for span in spans}
    roots = [span for span in spans if not span.get("references")]
    assert len(roots) == 1 and roots[0]["operationName"] == "POST /checkout"
    root = roots[0]
    def tags(span):
        return {tag["key"]: tag["value"] for tag in span["tags"]}
    def service(span):
        return document["processes"][span["processID"]]["serviceName"]
    assert service(root) == "checkout" and tags(root)["span.kind"] == "server"
    assert {p["serviceName"] for p in document["processes"].values()} == {"checkout", "inventory"}
    for span in spans:
        assert span["traceID"] == document["traceID"]
        assert math.isfinite(span["duration"]) and span["duration"] >= 0
        for reference in span.get("references", []):
            assert reference["refType"] == "CHILD_OF"
            assert reference["spanID"] in by_id
            assert reference["traceID"] == document["traceID"]
    clients = [span for span in spans if span is not root and service(span) == "checkout"]
    servers = [span for span in spans if service(span) == "inventory"]
    assert len(clients) == expected_calls and len(servers) == expected_calls
    for client in clients:
        assert client["operationName"] == "GET /inventory/check"
        assert tags(client)["span.kind"] == "client"
        assert len(client["references"]) == 1
        assert client["references"][0]["spanID"] == root["spanID"]
        children = [span for span in servers if any(ref["spanID"] == client["spanID"] for ref in span["references"])]
        assert len(children) == 1, "Each inventory client span must have one inventory server child"
        server = children[0]
        assert server["operationName"] == "GET /inventory/check"
        assert tags(server)["span.kind"] == "server"
        assert len(server["references"]) == 1


def utc(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="milliseconds")


def raw_inventory_calls():
    with urlopen(CHECKOUT + "/metrics", timeout=10) as response:
        for line in response.read().decode().splitlines():
            if line.startswith("checkout_inventory_calls_total "):
                return int(float(line.split()[1]))
    raise AssertionError("Missing inventory attempt counter")


def until_ready(action, predicate, description):
    deadline = time.monotonic() + 30
    last_error = None
    while time.monotonic() < deadline:
        try:
            result = action()
            if predicate(result):
                return result
        except Exception as error:
            last_error = error
        time.sleep(.5)
    raise AssertionError(f"Timed out waiting for {description}: {last_error}")


def check_logs(log_records, trace, expected_calls):
    document = trace["data"][0]
    spans = {span["spanID"]: span for span in document["spans"]}
    decisions = [row for row in log_records if row["event"] == "inventory_lookup_decision"]
    completions = [row for row in log_records if row["event"] == "checkout_completed"]
    assert len(decisions) == 6 and len(completions) == 1
    assert completions[0]["outcome"] == "accepted" and int(completions[0]["status"]) == 200
    assert {row["line_id"] for row in decisions} == {line["line_id"] for line in DEFAULT_BASKET}
    for row in log_records:
        assert row["trace_id"] == document["traceID"] and row["span_id"] in spans
        assert row["severity"] == "INFO"
        assert not {"duration_ms", "inventory_calls", "phase"}.intersection(row)
    for row in decisions:
        assert (row["sku"], row["warehouse"], row["variant"]) == ("BOOK-001", "east", "paperback")
        assert row["lookup_scope"] == ("line" if expected_calls == 6 else "request")
        tags = {tag["key"]: tag["value"] for tag in spans[row["span_id"]]["tags"]}
        assert tags["span.kind"] == ("client" if row["decision"] == "fetch" else "server")
    fetched = [row for row in decisions if row["decision"] == "fetch"]
    assert len(fetched) == expected_calls and len({row["span_id"] for row in fetched}) == expected_calls
    assert sum(row["decision"] == "reuse" for row in decisions) == 6 - expected_calls


def save_time_windows(output, phases):
    phase_windows = []
    for summary in phases:
        rows = json.loads((output / f"{summary['phase']}-requests.json").read_text())
        phase_windows.append({"phase": summary["phase"], "requests": len(rows),
                              "start_utc": utc(summary["started_unix"]),
                              "end_utc": utc(rows[-1]["received_at_unix"]),
                              "start_unix": summary["started_unix"],
                              "end_unix": rows[-1]["received_at_unix"],
                              "metrics_evaluated_at_utc": utc(summary["query_time_unix"])})
    # The first 10s let the metric lookbehind fill with this run's requests.
    # The final 10s include the last scrape and the short quiet period after it.
    ui_start = math.ceil(phase_windows[0]["start_unix"] + 10)
    ui_end = math.ceil(phase_windows[-1]["end_unix"]) + 10
    windows = {"timezone": "UTC", "utc_offset": "+00:00",
               "run_start_utc": phase_windows[0]["start_utc"],
               "run_end_utc": phase_windows[-1]["end_utc"],
               "recommended_ui_range": {"start_utc": utc(ui_start), "end_utc": utc(ui_end),
                                        "start_unix": ui_start, "end_unix": ui_end},
               "metric_lookbehind_seconds": 10, "last_sample_margin_seconds": 10,
               "note": "The chart starts 10 seconds after load begins so its lookbehind belongs to this run. The final margin includes the last scrape. Raw request files retain every request.",
               "phases": phase_windows}
    write(output / "time-windows.json", windows)
    return windows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="evidence/local-run")
    parser.add_argument("--execution", choices=("native", "compose"), default="native")
    args = parser.parse_args()
    output = ROOT / args.output
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"Output {output} already has evidence. Choose another --output directory.")
    output.mkdir(parents=True, exist_ok=True)
    environment = {"tested_at_utc": datetime.now(timezone.utc).isoformat(),
                   "os": platform.platform(), "machine": platform.machine(),
                   "python": sys.version, "backend_versions": json.loads((ROOT / "versions.json").read_text()),
                   "execution": args.execution,
                   "workload": "one first checkout; then 60 requests per version (v1, v2, v2.1), one scheduled "
                               "every 0.5 seconds; then 3 out-of-stock and 2 invalid checkouts after the timed phases",
                   "note": "Synthetic fixed delay; teaching measurements, not a backend benchmark."}
    environment["application_version"] = "book-lab-6"
    environment["source_sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                    for path in sorted(ROOT.glob("*.py"))}
    for key, command in [("cpu", ["sysctl", "-n", "machdep.cpu.brand_string"]),
                         ("memory_bytes", ["sysctl", "-n", "hw.memsize"])]:
        result = subprocess.run(command, text=True, capture_output=True) if platform.system() == "Darwin" else None
        environment[key] = result.stdout.strip() if result and result.returncode == 0 else "not collected"
    environment["dependencies"] = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True).splitlines()
    write(output / "environment.json", environment)
    if (ROOT / ".cache/downloads.json").exists():
        (output / "downloads.json").write_bytes((ROOT / ".cache/downloads.json").read_bytes())
    phases = []
    search_plans = {}
    first = post("/checkout")
    first["received_at_unix"] = time.time()
    write(output / "curl-response.json", {key: first[key] for key in ("status", "outcome", "items", "trace_id")})
    first_trace = until_ready(lambda: get_trace(first["trace_id"]), lambda result: len(result.get("data", [{}])[0].get("spans", [])) == 3,
                              "the first checkout's three spans")
    write(output / "first-checkout-trace.json", first_trace)
    first_logs = until_ready(lambda: logs(f'trace_id:={first["trace_id"]} | sort by (_time)'), lambda result: len(result) == 8,
                             "the first checkout's seven checkout logs and one inventory log")
    write(output / "first-checkout-logs.json", first_logs)
    outcomes_before, http_before = checkout_counters()
    expected_business = evaluate_basket(DEFAULT_BASKET, False, lambda line, _: STOCK[stock_key(line)], lambda *_: None)
    for phase in ("healthy", "fault", "fixed"):
        version = VERSION_OF[phase]
        if phases:
            # Keep the versions apart in graphs, as they are when a reader runs each step by hand.
            previous_end = json.loads((output / f"{phases[-1]['phase']}-requests.json").read_text())[-1]["received_at_unix"]
            time.sleep(max(0, previous_end + PAUSE - time.time()))
        print(f"Running {version} ({phase}): 60 requests at 2 requests/second", flush=True)
        switch(version)
        print(opening(version, 60), flush=True)
        started = time.time()
        calls = {"previous": raw_inventory_calls()}

        def inventory_attempts():
            current = raw_inventory_calls()
            attempts, calls["previous"] = current - calls["previous"], current
            return {"observed_inventory_attempts": attempts}

        rows = send(60, .5, inventory_attempts)
        # What traffic.py prints for this step, from the same functions.
        (output / f"{phase}-traffic.txt").write_text("\n".join([opening(version, 60), *closing(rows, started)]) + "\n")
        if phase == "fault":
            # vmalert evaluates 30 seconds in the past (-rule.evalDelay, matching VictoriaMetrics'
            # -search.latencyOffset) and the rule waits 10 seconds more, so wait for it to fire.
            deadline = time.monotonic() + 90
            while True:
                with urlopen(VMALERT + "/api/v1/alerts", timeout=10) as response:
                    alerts = json.load(response)
                if any(a["name"] == "CheckoutSlow" and a["state"] == "firing" for a in alerts["data"]["alerts"]):
                    break
                assert time.monotonic() < deadline, "CheckoutSlow did not fire during v2"
                time.sleep(1)
            write(output / "alerts-during-v2.json", {"read_at_utc": utc(time.time()), "v2_started_utc": utc(started),
                                                     "v2_last_request_utc": utc(rows[-1]["received_at_unix"]), "response": alerts})
        # Allow exports to finish. Query settled metrics after all phases below.
        time.sleep(3)
        query_time = rows[-1]["received_at_unix"] - 5
        write(output / f"{phase}-requests.json", rows)
        search_args = {"service": "checkout", "operation": "POST /checkout",
                       "start": utc(started), "end": utc(rows[-1]["received_at_unix"] + 1),
                       "min_duration": "200ms" if phase == "fault" else "0ms", "limit": 100}
        found = until_ready(lambda: search_traces(**search_args), lambda result: len(result.get("data", [])) >= 1,
                            "trace search results")
        write(output / f"{phase}-search.json", {"arguments": search_args, "result": found})
        search_plans[phase] = search_args
        # Discover the trace through service/time/duration, without a supplied trace ID.
        def root_duration(document):
            return next(span["duration"] for span in document["spans"] if not span.get("references"))
        candidates = sorted(found["data"], key=root_duration)
        selected = candidates[len(candidates) // 2]
        trace_id = selected["traceID"]
        assert trace_id in {row["trace_id"] for row in rows}, "Search returned a trace outside this phase"
        trace = get_trace(trace_id)
        write(output / f"{phase}-trace.json", trace)
        log_query = f'service:=checkout trace_id:={trace_id} | sort by (_time)'
        log_records = until_ready(lambda: logs(log_query), lambda result: len(result) == 7,
                                 "six decision logs and one completion")
        write(output / f"{phase}-logs.json", log_records)
        spans = trace.get("data", [{}])[0].get("spans", []) if trace.get("data") else []
        durations = sorted(row["client_duration_ms"] for row in rows)
        summary = {"phase": phase, "version": version, "requests": len(rows), "started_unix": started, "query_time_unix": query_time,
                   "client_mean_ms": round(statistics.mean(durations), 3),
                   "client_p95_ms": durations[math.ceil(.95 * len(durations)) - 1],
                   "inventory_calls_per_checkout": rows[0]["observed_inventory_attempts"],
                   "business_result": expected_business,
                   "http_errors": sum(row["status"] != "ok" for row in rows),
                   "example_trace_id": trace_id, "example_trace_span_count": len(spans),
                   "example_log_count": len(log_records), "trace_search_results": len(candidates),
                   "example_root_duration_ms": root_duration(selected) / 1000,
                   "example_client_span_id": next(row["span_id"] for row in log_records
                                                   if row.get("decision") == "fetch")}
        expected_spans = 13 if phase == "fault" else 3
        expected_calls = 6 if phase == "fault" else 1
        assert len(rows) == 60, (phase, "request count", len(rows))
        assert all(row["observed_inventory_attempts"] == expected_calls for row in rows), (phase, "inventory call count")
        assert all({key: row[key] for key in ("outcome", "items")} == expected_business for row in rows)
        assert len(spans) == expected_spans, (phase, "span count", len(spans), expected_spans)
        check_logs(log_records, trace, expected_calls)
        check_parentage(trace, expected_calls)
        span_query = f'service:=checkout trace_id:={trace_id} span_id:={summary["example_client_span_id"]}'
        span_logs = logs(span_query)
        assert len(span_logs) == 1 and span_logs[0]["decision"] == "fetch"
        write(output / f"{phase}-span-logs.json", {"query": span_query, "result": span_logs})
        assert all(row["status"] == "ok" for row in rows), "HTTP failure in scenario"
        phases.append(summary)
        print(json.dumps(summary), flush=True)
    # The /metrics page after the 180 timed requests, before any post-run check.
    (output / "metrics-excerpt.txt").write_text(checkout_metrics_text())
    # VictoriaMetrics defaults to a 30s query latency offset. Query fixed historical
    # timestamps after that delay so a short lab run does not read partial final buckets.
    print("Waiting 35 seconds for complete metric query windows", flush=True)
    time.sleep(35)
    for summary in phases:
        phase = summary["phase"]
        metric_receipts = {name: {"query": query, "result": metrics(query, summary["query_time_unix"])}
                           for name, query in [("request_rate", RATE), ("error_percent", ERROR), ("p95_seconds", P95)]}
        write(output / f"{phase}-metrics.json", metric_receipts)
        summary["metric_request_rate"] = scalar(metric_receipts["request_rate"]["result"])
        summary["metric_error_percent"] = scalar(metric_receipts["error_percent"]["result"])
        summary["metric_histogram_p95_seconds"] = scalar(metric_receipts["p95_seconds"]["result"])
        assert all(value is not None and math.isfinite(value) for value in (
            summary["metric_request_rate"], summary["metric_error_percent"],
            summary["metric_histogram_p95_seconds"])), (phase, "missing or non-finite telemetry")
        assert summary["metric_request_rate"] > 0, summary
        assert summary["metric_error_percent"] == 0, summary
        assert summary["metric_histogram_p95_seconds"] > 0, summary
        extra = {name: {"query": query, "result": metrics(query, summary["query_time_unix"])}
                 for name, query in [("inventory_request_rate", INVENTORY_RATE),
                                     ("inventory_p95_seconds", INVENTORY_P95),
                                     ("calls_per_checkout", CALLS_PER_CHECKOUT),
                                     ("share_within_200ms", WITHIN_200MS),
                                     ("error_ratio_plain", ERROR_RATIO),
                                     ("outcome_rates", OUTCOME_RATES)]}
        write(output / f"{phase}-metrics.json", {**metric_receipts, **extra})
        summary["metric_inventory_request_rate"] = scalar(extra["inventory_request_rate"]["result"])
        summary["metric_inventory_p95_seconds"] = scalar(extra["inventory_p95_seconds"]["result"])
        summary["metric_calls_per_checkout"] = scalar(extra["calls_per_checkout"]["result"])
        summary["metric_share_within_200ms"] = scalar(extra["share_within_200ms"]["result"])
        summary["metric_error_ratio_plain"] = scalar(extra["error_ratio_plain"]["result"])
        summary["metric_outcome_rates"] = vector_by(extra["outcome_rates"]["result"], "outcome")
        values = [summary[key] for key in ("metric_inventory_request_rate", "metric_inventory_p95_seconds",
                                           "metric_calls_per_checkout", "metric_share_within_200ms",
                                           "metric_error_ratio_plain")]
        assert all(value is not None and math.isfinite(value) for value in values), (phase, "dependency metrics", values)
        assert summary["metric_inventory_request_rate"] > 0 and summary["metric_inventory_p95_seconds"] > 0, summary
        assert 0 <= summary["metric_share_within_200ms"] <= 1 and summary["metric_error_ratio_plain"] == 0, summary
        expected_calls = 6 if phase == "fault" else 1
        # A ten-second rate ratio can gain or lose one completion at the window edges.
        # The exact per-request counts are checked above from the raw counter deltas.
        assert abs(summary["metric_calls_per_checkout"] / expected_calls - 1) <= .15, (phase, "calls per checkout", summary)
        rates = summary["metric_outcome_rates"]
        assert set(rates) == set(OUTCOMES) and all(math.isfinite(v) and v >= 0 for v in rates.values()), rates
        assert rates["accepted"] > 0 and rates["out_of_stock"] == rates["invalid"] == rates["error"] == 0, rates
        # Settled search: the first populated search above may still be filling.
        settled = search_traces(**search_plans[phase])
        write(output / f"{phase}-settled-search.json", {"arguments": search_plans[phase], "result": settled})
        roots = [next(span["duration"] for span in document["spans"] if not span.get("references")) / 1000
                 for document in settled["data"]]
        summary["settled_trace_search_results"] = len(settled["data"])
        summary["settled_root_span_p95_ms"] = nearest_rank_p95(roots)
        assert summary["settled_trace_search_results"] == 60, (phase, "settled search", len(settled["data"]))
        print(json.dumps(summary), flush=True)
    write(output / "summary.json", phases)
    healthy = phases[0]
    v1_done = json.loads((output / "healthy-requests.json").read_text())[-1]["received_at_unix"] + 6
    write(output / "basics-metrics.json", {
        "note": "The first queries in VMUI. The selector is read once v1 has finished; the rates during v1, "
                "at the same time as healthy-metrics.json.",
        "selector_after_v1": {"query": SELECTOR, "time_unix": v1_done, "time_utc": utc(v1_done),
                              "result": metrics(SELECTOR, v1_done)},
        "time_unix": healthy["query_time_unix"], "time_utc": utc(healthy["query_time_unix"]),
        "queries": {name: {"query": query, "result": metrics(query, healthy["query_time_unix"])} for name, query in BASICS}})
    # From the first checkout, as a reader's "last hour" would include it.
    window = lambda last_phase: (utc(first["received_at_unix"] - 2), utc(last_phase["query_time_unix"] + 6))
    stats = {}
    for label, (start, end) in [("first_checkout_to_v2", window(phases[1])), ("first_checkout_to_v2_1", window(phases[2]))]:
        stats[label] = {"query": LOG_STATS, "start": start, "end": end, "result": logs(LOG_STATS, start, end)}
    write(output / "log-stats.json", stats)
    run_start, run_end = phases[0]["started_unix"] - 10, phases[2]["query_time_unix"] + 30
    with urlopen(METRICS + "/api/v1/query_range?" + urlencode(
            {"query": ALERTS, "start": run_start, "end": run_end, "step": "5s"}), timeout=20) as response:
        history = json.load(response)
    firing = [float(t) for series in history["data"]["result"] if series["metric"].get("alertstate") == "firing"
              for t, _ in series["values"]]
    assert firing, "CheckoutSlow never fired"
    assert phases[1]["started_unix"] - 30 <= min(firing) <= phases[2]["started_unix"] + 60, "alert outside v2"
    write(output / "alerts-history.json", {"query": ALERTS, "start_utc": utc(run_start), "end_utc": utc(run_end), "step": "5s",
                                           "first_firing_utc": utc(min(firing)), "last_firing_utc": utc(max(firing)),
                                           "v2_started_utc": utc(phases[1]["started_unix"]), "result": history})
    processes = json.loads((ROOT / ".runtime/processes.json").read_text()) if (ROOT / ".runtime/processes.json").exists() else []
    footprint = {}
    for item in processes:
        rss = subprocess.run(["ps", "-p", str(item["pid"]), "-o", "rss="], capture_output=True, text=True).stdout.strip()
        if rss:
            footprint[item["name"]] = {"pid": item["pid"], "rss_kib": int(rss)}
    write(output / "footprint.json", {"note": "Resident memory of each lab process after the timed phases, read with ps. "
                                              "One laptop and a tiny workload; not a benchmark.",
                                      "measured_utc": utc(time.time()), "processes": footprint})
    # Post-run business checks, after the timed windows: the HTTP status and the
    # business outcome answer different questions, and both count every response.
    print("Running post-run business checks: 3 out-of-stock and 2 invalid checkouts", flush=True)
    sent = []
    over_demand = json.dumps({"basket": [{**line, "quantity": 4} for line in DEFAULT_BASKET]}).encode()
    for kind, body in [("out_of_stock", over_demand)] * 3 + [("invalid", b'{"basket":[]}'), ("invalid", b"not json")]:
        status, reply = post_body("/checkout", body)
        sent.append({"kind": kind, "body": body.decode(), "http_status": status, "outcome": reply["outcome"],
                     "items": reply["items"], "trace_id": reply["trace_id"]})
        assert reply["outcome"] == kind and status == (200 if kind == "out_of_stock" else 400), (kind, status, reply)
    posted_until = time.time()
    outcomes_after, http_after = checkout_counters()
    deltas = {key: outcomes_after[key] - outcomes_before[key] for key in OUTCOMES}
    http_deltas = {key: http_after.get(key, 0) - http_before.get(key, 0) for key in sorted(set(http_before) | set(http_after))}
    assert deltas == {"accepted": 180, "out_of_stock": 3, "invalid": 2, "error": 0}, deltas
    assert http_deltas == {"200": 183, "400": 2, "500": 0}, http_deltas
    equal = sum(outcomes_after.values()) == sum(http_after.values())
    assert equal, (outcomes_after, http_after)
    query_at = posted_until + 5
    wait = query_at + 35 - time.time()
    print(f"Waiting {max(wait, 0):.0f} seconds before reading the outcome totals from VictoriaMetrics", flush=True)
    if wait > 0:
        time.sleep(wait)
    stored = vector_by(metrics(OUTCOME_TOTALS, query_at), "outcome")
    assert stored == outcomes_after, (stored, outcomes_after)
    write(output / "outcomes.json", {
        "note": "Sent after the three timed phases. checkout_outcomes_total counts each completed POST /checkout "
                "response once, by business outcome; app_http_requests_total counts the same responses by HTTP status.",
        "requests": sent,
        "metrics_endpoint_before": {"checkout_outcomes_total": outcomes_before, "app_http_requests_total_checkout": http_before},
        "metrics_endpoint_after": {"checkout_outcomes_total": outcomes_after, "app_http_requests_total_checkout": http_after},
        "outcome_deltas": deltas, "http_status_deltas": http_deltas,
        "equality": {"sum_outcomes": sum(outcomes_after.values()), "sum_http_checkout": sum(http_after.values()), "equal": equal},
        "victoriametrics": {"query": OUTCOME_TOTALS, "time_unix": query_at, "time_utc": utc(query_at),
                            "result": stored, "matches_metrics_endpoint": stored == outcomes_after}})
    assert sum(phase["requests"] for phase in phases) == 180
    write(output / "duration-observations.json", {
        "note": "Recorded timing comparisons are observations, not integration pass criteria. Scheduling, host load, short query windows, and histogram bucket boundaries affect them.",
        "fault_mean_over_healthy_mean": phases[1]["client_mean_ms"] / phases[0]["client_mean_ms"],
        "fixed_mean_over_fault_mean": phases[2]["client_mean_ms"] / phases[1]["client_mean_ms"],
        "fault_histogram_p95_over_healthy": phases[1]["metric_histogram_p95_seconds"] / phases[0]["metric_histogram_p95_seconds"],
        "fixed_histogram_p95_over_healthy": phases[2]["metric_histogram_p95_seconds"] / phases[0]["metric_histogram_p95_seconds"],
        "histogram_p95_ms_vs_settled_root_span_p95_ms": {
            summary["phase"]: [round(summary["metric_histogram_p95_seconds"] * 1000, 3), summary["settled_root_span_p95_ms"]]
            for summary in phases},
    })
    write(output / "verification.json", {"status": "passed", "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                                         "checks": ["180 identical accepted business results with aggregated quantity6 and stock20",
                                                    "observed inventory attempt counter deltas 1/6/1", "finite metric results",
                                                    "six decision logs plus one completion per selected trace",
                                                    "trace discovery by service/time/duration without prior ID",
                                                    "trace and client-span log correlation", "trace span counts 3/13/3", "exact trace parentage",
                                                    "ten-second metric calls per checkout within 15% of 1/6/1; finite inventory rate and p95",
                                                    "settled trace search returns 60 traces per phase",
                                                    "outcome counter deltas accepted180/out_of_stock3/invalid2/error0",
                                                    "outcome totals equal HTTP /checkout totals; stored totals match /metrics"]})
    windows = save_time_windows(output, phases)
    print("All request, metric, log, and distributed trace checks passed.")
    print(f"Evidence: {output}")
    ui_range = windows["recommended_ui_range"]
    print(f"Use UTC range {ui_range['start_utc']} through {ui_range['end_utc']} in the UI.")


if __name__ == "__main__":
    main()
