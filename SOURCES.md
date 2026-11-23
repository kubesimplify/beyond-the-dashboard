# Sources

Every source cited in *Beyond the Dashboard*, by the ID printed in the page footers. Documentation was checked between 5 October and 22 November 2026.

| ID | Source | What it supports | Checked |
| --- | --- | --- | --- |
| C01 | [OpenTelemetry observability primer](https://opentelemetry.io/docs/concepts/observability-primer/) | Observability, telemetry, instrumentation, and the role of signals | 2026-10-12 |
| C02 | [Prometheus metric types](https://prometheus.io/docs/concepts/metric_types/) | Counter, gauge, and histogram semantics | 2026-10-12 |
| C03 | [Prometheus query functions](https://prometheus.io/docs/prometheus/latest/querying/functions/) | rate() and counter resets | 2026-10-12 |
| C04 | [Prometheus histograms](https://prometheus.io/docs/practices/histograms/) | Cumulative buckets and estimated quantiles | 2026-10-12 |
| C05 | [Prometheus instrumentation practices](https://prometheus.io/docs/practices/instrumentation/) | Each label set is an additional time series with RAM, CPU, disk, and network costs; avoid unbounded label values | 2026-10-19 |
| C06 | [OpenTelemetry logs](https://opentelemetry.io/docs/concepts/signals/logs/) | Logs, structured records, and correlation with traces | 2026-10-12 |
| C07 | [OpenTelemetry log data model](https://opentelemetry.io/docs/specs/otel/logs/data-model/) | Trace context fields in log records | 2026-10-12 |
| C08 | [OpenTelemetry traces](https://opentelemetry.io/docs/concepts/signals/traces/) | Traces, spans, parent relationships, and span kinds | 2026-10-12 |
| C09 | [OpenTelemetry context propagation](https://opentelemetry.io/docs/concepts/context-propagation/) | Propagating trace context between services | 2026-10-12 |
| C10 | [OpenTelemetry sampling](https://opentelemetry.io/docs/concepts/sampling/) | Head and tail sampling decisions | 2026-10-13 |
| C12 | [OpenTelemetry components](https://opentelemetry.io/docs/concepts/components/) | API, SDK, instrumentation libraries, exporters, OTLP, and the Collector | 2026-10-12 |
| C13 | [OpenTelemetry resources](https://opentelemetry.io/docs/concepts/resources/) | Producer identity in resource attributes | 2026-10-12 |
| C14 | [OpenTelemetry profiles](https://opentelemetry.io/docs/concepts/signals/profiles/) | Profiles show where CPU time and memory are spent | 2026-10-13 |
| C16 | [Prometheus data model](https://prometheus.io/docs/concepts/data_model/) | Time series identified by metric name and labels | 2026-10-12 |
| C17 | [OpenTelemetry tracing API](https://opentelemetry.io/docs/specs/otel/trace/api/) | Span identity, parent relationships, span kinds, attributes, and span events | 2026-10-12 |
| C19 | [OpenTelemetry spanmetrics connector](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/connector/spanmetricsconnector/README.md) | Span-derived call counts and duration histograms with configured dimensions | 2026-10-13 |
| C21 | [OpenTelemetry metrics data model](https://opentelemetry.io/docs/specs/otel/metrics/data-model/#exemplars) | An exemplar associates a measurement with trace context | 2026-10-13 |
| C22 | [OpenTelemetry tail sampling processor](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/processor/tailsamplingprocessor/README.md) | Tail decisions after decision_wait; probabilistic policies inside tail sampling; all spans of a trace must reach the same instance | 2026-10-13 |
| C23 | [OpenTelemetry zero-code instrumentation](https://opentelemetry.io/docs/concepts/instrumentation/zero-code/) | Instrumentation libraries record requests, responses, and database calls at network boundaries | 2026-10-13 |
| C24 | [Grafana Labs: the RED method](https://grafana.com/blog/2018/08/02/the-red-method-how-to-instrument-your-services/) | Rate, errors, and duration for request-driven services | 2026-10-13 |
| C26 | [W3C Trace Context](https://www.w3.org/TR/trace-context/) | traceparent version, trace ID, parent ID, and flags; the parent ID is the caller's span | 2026-10-13 |
| C27 | [VictoriaMetrics: exemplar support decision](https://github.com/VictoriaMetrics/VictoriaMetrics/issues/1169) | VictoriaMetrics decided not to add Prometheus exemplar support | 2026-10-13 |
| C28 | [Grafana Tempo: tail sampling with the Collector](https://grafana.com/docs/tempo/latest/set-up-for-tracing/instrument-send/set-up-collector/tail-sampling/) | Derive span metrics before any tail sampling | 2026-10-13 |
| C29 | [Google SRE book: monitoring distributed systems](https://sre.google/sre-book/monitoring-distributed-systems/) | Monitoring is collecting, processing, aggregating, and displaying real-time quantitative data about a system | 2026-10-19 |
| C30 | [OpenTelemetry: deprecating the Span Events API](https://opentelemetry.io/blog/2026/deprecating-span-events/) | New code should write events as logs correlated with the current span; existing span events keep working | 2026-10-19 |
| C31 | [Prometheus metric and label naming](https://prometheus.io/docs/practices/naming/) | Do not use labels for high-cardinality dimensions such as user IDs or other unbounded sets of values | 2026-11-04 |
| C32 | [Prometheus jobs and instances](https://prometheus.io/docs/concepts/jobs_instances/) | An instance is a scrapable endpoint, usually one process; up is 1 when the scrape succeeded and 0 when it failed | 2026-11-04 |
| C33 | [OpenTelemetry tracing SDK: sampling](https://opentelemetry.io/docs/specs/otel/trace/sdk/#sampling) | The SDK asks its sampler when a span is created; a DROP decision means the span is never recorded or exported | 2026-11-04 |
| P01 | [VictoriaMetrics single-node documentation](https://docs.victoriametrics.com/victoriametrics/single-server-victoriametrics/) | A single small executable without external dependencies; one process ingests, stores, and queries; built-in VMUI | 2026-10-16 |
| P02 | [VictoriaMetrics key concepts](https://docs.victoriametrics.com/victoriametrics/keyconcepts/) | Samples, series, labels, and query evaluation | 2026-10-12 |
| P03 | [Companion lab: source, run instructions, and checks](https://github.com/kubesimplify/beyond-the-dashboard/blob/main/lab/README.md) | How to run the lab, what each process does, and what was tested | 2026-10-16 |
| P04 | [vmagent documentation](https://docs.victoriametrics.com/victoriametrics/vmagent/) | Scraping, remote write, the VictoriaMetrics remote-write protocol used by default, and on-disk buffering | 2026-10-13 |
| P05 | [MetricsQL documentation](https://docs.victoriametrics.com/victoriametrics/metricsql/) | MetricsQL is backward-compatible with PromQL, with some intentional differences | 2026-10-16 |
| P06 | [Prometheus histogram_quantile function](https://prometheus.io/docs/prometheus/latest/querying/functions/#histogram_quantile) | Percentile estimates from cumulative buckets assume an even spread within a bucket | 2026-10-13 |
| P07 | [vmalert documentation](https://docs.victoriametrics.com/victoriametrics/vmalert/) | Rules run against the datasource on an interval; pending and firing with for; ALERTS series through remote write; -rule.evalDelay of 30s matching hidden recent samples; -notifier.blackhole; notifications through Alertmanager | 2026-10-16 |
| P08 | [VictoriaMetrics cluster version](https://docs.victoriametrics.com/victoriametrics/cluster-victoriametrics/) | vminsert, vmstorage, vmselect; single-node recommended below about a million data points per second | 2026-10-13 |
| P09 | [vmauth documentation](https://docs.victoriametrics.com/victoriametrics/vmauth/) | Authorization and routing proxy for reads and writes | 2026-10-12 |
| P10 | [vmbackup documentation](https://docs.victoriametrics.com/victoriametrics/vmbackup/) | Backups keep their own copies and lifetimes | 2026-10-12 |
| P11 | [VictoriaMetrics capacity planning](https://docs.victoriametrics.com/victoriametrics/single-server-victoriametrics/#capacity-planning) | Measure active series, ingestion rate, retention, and query load before sizing | 2026-10-12 |
| P12 | [VictoriaLogs documentation](https://docs.victoriametrics.com/victorialogs/) | Log storage with structured fields and LogsQL | 2026-10-13 |
| P13 | [VictoriaLogs data ingestion](https://docs.victoriametrics.com/victorialogs/data-ingestion/) | JSON line ingestion with _time_field, _msg_field, and _stream_fields | 2026-10-13 |
| P14 | [VictoriaLogs key concepts](https://docs.victoriametrics.com/victorialogs/keyconcepts/) | Log streams; trace_id must never define a stream; all fields are indexed | 2026-10-13 |
| P15 | [VictoriaLogs OpenTelemetry setup](https://docs.victoriametrics.com/victorialogs/data-ingestion/opentelemetry/) | VictoriaLogs accepts logs from OpenTelemetry SDKs and from the OpenTelemetry Collector | 2026-11-19 |
| P16 | [LogsQL reference](https://docs.victoriametrics.com/victorialogs/logsql/) | Word and exact filters, filters joined by AND, and the sort, fields, and stats pipes with count and count_uniq | 2026-10-16 |
| P18 | [VictoriaTraces documentation](https://docs.victoriametrics.com/victoriatraces/) | Trace storage built on top of VictoriaLogs; OTLP ingestion | 2026-10-13 |
| P19 | [VictoriaTraces changelog](https://docs.victoriametrics.com/victoriatraces/changelog/) | v0.12.0 adds the built-in trace explorer | 2026-10-13 |
| P20 | [VictoriaTraces repository README](https://github.com/VictoriaMetrics/VictoriaTraces) | A work in progress until the first release: on-disk data structures and API endpoints may change and may not be backward compatible | 2026-11-14 |
| P21 | [VictoriaTraces querying](https://docs.victoriametrics.com/victoriatraces/querying/) | Jaeger-compatible search API with microsecond start and end times | 2026-10-13 |
| P22 | [VictoriaTraces OpenTelemetry ingestion](https://docs.victoriametrics.com/victoriatraces/data-ingestion/opentelemetry/) | OTLP/HTTP span ingestion path | 2026-10-13 |
| P23 | [OpenTelemetry HTTP metrics conventions](https://opentelemetry.io/docs/specs/semconv/http/http-metrics/) | HTTP server duration should match the server span duration | 2026-10-13 |
| P24 | [Recorded run: the version 2 trace's logs](https://github.com/kubesimplify/beyond-the-dashboard/blob/main/lab/evidence/book-lab-6-20261016/fault-logs.json) | The selected version 2 trace's decision logs, as VictoriaLogs returned them | 2026-10-16 |
| P25 | [Recorded run: results per version](https://github.com/kubesimplify/beyond-the-dashboard/blob/main/lab/evidence/book-lab-6-20261016/summary.json) | Client timings, metric results, trace and log checks for each version | 2026-10-16 |
| P26 | [Recorded run: business outcome checks](https://github.com/kubesimplify/beyond-the-dashboard/blob/main/lab/evidence/book-lab-6-20261016/outcomes.json) | Outcome counter values after the extra out-of-stock and invalid requests | 2026-10-16 |
| P27 | [Recorded run: first metric queries](https://github.com/kubesimplify/beyond-the-dashboard/blob/main/lab/evidence/book-lab-6-20261016/basics-metrics.json) | The selector after version 1 and the rate queries during it | 2026-10-16 |
| P28 | [VictoriaLogs querying](https://docs.victoriametrics.com/victorialogs/querying/) | The /select/logsql/query endpoint takes a query argument and returns a stream of JSON lines | 2026-10-16 |
| P29 | [Recorded run: decision-log statistics](https://github.com/kubesimplify/beyond-the-dashboard/blob/main/lab/evidence/book-lab-6-20261016/log-stats.json) | Distinct checkouts per lookup scope, from the first checkout to the end of version 2 | 2026-10-16 |
| P30 | [Recorded run: alert history](https://github.com/kubesimplify/beyond-the-dashboard/blob/main/lab/evidence/book-lab-6-20261016/alerts-history.json) | When CheckoutSlow fired during version 2, from the ALERTS series | 2026-10-16 |
| P31 | [VictoriaMetrics FAQ](https://docs.victoriametrics.com/victoriametrics/faq/) | A series is active if it received at least one sample during the last hour | 2026-10-19 |
| P32 | [VictoriaStack documentation](https://docs.victoriametrics.com/victoriastack/) | VictoriaMetrics, VictoriaLogs, and VictoriaTraces as one stack of separate databases, with vmauth as a single entry point that routes requests; each database is battle-tested in production; Grafana for dashboards; a Docker Compose demo (make otel-single-up), which its quick start page calls a demonstration, not for production use; Helm charts for Kubernetes | 2026-11-19 |
| P33 | [VictoriaMetrics blog: introducing VictoriaStack](https://victoriametrics.com/blog/introducing-victoriastack-the-right-database-for-every-signal/) | VictoriaStack was introduced on 10 November 2026 | 2026-11-14 |
| P34 | [Recorded runs: the bookshop on VictoriaStack](https://github.com/kubesimplify/beyond-the-dashboard/blob/main/lab/evidence/victoriastack-bookshop-20261119/README.md) | The book's checkout and inventory run against the VictoriaStack demo on 19 November 2026 and against the Helm chart on a kind cluster on 22 November 2026: versions, and the Part 3 queries through vmauth | 2026-11-22 |
| P35 | [victoria-metrics-k8s-stack Helm chart](https://docs.victoriametrics.com/helm/victoria-metrics-k8s-stack/) | The chart installs dependency charts such as grafana, node-exporter, kube-state-metrics, and victoria-metrics-operator, and custom resources for metrics, optionally for logs and traces | 2026-11-19 |
| P36 | [kind: Kubernetes in Docker](https://kind.sigs.k8s.io/) | kind runs local Kubernetes clusters using Docker container nodes, and supports Linux, macOS, and Windows | 2026-11-20 |
| P37 | [Recorded run: a second slow checkout](https://github.com/kubesimplify/beyond-the-dashboard/blob/main/lab/evidence/slow-inventory-20261119/README.md) | Version 1 of checkout with inventory's delay raised from 40 to 300 ms, on 19 November 2026: metrics, one trace, and its decision logs | 2026-11-19 |
| R01 | [Google SRE: implementing SLOs](https://sre.google/workbook/implementing-slos/) | SLIs, objectives, and event-based error budgets | 2026-10-05 |
| R02 | [OpenTelemetry log severity](https://opentelemetry.io/docs/specs/otel/logs/data-model/#severity-fields) | Severity fields and the meanings of DEBUG, INFO, WARN, and ERROR | 2026-10-13 |
| R03 | [NIST SP 800-92: log management](https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication800-92.pdf) | Retention policies reflect operational and applicable requirements, with different lifetimes for different records | 2026-10-13 |
| R04 | [Prometheus Operator runbooks: Watchdog](https://runbooks.prometheus-operator.dev/runbooks/general/watchdog/) | An always-firing alert, watched by an outside service, shows that the alerting pipeline works | 2026-10-13 |
| R05 | [Prometheus Alertmanager](https://prometheus.io/docs/alerting/latest/alertmanager/) | Alertmanager deduplicates, groups, and routes alerts to receivers, with silences and inhibition | 2026-10-16 |
| R06 | [Google SRE: alerting on SLOs](https://sre.google/workbook/alerting-on-slos/) | Alert on how fast the error budget is being used (the burn rate), not on a single threshold crossing | 2026-11-04 |
