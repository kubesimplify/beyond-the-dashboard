# The checkout lab

A small online bookshop's checkout, and the telemetry stack to watch it: VictoriaMetrics for metrics, VictoriaLogs for logs, VictoriaTraces for traces, vmagent to collect metrics, and vmalert to run alert rules. *Beyond the Dashboard* uses it in two ways. First you learn each signal on steady traffic. Then a new release of checkout makes it slower, and you investigate why.

Checkout receives a basket and asks a second service, inventory, how much stock is available. The basket has six one-unit lines of the same book. This is a read-only stock check: it does not reserve inventory, charge a card, or create an order. Inventory waits 40 milliseconds per call to stand in for real work. Measurements from this workload explain the example; they are not product benchmarks.

## What runs

| Program | Address | Job |
| --- | --- | --- |
| VictoriaMetrics 1.153.0 | `127.0.0.1:8428` | Stores metrics; its interface, VMUI, is at `/vmui/` |
| vmagent 1.153.0 | `127.0.0.1:8429` | Scrapes both apps and the telemetry programs every two seconds |
| vmalert 1.153.0 | `127.0.0.1:8880` | Runs `config/alerts.yml` against VictoriaMetrics; alerts at `/vmalert/alerts` |
| VictoriaLogs 1.53.0 | `127.0.0.1:9428` | Stores JSON log records; its interface is at `/select/vmui/` |
| VictoriaTraces 0.12.0 | `127.0.0.1:10428` | Stores OpenTelemetry spans; its interface is at `/select/vmui/` |
| Inventory | `127.0.0.1:8081` | Handles `GET /inventory/check` |
| Checkout | `127.0.0.1:8080` | Handles `POST /checkout` and calls inventory |

Every program listens on its product's default port, bound to localhost. The apps expose counters and a histogram at `/metrics`; vmagent scrapes them and sends the samples to VictoriaMetrics with remote write. A background queue in each app sends JSON log records to VictoriaLogs. The OpenTelemetry Python SDK sends spans to VictoriaTraces over OTLP/HTTP and carries W3C trace context on each call to inventory. vmalert writes each alert's state back to VictoriaMetrics as the `ALERTS` series, and runs with `-notifier.blackhole` because the lab has no Alertmanager.

## Start it

You need git, Python 3.12, and internet access for the first downloads. The installer supports macOS or Linux on ARM64 or AMD64. The recorded run used macOS ARM64; a full scenario run also passed on Linux (Ubuntu 24.04 on x86_64, Python 3.12.3) on 4 November 2026. On Debian and Ubuntu, Python's venv module is a separate package: install `python3.12-venv` first, or setup stops at the virtual environment with an ensurepip error.

```sh
git clone https://github.com/kubesimplify/beyond-the-dashboard
cd beyond-the-dashboard/lab
python3.12 setup.py
.venv/bin/python control.py start
```

`setup.py` downloads the pinned official release archives, checks the binaries against the release checksum files, unpacks them into `.cache/bin`, and installs pinned Python dependencies in `.venv`. Download receipts go in `.cache/downloads.json`. Nothing is installed globally.

`control.py start` checks that the seven ports are free, starts each program in the background, waits for its `/health` endpoint, and prints the page to open for it. Output goes to `.runtime/<program>.log` and data to `.runtime/`. There is nothing hidden in it. These are the lines it runs, which you can also type yourself, one terminal each:

```sh
.venv/bin/python control.py commands
```

```text
.cache/bin/victoria-metrics-prod -httpListenAddr=127.0.0.1:8428 -storageDataPath=.runtime/metrics -retentionPeriod=7d
.cache/bin/victoria-logs-prod -httpListenAddr=127.0.0.1:9428 -storageDataPath=.runtime/logs -retentionPeriod=7d
TZ=UTC .cache/bin/victoria-traces-prod -httpListenAddr=127.0.0.1:10428 -storageDataPath=.runtime/traces -retentionPeriod=7d -insert.indexFlushInterval=1s
.cache/bin/vmagent-prod -httpListenAddr=127.0.0.1:8429 -promscrape.config=config/scrape.yml -remoteWrite.url=http://127.0.0.1:8428/api/v1/write -remoteWrite.tmpDataPath=.runtime/vmagent
.cache/bin/vmalert-prod -httpListenAddr=127.0.0.1:8880 -rule=config/alerts.yml -datasource.url=http://127.0.0.1:8428 -remoteWrite.url=http://127.0.0.1:8428 -notifier.blackhole
SERVICE=inventory PORT=8081 .venv/bin/python app.py
SERVICE=checkout PORT=8080 .venv/bin/python app.py
```

