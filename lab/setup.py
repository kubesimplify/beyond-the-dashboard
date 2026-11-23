"""Download pinned official binaries and install app dependencies locally."""
import hashlib
import json
import platform
from pathlib import Path
import socket
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / ".cache"
BIN = CACHE / "bin"


def main():
    # Bound each network connection/read so an unreachable release host address
    # cannot stall setup indefinitely. This is not a whole-download deadline.
    socket.setdefaulttimeout(10)
    system = platform.system().lower()
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "amd64"}.get(platform.machine())
    if system not in ("darwin", "linux") or not arch:
        raise SystemExit("Use Docker Compose on this platform, or install supported binaries manually.")
    BIN.mkdir(parents=True, exist_ok=True)
    versions = json.loads((ROOT / "versions.json").read_text())
    receipts = []
    for repo, prefix, names in [
        ("VictoriaMetrics", "victoria-metrics", ["victoria-metrics-prod"]),
        ("VictoriaMetrics", "vmutils", ["vmagent-prod", "vmalert-prod"]),
        ("VictoriaLogs", "victoria-logs", ["victoria-logs-prod"]),
        ("VictoriaTraces", "victoria-traces", ["victoria-traces-prod"]),
    ]:
        tag = versions[repo]
        base = f"{prefix}-{system}-{arch}-{tag}"
        url = f"https://github.com/VictoriaMetrics/{repo}/releases/download/{tag}/{base}.tar.gz"
        archive = CACHE / f"{base}.tar.gz"
        if not archive.exists():
            print(f"Downloading {archive.name}", flush=True)
            urllib.request.urlretrieve(url, archive)
        checksum_url = url.removesuffix(".tar.gz") + "_checksums.txt"
        checksum_text = urllib.request.urlopen(checksum_url).read().decode()
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        # Release checksum files cover the executable, not always its archive.
        with tarfile.open(archive) as tar:
            for name in names:
                members = [m for m in tar.getmembers() if Path(m.name).name == name and m.isfile()]
                if len(members) != 1:
                    raise RuntimeError(f"Missing executable {name} in {archive.name}")
                data = tar.extractfile(members[0]).read()
                binary_sha256 = hashlib.sha256(data).hexdigest()
                matches = [line for line in checksum_text.splitlines()
                           if name in line and binary_sha256 in line]
                # Some releases checksum archives. Require either documented format.
                if not matches and not any(digest in line and archive.name in line
                                           for line in checksum_text.splitlines()):
                    raise RuntimeError(f"Checksum verification failed for {name}")
                destination = BIN / name
                destination.write_bytes(data)
                destination.chmod(0o755)
                receipts.append({"binary": name, "version": tag, "url": url,
                                 "sha256": binary_sha256, "checksums": checksum_url})
    (CACHE / "downloads.json").write_text(json.dumps(receipts, indent=2) + "\n")
    venv = ROOT / ".venv"
    if not venv.exists():
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    subprocess.run([str(venv / "bin/python"), "-m", "pip", "install", "-r",
                    str(ROOT / "requirements.lock")], check=True)
    print("Setup complete. Run .venv/bin/python control.py start")


if __name__ == "__main__":
    main()
