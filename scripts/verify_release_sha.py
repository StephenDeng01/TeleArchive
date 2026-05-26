#!/usr/bin/env python3
"""Verify GitHub Release exe sha256 matches version.json and the .sha256 sidecar."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "TeleArchive-verify"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", default="StephenDeng01")
    parser.add_argument("--repo", default="TeleArchive")
    parser.add_argument("--tag", required=True, help="Release tag, e.g. v0.6.7")
    parser.add_argument(
        "--manifest-url",
        default="",
        help="Override version.json URL (default: raw main/version.json)",
    )
    args = parser.parse_args()

    tag = args.tag
    base = f"https://github.com/{args.owner}/{args.repo}/releases/download/{tag}"
    manifest_url = args.manifest_url or (
        f"https://raw.githubusercontent.com/{args.owner}/{args.repo}/main/version.json"
    )

    try:
        sidecar = _get(f"{base}/TeleArchive.exe.sha256").decode("utf-8").strip().lower()
        manifest_raw = _get(manifest_url).decode("utf-8")
    except urllib.error.URLError as exc:
        print(f"fetch failed: {exc}", file=sys.stderr)
        return 1

    if not re.fullmatch(r"[0-9a-f]{64}", sidecar):
        print(f"invalid sidecar sha256: {sidecar!r}", file=sys.stderr)
        return 1

    try:
        manifest = json.loads(manifest_raw)
    except json.JSONDecodeError as exc:
        print(f"invalid manifest json: {exc}", file=sys.stderr)
        return 1

    manifest_sha = str(manifest.get("sha256") or "").strip().lower()
    manifest_tag = str(manifest.get("tag") or "")
    if manifest_tag and manifest_tag != tag:
        print(f"manifest tag mismatch: manifest={manifest_tag!r} expected={tag!r}", file=sys.stderr)
        return 1
    if manifest_sha != sidecar:
        print(
            f"sha256 mismatch for {tag}:\n"
            f"  sidecar:  {sidecar}\n"
            f"  manifest: {manifest_sha or '(empty)'}",
            file=sys.stderr,
        )
        return 1

    print(f"OK {tag}: manifest sha256 matches release sidecar ({sidecar})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