`-insert.indexFlushInterval=1s` lets a new trace open by its ID after a few seconds instead of about 20; trace search still hides the newest 30 seconds (`-search.latencyOffset`). VictoriaTraces runs with `TZ=UTC` so absolute search windows do not depend on the machine's timezone. If a port is taken, `control.py start` stops before starting anything and names the port.

To stop everything, keeping the stored data:

```sh
.venv/bin/python control.py stop
```

## Follow the book

Send one checkout. With no body, it uses the six-line basket, and the reply carries the business outcome and the trace ID:

```sh
curl -s -X POST http://127.0.0.1:8080/checkout
```

`traffic.py` plays checkout's customers. Each step switches checkout to a version and sends 60 checkouts on a half-second schedule, then prints when the traffic ran:

```sh
.venv/bin/python traffic.py v1      # the version running today
.venv/bin/python traffic.py v2      # a new release
.venv/bin/python traffic.py v2.1    # the patch
```

All three versions live in `app.py`; switching is instant and nothing is redeployed. The book runs `v1` in Part 2, to learn the queries on steady traffic, then `v2` and `v2.1` in Part 3. Each version must return the same accepted business result: six units required and 20 available.

Wait about 30 seconds after traffic before querying. VictoriaMetrics and VictoriaTraces hide the newest 30 seconds of data by default (`-search.latencyOffset`), so an immediate query can miss recent samples, and vmalert evaluates 30 seconds in the past for the same reason. In each interface, set the time range at the top right to cover your traffic. Data is kept for seven days.

### Query from the command line

`query.py` calls the same HTTP APIs as the interfaces, using Python's standard library:

```sh
.venv/bin/python query.py metrics 'sum(rate(app_http_requests_total{service="checkout"}[1m]))'
.venv/bin/python query.py logs 'service:=checkout event:=checkout_completed | stats by (outcome) count()'
.venv/bin/python query.py search checkout --last 15m --min-duration 200ms
.venv/bin/python query.py trace TRACE_ID
```

Trace search uses the Jaeger-compatible query API that VictoriaTraces serves; there is no Jaeger in the lab. `--last` sets a window ending now. Pass `--start` and `--end` with explicit timezone offsets instead to search a past window, and keep it inside the retention period: VictoriaTraces rejects a window that lies outside it with `request time out of retention`. On an HTTP error, `query.py` prints the message the database returned.

### Queries the book uses

| Question | Query |
| --- | --- |
| Checkout requests per second | `sum(rate(app_http_requests_total{service="checkout"}[10s]))` |
| Share that failed with a server error | `sum(rate(app_http_requests_total{service="checkout",status=~"5.."}[10s])) / sum(rate(app_http_requests_total{service="checkout"}[10s]))` |
| Answers by business outcome | `sum by (outcome) (rate(checkout_outcomes_total[10s]))` |
| Estimated checkout p95 | `histogram_quantile(0.95, sum by (le) (rate(app_http_request_duration_seconds_bucket{service="checkout"}[10s])))` |
| Inventory calls per checkout | `sum(rate(checkout_inventory_calls_total[10s])) / sum(rate(app_http_requests_total{service="checkout",route="/checkout"}[10s]))` |
| Share answered within 200 ms | `sum(rate(app_http_request_duration_seconds_bucket{service="checkout",le="0.2"}[10s])) / sum(rate(app_http_request_duration_seconds_count{service="checkout"}[10s]))` |
| Every log record of one checkout | `trace_id:=TRACE_ID \| sort by (_time)` |
| Lookup logs of one checkout | `service:=checkout event:=inventory_lookup_decision trace_id:=TRACE_ID \| sort by (_time)` |
| Checkouts per lookup scope | `service:=checkout event:=inventory_lookup_decision \| stats by (lookup_scope) count_uniq(trace_id) as checkouts` |

