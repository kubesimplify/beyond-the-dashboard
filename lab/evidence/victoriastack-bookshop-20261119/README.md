# The bookshop on VictoriaStack, as run for pages 44 and 45

Pages 44 and 45 of *Beyond the Dashboard* run the book's own checkout and inventory apps against VictoriaStack: first its Docker Compose demo, then the `victoria-metrics-k8s-stack` Helm chart on a kind cluster. The Compose run was made on 19 November 2026 and the Kubernetes run on 22 November 2026, both on macOS 27.0.1 (ARM64). The apps were not changed. `lab/stack.py` starts them with their log and trace addresses on vmauth, and starts the lab's vmagent with its remote write address on vmauth.

| File | What it holds |
| --- | --- |
| `summary.json` | The facts the pages print: versions, the entry points, and for each version of checkout the p95 estimate, inventory's request rate, calls per checkout, and the trace search counts. The Kubernetes run is under `kubernetes` |
| `start.txt`, `containers.txt` | The clone at commit 5c1df0b, `make otel-single-up`, and the 12 containers |
| `stack-start.txt` | What `stack.py start` printed |
| `kubernetes.txt` | The Kubernetes run on kind v0.32.0: the commands of page 45 and what each one printed, the pods, the ClusterIP Service of vmauth, the port-forward, `stack.py start`, the same traffic and queries, the image versions, and the cleanup |

Notes from the runs:

- The demo publishes ports 8428, 9428, and 10428 as well as 8427, so the lab must be stopped first. `stack.py start` refuses to run while the lab is running.
- Each run waited 75 seconds after the last traffic before it queried. The demo does not shorten VictoriaTraces' index flush as the lab does.
- The demo's own services keep running, so the trace service list has `flagd`, `quote`, and `shipping` next to `checkout` and `inventory`.
- On Kubernetes, vmauth's Service is of type ClusterIP. The run reached it with `kubectl port-forward`, and `stack.py start` then printed the same three lines as with Compose.
- Timings differ a little from run to run: version 2's p95 estimate reads 0.386 seconds with Compose and 0.389 seconds on Kubernetes. The counts are the same: 12 inventory requests per second, 6 calls per checkout, and 60 slow traces.
