# A second slow checkout, as run for Part 6

Pages 49 and 50 of *Beyond the Dashboard* ask the reader to make inventory itself slower and to tell that apart from version 2's repeated calls. This is our run of that exercise, made on 19 November 2026 in a copy of the lab with one line changed (`change.diff`): inventory's `time.sleep(.04)` became `time.sleep(.3)`. Checkout ran version 1.

| File | What it holds |
| --- | --- |
| `summary.json` | The facts the pages print: checkout's and inventory's p95 estimates, inventory's request rate, calls per checkout, the spans of one slow trace, its lookup logs, and the `CheckoutSlow` alert |
| `change.diff` | The one changed line of `app.py` |