The ten-second windows keep the 30-second versions apart. On a real service, use windows such as five minutes.

To see an `out_of_stock` answer, send a basket that needs more than the 20 units in stock. The reply is still HTTP 200:

```sh
curl -s -X POST http://127.0.0.1:8080/checkout -d '{"basket":[
  {"line_id":"line-1","sku":"BOOK-001","warehouse":"east",
   "variant":"paperback","quantity":21}]}'
```

### Alerts

`config/alerts.yml` has two rules. `CheckoutSlow` fires when the estimated checkout p95 has been above 0.2 seconds for 10 seconds; `TargetDown` fires when a scrape target has been down for 30 seconds. The windows suit 30-second traffic steps; the file says what to use on a real service. Check the rules without running vmalert:

```sh
.cache/bin/vmalert-prod -rule=config/alerts.yml -dryRun
```

## What the app measures

The HTTP wrapper in `http_telemetry.py` measures two routes: `POST /checkout` and `GET /inventory/check`. Its timer starts after request headers are parsed, before the route handler runs, and ends after the response is written and flushed, or the write fails. The HTTP server span and the duration histogram use that same interval. Health checks, the version switch, unknown routes, and metrics scrapes are not measured.

| Counter | Labels | What one increment means |
| --- | --- | --- |
| `app_http_requests_total` | `service`, `route`, `status` | One instrumented HTTP response, by status code |
| `checkout_outcomes_total` | `outcome` | One completed `POST /checkout` response, by business outcome |
| `checkout_inventory_calls_total` | none | One HTTP call from checkout to inventory |

The outcome is `accepted` or `out_of_stock` for a valid basket (both HTTP 200), `invalid` for a rejected request body (HTTP 400), and `error` when the stock check fails (HTTP 5xx). Each completed checkout counts once in each of the first two counters, so their totals for `/checkout` are equal. The `checkout_completed` log records the same outcome before the response is sent, and `checkout.outcome` records it on the span.

Logs carry `trace_id` and `span_id`, copied from the active span. `service` is the only log stream field; IDs, line IDs, and SKUs are ordinary fields, and none of them is a metric label. Severity is `INFO` for lookups and normal outcomes, `WARN` for invalid input, and `ERROR` for failed checkouts.

The log sender is deliberately small. It sends one HTTP request per record from an in-memory queue of 10,000 records, prints an export error, and drops the record if delivery fails. Production collection needs a chosen shipper, capacity limits, retries, and durability. There is no OpenTelemetry Collector in the lab, and every trace is kept so the checks are repeatable.

## Record a run

`scenario.py` records a full run with the same steps a reader takes: one checkout, then `v1`, `v2`, and `v2.1` through `traffic.py`'s functions, 15 seconds apart. It checks every signal and saves each API response it relies on:

```sh
.venv/bin/python scenario.py --output evidence/my-run
```

It takes about five minutes and refuses to overwrite an evidence directory. The checks cover:

- 180 identical accepted business results, with inventory calls per request of one, six, and one.
- Finite metrics, with calls per checkout of 1, 6, and 1 from the metrics alone.
- Trace discovery by service, operation, time, and minimum duration, with 60 traces per version once the data has settled.
- Trace parentage: 3, 13, and 3 spans, each inventory server span a child of its client span.
- Six lookup logs and one completion per selected checkout, joined to the trace by trace and span IDs.
- `CheckoutSlow` firing during `v2`, from vmalert and from the `ALERTS` series.
- Extra out-of-stock and invalid checkouts afterward, with outcome counter deltas of 180, 3, 2, and 0, and outcome totals equal to the HTTP totals.

`summary.json` has the per-version results; `duration-observations.json` keeps timing comparisons as observations, not pass criteria.

