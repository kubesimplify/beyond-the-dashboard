"""Play the part of checkout's customers.

Switch checkout to one of its versions, then send it steady traffic:

    .venv/bin/python traffic.py v1      # the version running today
    .venv/bin/python traffic.py v2      # a new release
    .venv/bin/python traffic.py v2.1    # a patch for that release

Each run sends 60 checkouts with the same basket, one every half second, and
prints when the traffic started and finished, in UTC. All versions live in
app.py, so switching is instant; nothing is redeployed.
"""
import argparse
from datetime import datetime, timezone
import json
import time
from urllib.request import Request, urlopen

CHECKOUT = "http://127.0.0.1:8080"
# The lab's names for the three code paths behind each version.
VERSIONS = {"v1": "healthy", "v2": "fault", "v2.1": "fixed"}


def post(path, timeout=15):
    with urlopen(Request(CHECKOUT + path, data=b""), timeout=timeout) as response:
        return json.load(response)


def switch(version):
    """Make checkout answer as this version from its next request."""
    return post("/admin/phase?name=" + VERSIONS[version])


def send(count=60, interval=.5, after_each=None):
    """Send count checkouts on a fixed schedule and return one row per reply."""
    rows = []
    monotonic_start = time.monotonic()
    for index in range(count):
        scheduled = monotonic_start + index * interval
        if time.monotonic() < scheduled:
            time.sleep(scheduled - time.monotonic())
        client_start = time.perf_counter()
        reply = post("/checkout")
        row = {"index": index, "received_at_unix": time.time(),
               "client_duration_ms": round((time.perf_counter() - client_start) * 1000, 3), **reply}
        if after_each:
            row.update(after_each())
        rows.append(row)
    return rows


def clock(unix):
    return datetime.fromtimestamp(unix, timezone.utc).strftime("%H:%M:%S")


def opening(version, count):
    return f"Checkout now runs {version}. Sending {count} checkouts, two per second."


def closing(rows, started):
    accepted = sum(row["outcome"] == "accepted" for row in rows)
    failed = sum(row["status"] != "ok" for row in rows)
    day = datetime.fromtimestamp(started, timezone.utc).strftime("%d %b %Y")
    return [f"Done: {len(rows)} checkouts, {accepted} accepted, {failed} failed.",
            f"Traffic ran from {clock(started)} to {clock(rows[-1]['received_at_unix'])} UTC on {day}."]


def main():
    parser = argparse.ArgumentParser(description="Switch checkout's version and send it steady traffic.")
    parser.add_argument("version", choices=list(VERSIONS))
    parser.add_argument("--requests", type=int, default=60)
    args = parser.parse_args()
    switch(args.version)
    print(opening(args.version, args.requests), flush=True)
    started = time.time()
    rows = send(args.requests)
    print("\n".join(closing(rows, started)))


if __name__ == "__main__":
    main()
