from __future__ import annotations

import hashlib
import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path


URL = "https://cdn.uci-ics-mlr-prod.aws.uci.edu/601/ai4i%2B2020%2Bpredictive%2Bmaintenance%2Bdataset.zip"
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "ai4i"
sys.path.insert(0, str(ROOT / "src"))

from industrial_maintenance_agent.data_import import profile_ai4i  # noqa: E402


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    archive = RAW / "ai4i.zip"
    request = urllib.request.Request(URL, headers={"User-Agent": "industrial-maintenance-agent/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response, archive.open("wb") as output:
        shutil.copyfileobj(response, output)
    with zipfile.ZipFile(archive) as zipped:
        member = next(name for name in zipped.namelist() if name.lower().endswith(".csv"))
        target = RAW / "ai4i2020.csv"
        with zipped.open(member) as source, target.open("wb") as output:
            shutil.copyfileobj(source, output)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest = {
        "source_url": URL,
        "source_page": "https://archive.ics.uci.edu/dataset/601/ai4i",
        "license": "CC BY 4.0",
        "file": target.name,
        "sha256": digest,
        "profile": profile_ai4i(target),
    }
    manifest_dir = ROOT / "data" / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "ai4i.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(target)
    print(digest)


if __name__ == "__main__":
    main()