The business and HTTP checks run without the databases:

```sh
.venv/bin/python -m unittest -v test_basket test_http_telemetry
.venv/bin/python test_http.py --output evidence/my-http-checks.json
```

## Docker Compose

`compose.yml` starts the same seven programs on the same ports, in containers. A full `scenario.py` run against it passed with `book-lab-6` on 19 November 2026. Stop the native programs first:

```sh
docker compose up --build -d
docker compose down
```

`traffic.py`, `query.py`, and the interfaces work as before, because the ports are the same. `docker compose down` keeps the stored data in Docker volumes; `docker compose down -v` removes it as well. To record a run of your own against the containers, add `--execution compose` to the `scenario.py` line above.

## Run the bookshop on VictoriaStack

Part 5 of the book (pages 46 to 48) sends the same apps' telemetry to VictoriaStack, first to its Docker Compose demo. Stop the lab first, because the demo listens on ports 8428, 9428, and 10428. The demo is not meant for production, as its documentation says: other machines on your network can reach its ports, and port 8427 does not ask for a login. So run it only on your own machine, on a network you trust. From the lab directory, stop the lab and get the files next to the companion repository, at the commit we ran:

```sh
.venv/bin/python control.py stop
cd ../..
git clone https://github.com/VictoriaMetrics/VictoriaStack.git
cd VictoriaStack && git checkout 5c1df0b
make otel-single-up
```

Then go back to the lab directory (`cd ../beyond-the-dashboard/lab`):

```sh
.venv/bin/python stack.py start      # inventory, checkout, and vmagent, all sending to port 8427
.venv/bin/python stack.py commands   # the three lines it runs
.venv/bin/python stack.py stop
```

`stack.py` changes three addresses and nothing in the apps: `LOG_URL` and `TRACE_URL` point at vmauth's `/logs` and `/traces`, and vmagent's remote write at `/metrics/insert/api/v1/write`. `traffic.py` works as before. The interfaces are under one port: `http://127.0.0.1:8427/metrics/select/vmui/`, `/logs/select/vmui/`, and `/traces/select/vmui/`. Our runs asked every question through that port, and waited 75 seconds after the last traffic before they did. `query.py` still asks ports 8428, 9428, and 10428 directly, so our runs did not use it against the stack. The Compose demo publishes those three ports as well; a Kubernetes cluster does not. `make -C ../../VictoriaStack otel-single-down`, from the lab directory, removes the stack and its data.

### On Kubernetes

