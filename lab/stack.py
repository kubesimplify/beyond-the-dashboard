"""Run the bookshop against VictoriaStack instead of the lab's own databases.

Start VictoriaStack's quick start first, so that vmauth listens on port 8427,
and stop the lab (control.py stop). Then, from the lab directory:

    .venv/bin/python stack.py start      # inventory, checkout, and vmagent
    .venv/bin/python stack.py commands   # print the lines it runs
    .venv/bin/python stack.py stop

The apps and their telemetry code are unchanged. Three addresses differ from
control.py: where logs go, where spans go, and where vmagent sends samples.
All three point at vmauth, the stack's single entry point.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
from urllib.request import urlopen

from control import BIN, PYTHON, process_matches, shell_line

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / ".runtime"
STATE = RUNTIME / "stack-processes.json"
ENTRY = os.environ.get("STACK_URL", "http://127.0.0.1:8427")
ADDRESSES = {"LOG_URL": ENTRY + "/logs", "TRACE_URL": ENTRY + "/traces"}
SERVICES = [
    ("inventory", 8081, [PYTHON, "app.py"], {"SERVICE": "inventory", "PORT": "8081", **ADDRESSES}),
    ("checkout", 8080, [PYTHON, "app.py"], {"SERVICE": "checkout", "PORT": "8080", **ADDRESSES}),
    ("vmagent", 8429,
     [f"{BIN}/vmagent-prod", "-httpListenAddr=127.0.0.1:8429",
      "-promscrape.config=config/scrape-stack.yml",
      f"-remoteWrite.url={ENTRY}/metrics/insert/api/v1/write",
      "-remoteWrite.tmpDataPath=.runtime/vmagent-stack"], {}),
]


def stop():
    if not STATE.exists():
        print("No bookshop processes recorded for VictoriaStack.")
        return
    for item in reversed(json.loads(STATE.read_text())):
        if process_matches(item):
            os.kill(item["pid"], signal.SIGTERM)
            deadline = time.monotonic() + 10
            while process_matches(item) and time.monotonic() < deadline:
                time.sleep(.2)
            if process_matches(item):
                raise SystemExit(f"{item['name']} has not stopped. Inspect PID {item['pid']} before retrying.")
            print("Stopped " + item["name"])
    STATE.unlink()


def start():
    if STATE.exists():
        raise SystemExit("Already started. Run stack.py stop first.")
    if (RUNTIME / "processes.json").exists():
        raise SystemExit("The lab is running. Run control.py stop first.")
    try:
        with urlopen(ENTRY + "/metrics/select/prometheus/api/v1/query?query=1", timeout=5) as response:
            response.read()
    except Exception as error:
        raise SystemExit(f"VictoriaStack does not answer on {ENTRY} ({error}). Start it first.")
    for _, port, _, _ in SERVICES:
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                raise SystemExit(f"Port {port} is in use. No processes started.")
    RUNTIME.mkdir(exist_ok=True)
    entries = []
    try:
        for name, port, command, extra_env in SERVICES:
            with (RUNTIME / f"stack-{name}.log").open("a") as output:
                child = subprocess.Popen(command, cwd=ROOT, env={**os.environ, **extra_env},
                                         stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            identity = "app.py" if command[-1] == "app.py" else command[0]
            entries.append({"name": name, "pid": child.pid, "port": port, "identity": identity})
            STATE.write_text(json.dumps(entries, indent=2) + "\n")
            deadline = time.monotonic() + 60
            while True:
                if child.poll() is not None:
                    raise RuntimeError(f"{name} exited. Read .runtime/stack-{name}.log")
                try:
                    with urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except Exception:
                    if time.monotonic() > deadline:
                        raise RuntimeError(f"{name} did not become healthy")
                    time.sleep(.25)
            print(f"Started {name:<10} http://127.0.0.1:{port}, sending to {ENTRY}", flush=True)
    except Exception:
        stop()
        raise


def commands():
    print("# From the lab directory, one terminal per line. stack.py start runs the same lines.")
    for _, _, command, extra_env in SERVICES:
        print(shell_line(command, extra_env))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run checkout, inventory, and vmagent against VictoriaStack.")
    parser.add_argument("action", choices=("start", "stop", "commands"))
    {"start": start, "stop": stop, "commands": commands}[parser.parse_args().action]()
