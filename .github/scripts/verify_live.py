"""Verify the actual public release after Stellar's scheduled pull."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.request


def verify(base, commit, manifest):
    def fetch(path):
        url = base + "/" + path + "?release-check=" + commit
        request = urllib.request.Request(url, headers={"User-Agent": "CWA-Publication-Verification/1.0", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(request, timeout=20) as response:
            if not response.url.startswith(base + "/"):
                raise ValueError("Unexpected public redirect")
            return response.read()
    deployment = json.loads(fetch("deployment.json"))
    if deployment.get("commit") != commit or deployment.get("release") != manifest["release"]:
        raise ValueError("Hosting has not activated the expected complete release")
    for item in manifest["files"]:
        data = fetch(item["path"])
        if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError("Live file does not match: " + item["path"])
    return deployment


def main():
    commit, directory = sys.argv[1:]
    manifest = json.loads((Path(directory) / "manifest.json").read_text())
    base = "https://clinicallywelladjusted.com"
    deadline = time.monotonic() + 540
    while True:
        try:
            deployment = verify(base, commit, manifest)
            break
        except Exception as error:
            if time.monotonic() >= deadline:
                raise RuntimeError("Live publication was not verified within nine minutes") from error
            print("Waiting for verified public release:", str(error), flush=True)
            time.sleep(30)
    evidence = {"live_verified": True, "site": base, "commit": commit,
                "release": manifest["release"], "files_verified": len(manifest["files"]),
                "deployed_at": deployment["deployed_at"]}
    print(json.dumps(evidence, indent=2), flush=True)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as output:
            output.write("Verified live publication\n\n```json\n" + json.dumps(evidence, indent=2) + "\n```\n")


if __name__ == "__main__":
    main()