`config/stack-values.yaml` is the values file for the `victoria-metrics-k8s-stack` Helm chart: it turns on logs and traces, and gives vmauth the same three paths. Its comments say why vmauth removes two parts of the path for metrics and one for logs and traces. Page 48 uses [kind](https://kind.sigs.k8s.io/), which runs on Linux, macOS, and Windows. Any other cluster works the same way:

```sh
kind create cluster --name btd-bookshop
helm repo add vm https://victoriametrics.github.io/helm-charts/
helm repo update
helm install stack vm/victoria-metrics-k8s-stack --version 0.98.1 \
  --namespace monitoring --create-namespace -f config/stack-values.yaml
kubectl get pods -n monitoring               # wait until the pods are running
```

vmauth's Service is of type ClusterIP, so only pods inside the cluster can reach it. As in the Compose demo, the values file gives vmauth no users, so it does not ask for a login. That is a demo shortcut for a cluster on your own machine. In a real setup, vmauth has users, and their credentials decide what each one can reach ([access control](https://docs.victoriametrics.com/victoriastack/access-control/)). Forward its port in a second terminal and leave it running. The Compose demo must be stopped by now, because it uses the same port:

```sh
kubectl port-forward -n monitoring svc/vmauth-stack 8427:8427
```

vmauth now answers on `http://127.0.0.1:8427`, the same address as with Compose, so the next steps are the same as above:

```sh
.venv/bin/python stack.py start
```

`helm repo update` makes sure helm knows chart 0.98.1, also when the `vm` repository was added some time ago. If your cluster gives vmauth an address of its own, set `STACK_URL` to it before `stack.py start`, for example, `STACK_URL=http://192.0.2.10:8427`.

When you are done, run `.venv/bin/python stack.py stop`, press Ctrl+C in the terminal of the port-forward, and run `kind delete cluster --name btd-bookshop`. Our run, made on 22 November 2026, is in `evidence/victoriastack-bookshop-20261119/` next to the Compose run of 19 November.

## Change the lab

The book's exercises change the code, so make them in a copy of the whole lab directory. `control.py` always starts the `app.py` next to it. Stop the original lab first, because the copy uses the same ports. The copy also carries the original's stored telemetry in `.runtime`: delete that directory in the copy, so its queries show only the new run. Pages 49 and 50 walk through one such change, a slower inventory, with these lines, run from the lab directory:

```sh
.venv/bin/python control.py stop
cd .. && cp -R lab lab-slow && cd lab-slow
rm -rf .runtime
sed -i.bak 's/time.sleep(.04)/time.sleep(.3)/' app.py
.venv/bin/python control.py start
.venv/bin/python traffic.py v1
```

Our run of it is in `evidence/slow-inventory-20261119/`. To undo the change, run `sed -i.bak 's/time.sleep(.3)/time.sleep(.04)/' app.py` in the copy.

## The files

| File | What it does |
| --- | --- |
| `app.py` | Both HTTP services, with their spans, logs, and metrics |
| `basket.py` | The quantity checks and the stock lookups. Read it after Part 3 if you want to solve the incident yourself |
| `http_telemetry.py` | The shared HTTP timing and counters |
| `setup.py`, `control.py` | Download the pinned programs, then start and stop all seven |
| `traffic.py`, `query.py` | Send steady traffic to one version of checkout, and query the three databases from the command line |
| `scenario.py` | Records a full run with every check |
| `stack.py` | Starts the two apps and vmagent against VictoriaStack (Part 5, pages 46 to 48) |
| `config/` | The scrape targets, the alert rules, and the Helm values for page 48 |
| `compose.yml`, `Dockerfile` | The same seven programs in containers |
| `test_*.py` | The unit tests and the HTTP checks |

## What was tested

The app version is `book-lab-6`. The first three runs below are full `scenario.py` runs, and each one passed all 12 of its checks.

| Run | Date | Result |
| --- | --- | --- |
| The run behind the book's numbers, on macOS 27.0.1 (ARM64) with Python 3.12.4 | 16 October 2026 | `evidence/book-lab-6-20261016/` |
| The same run on Linux (Ubuntu 24.04 on x86_64, Python 3.12.3) | 4 November 2026 | Passed |
| The same run against `compose.yml` | 19 November 2026 | Passed |
| Part 5, pages 46 to 48: the same apps on the VictoriaStack demo, and on a kind cluster | 19 and 22 November 2026 | `evidence/victoriastack-bookshop-20261119/` |
| Part 6, pages 49 and 50: a slower inventory | 19 November 2026 | `evidence/slow-inventory-20261119/` |

The evidence folders hold the results that the book cites. Your own runs go next to them, and git ignores them. A recorded file is what our run printed, with one detail replaced: `<machine-name>` stands for the network name of the computer.

VictoriaTraces has not reached version 1.0 yet, but the VictoriaMetrics team considers it production ready. The lab pins the versions in the table at the top, and `versions.json` holds them.

Every source the book cites is in [SOURCES.md](../SOURCES.md).

## Spoiler: what version 2 changes

Read this after Part 3 of the book, or if you want the answer first.

Version 2 moves the stock lookup inside the basket line loop, so checkout fetches the same stock key once per line: six sequential calls to inventory instead of one. This is similar to the N+1 pattern. Versions 1 and 2.1 fetch once per stock key and reuse the answer within the request. All versions add up the quantities across lines before checking stock, so they return the same business result. In `app.py` the versions are the internal phases `healthy`, `fault`, and `fixed`, selected through `POST /admin/phase`, an unauthenticated local teaching control.
