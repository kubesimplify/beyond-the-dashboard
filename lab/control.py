"""Start and stop the lab's seven local processes, and print how each one starts."""
import argparse
import json
import os
from pathlib import Path
import shlex
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / ".runtime"
STATE = RUNTIME / "processes.json"
BIN = ".cache/bin"
PYTHON = ".venv/bin/python"

# Each process: its name, port, the page to open, the command, and extra environment.
# Paths are relative to the lab directory, so the same lines work when typed by hand.
# Every listener binds to 127.0.0.1 on the product's default port.
SERVICES = [
    ("VictoriaMetrics", 8428, "/vmui/",
     [f"{BIN}/victoria-metrics-prod", "-httpListenAddr=127.0.0.1:8428",
      "-storageDataPath=.runtime/metrics", "-retentionPeriod=7d"], {}),
    ("VictoriaLogs", 9428, "/select/vmui/",
     [f"{BIN}/victoria-logs-prod", "-httpListenAddr=127.0.0.1:9428",
      "-storageDataPath=.runtime/logs", "-retentionPeriod=7d"], {}),
    # A one-second index flush makes new traces searchable quickly in a short lab.
    ("VictoriaTraces", 10428, "/select/vmui/",
     [f"{BIN}/victoria-traces-prod", "-httpListenAddr=127.0.0.1:10428",
      "-storageDataPath=.runtime/traces", "-retentionPeriod=7d",
      "-insert.indexFlushInterval=1s"], {"TZ": "UTC"}),
    ("vmagent", 8429, "/targets",
     [f"{BIN}/vmagent-prod", "-httpListenAddr=127.0.0.1:8429",
      "-promscrape.config=config/scrape.yml",
      "-remoteWrite.url=http://127.0.0.1:8428/api/v1/write",
      "-remoteWrite.tmpDataPath=.runtime/vmagent"], {}),
    # The lab has no Alertmanager, so notifications go nowhere; alert states are
    # written back to VictoriaMetrics as the ALERTS series.
    ("vmalert", 8880, "/vmalert/alerts",
     [f"{BIN}/vmalert-prod", "-httpListenAddr=127.0.0.1:8880",
      "-rule=config/alerts.yml", "-datasource.url=http://127.0.0.1:8428",
      "-remoteWrite.url=http://127.0.0.1:8428", "-notifier.blackhole"], {}),
    ("inventory", 8081, "/metrics", [PYTHON, "app.py"], {"SERVICE": "inventory", "PORT": "8081"}),
    ("checkout", 8080, "/metrics", [PYTHON, "app.py"], {"SERVICE": "checkout", "PORT": "8080"}),
]


def shell_line(command, env):
    return " ".join([f"{key}={value}" for key, value in env.items()] + [shlex.quote(part) for part in command])


def process_matches(item):
    result = subprocess.run(["ps", "-p", str(item["pid"]), "-o", "command="], capture_output=True, text=True)
    return result.returncode == 0 and item["identity"] in result.stdout


def stop():
    if not STATE.exists():
        print("No running lab recorded.")
        return
    entries = json.loads(STATE.read_text())
    for item in reversed(entries):
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
        raise SystemExit("Lab state already exists. Run control.py stop before starting again.")
    if not (ROOT / BIN).is_dir() or not (ROOT / PYTHON).exists():
        raise SystemExit("Run python3.12 setup.py first.")
    for _, port, _, _, _ in SERVICES:
        with socket.socket() as probe:
            # Match the HTTP servers' reuse behavior after a clean stop. A
            # TIME_WAIT connection is not a running listener on this port.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                raise SystemExit(f"Port {port} is in use. No processes started.")
    RUNTIME.mkdir(exist_ok=True)
    entries = []
    try:
        for name, port, page, command, extra_env in SERVICES:
            with (RUNTIME / f"{name}.log").open("a") as output:
                child = subprocess.Popen(command, cwd=ROOT, env={**os.environ, **extra_env},
                                         stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            # stop() signals this PID only while it still runs this command.
            identity = "app.py" if command[-1] == "app.py" else command[0]
            entries.append({"name": name, "pid": child.pid, "port": port, "identity": identity})
            STATE.write_text(json.dumps(entries, indent=2) + "\n")
            deadline = time.monotonic() + 60
            while True:
                if child.poll() is not None:
                    raise RuntimeError(f"{name} exited. Read .runtime/{name}.log")
                try:
                    with urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except Exception:
                    if time.monotonic() > deadline:
                        raise RuntimeError(f"{name} did not become healthy")
                    time.sleep(.25)
            print(f"Started {name:<16} http://127.0.0.1:{port}{page}", flush=True)
    except Exception:
        stop()
        raise


def commands():
    print("# From the lab directory, one terminal per line. control.py start runs the same lines.")
    for name, _, _, command, extra_env in SERVICES:
        print(shell_line(command, extra_env))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "stop", "status", "commands"))
    action = parser.parse_args().action
    if action == "start":
        start()
    elif action == "stop":
        stop()
    elif action == "commands":
        commands()
    else:
        items = json.loads(STATE.read_text()) if STATE.exists() else []
        print(json.dumps([{**item, "running": process_matches(item)} for item in items], indent=2))
