# The recorded run behind Parts 2 and 3

Every number, ID, and output block in Parts 2 and 3 of *Beyond the Dashboard* comes from one run of this lab, made on 16 October 2026 on macOS 27.0.1 (ARM64) with Python 3.12.4. `lab/scenario.py` recorded it: one checkout, then 60 checkouts each for versions 1, 2, and 2.1, with every signal checked along the way. These are the result files that the book cites.

| File | What it holds |
| --- | --- |
| `summary.json` | The results for each version of checkout: client timings, metric results, and the trace and log checks |
| `verification.json` | The 12 checks of the run, all passed |
| `environment.json` | The machine, the Python version, and the versions of the three databases |
| `basics-metrics.json` | The first metric queries of Part 2 |
| `fault-logs.json` | The decision logs of the version 2 trace, as VictoriaLogs returned them |
| `log-stats.json` | The number of checkouts for each lookup scope |
| `alerts-history.json` | When CheckoutSlow fired during version 2 |
| `outcomes.json` | The outcome counters after the extra out-of-stock and invalid requests |

To make a run of your own, see "Record a run" in [lab/README.md](../../README.md).
