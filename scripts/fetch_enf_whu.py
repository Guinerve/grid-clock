"""Download a pinned copy of the public ENF-WHU dataset and verify every file.

ENF-WHU (Hua et al., MIT licence) holds phone and voice-recorder clips from
Wuhan University with simultaneous mains-power references. The audio stays in
data/raw/, which git ignores. Only standard-library modules are used.

    uv run python scripts/fetch_enf_whu.py            # H1, H1_ref, H0 originals
    uv run python scripts/fetch_enf_whu.py --one-day  # also 24-hour references (~1.9 GB)
"""

import argparse
import hashlib
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPOSITORY = "ghua-ac/ENF-WHU-Dataset"
COMMIT = "78ed7f3784949f769f291fc1cb94acd10da6322f"
TREE_URL = f"https://api.github.com/repos/{REPOSITORY}/git/trees/{COMMIT}?recursive=1"
RAW_URL = f"https://raw.githubusercontent.com/{REPOSITORY}/{COMMIT}/"
PREFIX = "ENF-WHU-Dataset/"


def git_blob_sha(path: Path) -> str:
    digest = hashlib.sha1(f"blob {path.stat().st_size}\0".encode())
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wanted(path: str, one_day: bool) -> bool:
    if not path.startswith(PREFIX) or not path.endswith(".wav"):
        return False
    folder, name = path[len(PREFIX) :].split("/", 1)
    if folder == "H0":
        return name.startswith("O")  # The numbered H0 files are crops of these.
    return folder in {"H1", "H1_ref"} or (one_day and folder == "H1_ref_one_day")


def fetch(entry: dict, root: Path) -> str:
    target = root / entry["path"][len(PREFIX) :]
    if target.is_file() and git_blob_sha(target) == entry["sha"]:
        return "kept"
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    with urllib.request.urlopen(RAW_URL + entry["path"], timeout=120) as response:
        partial.write_bytes(response.read())
    if git_blob_sha(partial) != entry["sha"]:
        partial.unlink()
        raise ValueError(f"Checksum mismatch: {entry['path']}")
    partial.replace(target)
    return "downloaded"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=Path("data/raw/enf-whu"))
    parser.add_argument("--one-day", action="store_true", help="Include 24-hour references")
    args = parser.parse_args(argv)
    with urllib.request.urlopen(TREE_URL, timeout=60) as response:
        tree = json.load(response)
    if tree.get("truncated"):
        raise SystemExit("GitHub returned a truncated file list.")
    entries = [e for e in tree["tree"] if e["type"] == "blob" and wanted(e["path"], args.one_day)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda e: fetch(e, args.output), entries))
    print(
        f"{len(entries)} files verified at commit {COMMIT[:12]}: "
        f"{results.count('downloaded')} downloaded, {results.count('kept')} already present.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
