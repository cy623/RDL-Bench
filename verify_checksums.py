"""Verify the integrity of an RDL-Bench release against SHA256SUMS.

Usage (run from anywhere; only the Python standard library is needed):

    python verify_checksums.py              # check every file listed in SHA256SUMS
    python verify_checksums.py --skip-db    # skip the large DB/*.duckdb files
    python verify_checksums.py --root PATH  # check a release folder elsewhere
    python verify_checksums.py --sums FILE  # use a SHA256SUMS file kept elsewhere

By default the script checks the folder it is in, using the SHA256SUMS file
in that folder, so place both files in the unzipped release folder.

Equivalent shell commands from the release root:

    sha256sum -c SHA256SUMS            # Linux
    shasum -a 256 -c SHA256SUMS        # macOS

Exit status: 0 if every listed file is present and matches, 1 otherwise.
Files that are present but not listed are reported as warnings only.

Maintainers: ``--write`` recomputes SHA256SUMS and the ``files`` section of
manifest.json from the current tree. Use it only when preparing a release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

SUMS_NAME = "SHA256SUMS"
MANIFEST_NAME = "manifest.json"
# Operating-system artefacts that must never be part of a release.
JUNK_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}
JUNK_DIRS = {"__MACOSX", "__pycache__", ".git", ".ipynb_checkpoints"}
CHUNK = 1 << 20


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def is_junk(rel: str) -> bool:
    parts = rel.split("/")
    return parts[-1] in JUNK_NAMES or any(p in JUNK_DIRS for p in parts[:-1]) \
        or parts[-1].endswith(".pyc")


def tree(root: Path):
    """All regular files under root as sorted POSIX paths."""
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def read_sums(path: Path) -> dict[str, str]:
    entries = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        digest, sep, name = line.partition("  ")
        if not sep or len(digest) != 64:
            raise ValueError(f"{path.name}:{number}: malformed line")
        entries[name.lstrip("*")] = digest.lower()
    return entries


def verify(root: Path, skip_db: bool, sums_path: Path | None = None) -> int:
    sums_path = sums_path or root / SUMS_NAME
    if not sums_path.is_file():
        print(f"ERROR: {sums_path} not found")
        return 1
    expected = read_sums(sums_path)
    ok = bad = missing = skipped = 0
    for name, digest in expected.items():
        path = root / name
        if skip_db and name.startswith("DB/"):
            skipped += 1
            continue
        if not path.is_file():
            missing += 1
            print(f"MISSING   {name}")
        elif sha256(path) != digest:
            bad += 1
            print(f"MODIFIED  {name}")
        else:
            ok += 1

    present = [p for p in tree(root) if p not in (SUMS_NAME, Path(__file__).name)]
    junk = [p for p in present if is_junk(p)]
    extra = [p for p in present if p not in expected and p not in junk]
    for name in junk:
        print(f"JUNK      {name}  (operating-system file; safe to delete)")
    for name in extra:
        print(f"UNLISTED  {name}  (not part of the release)")

    manifest_path = root / MANIFEST_NAME
    if manifest_path.is_file():
        listed = json.loads(manifest_path.read_text(encoding="utf-8")).get("files", {})
        stale = [n for n, e in listed.items()
                 if n not in expected or e.get("sha256") != expected[n]]
        if stale:
            print(f"NOTE      {len(stale)} entries in manifest.json files{{}} are outdated; "
                  f"{SUMS_NAME} is authoritative (see DATASET_CARD.md, known packaging notes)")

    summary = f"{ok} OK, {bad} modified, {missing} missing"
    if skipped:
        summary += f", {skipped} skipped (--skip-db)"
    if junk or extra:
        summary += f"; {len(junk)} junk and {len(extra)} unlisted file(s) present"
    print(summary)
    if bad or missing:
        print("Integrity check FAILED. Re-download the affected files from the official release.")
        return 1
    print("Integrity check passed.")
    return 0


def write(root: Path) -> int:
    """Maintainers only: refresh manifest.json files{} and SHA256SUMS."""
    names = [p for p in tree(root) if p != SUMS_NAME]
    junk = [p for p in names if is_junk(p)]
    if junk:
        print("Remove these files first:\n  " + "\n  ".join(junk))
        return 1
    manifest_path = root / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = {
        name: {"bytes": (root / name).stat().st_size, "sha256": sha256(root / name)}
        for name in names if name != MANIFEST_NAME
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
    lines = [f"{manifest['files'][n]['sha256'] if n != MANIFEST_NAME else sha256(root / n)}  {n}"
             for n in names]
    (root / SUMS_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {SUMS_NAME} ({len(lines)} files) and refreshed {MANIFEST_NAME}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent,
                        help="release folder (default: the folder containing this script)")
    parser.add_argument("--sums", type=Path, default=None,
                        help="SHA256SUMS file to check against (default: <root>/SHA256SUMS)")
    parser.add_argument("--skip-db", action="store_true", help="skip DB/*.duckdb files")
    parser.add_argument("--write", action="store_true",
                        help="maintainers: regenerate SHA256SUMS and manifest.json files{}")
    args = parser.parse_args()
    root = args.root.resolve()
    return write(root) if args.write else verify(root, args.skip_db, args.sums)


if __name__ == "__main__":
    sys.exit(main())
