# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import fnmatch
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import List, Tuple, Optional

IS_WIN = platform.system().lower().startswith("win")


# ----------------------------
# Logger
# ----------------------------

class Logger:
    def __init__(self, log_file: Optional[Path]):
        self.log_file = log_file
        self.lock = threading.Lock()
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)

    def write(self, obj: dict):
        line = json.dumps(obj, ensure_ascii=False)
        if self.log_file:
            with self.lock:
                with self.log_file.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
        else:
            print(line)


# ----------------------------
# Helpers
# ----------------------------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(4 * 1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def match_patterns(path: Path, patterns: List[str]) -> bool:
    for pat in patterns or []:
        if fnmatch.fnmatch(path.name, pat) or fnmatch.fnmatch(str(path), pat):
            return True
    return False


def should_process(path: Path, patterns: List[str], mode: str) -> bool:
    matched = match_patterns(path, patterns)
    if mode == "include":
        return matched
    return not matched


def list_snapshots(repo: Path) -> List[str]:
    root = repo / "snapshots"
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def load_last_manifest(repo: Path) -> dict:
    snaps = list_snapshots(repo)
    if not snaps:
        return {}
    last = repo / "snapshots" / snaps[-1] / "manifest.json"
    if not last.exists():
        return {}
    return json.loads(last.read_text(encoding="utf-8"))


# ----------------------------
# Backup Engine (TRUE INCREMENTAL)
# ----------------------------

def backup(
    repo: Path,
    sources: List[Path],
    patterns: List[str],
    pattern_mode: str,
    use_vss: bool,
    max_retries: int
):
    repo = repo.resolve()
    repo.mkdir(parents=True, exist_ok=True)
    (repo / ".store").mkdir(exist_ok=True)
    (repo / "snapshots").mkdir(exist_ok=True)
    (repo / "logs").mkdir(exist_ok=True)

    prev_manifest = load_last_manifest(repo)
    prev_hashes = {e["path"]: e["hash"] for e in prev_manifest.get("entries", [])}

    timestamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    snapshot = repo / "snapshots" / timestamp
    files_dir = snapshot / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    manifest = {"timestamp": timestamp, "entries": []}

    total = 0
    taken = 0
    skipped = 0

    for src in sources:
        for _, _, files in os.walk(src):
            total += len(files)

    print(f"TOPLAM DOSYA: {total}")

    for src in sources:
        src = src.resolve()
        for dirpath, _, filenames in os.walk(src):
            for name in filenames:
                s = Path(dirpath) / name

                if not should_process(s, patterns, pattern_mode):
                    skipped += 1
                    continue

                rel = s.relative_to(src)
                logical_path = f"{src.name}/{rel.as_posix()}"

                h = sha256_file(s)

                if prev_hashes.get(logical_path) == h:
                    skipped += 1
                    print(f"ATLANDI (değişmedi): {logical_path}")
                    continue

                blob = repo / ".store" / h[:2] / h
                blob.parent.mkdir(parents=True, exist_ok=True)
                if not blob.exists():
                    shutil.copy2(s, blob)

                dst = files_dir / logical_path
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(blob, dst)

                manifest["entries"].append({
                    "path": logical_path,
                    "hash": h,
                    "size": s.stat().st_size,
                    "mtime": int(s.stat().st_mtime)
                })

                taken += 1
                remaining = total - (taken + skipped)

                print(
                    f"İLERLEME → "
                    f"Toplam:{total} | "
                    f"Alınan:{taken} | "
                    f"Atlanan:{skipped} | "
                    f"Kalan:{remaining}"
                )

    (snapshot / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("✔ Snapshot oluşturuldu:", snapshot)


# ----------------------------
# Restore
# ----------------------------

def restore_full_snapshot(repo: Path, snapshot_id: str, target: Path):
    src = repo / "snapshots" / snapshot_id / "files"
    for root, _, files in os.walk(src):
        for f in files:
            p = Path(root) / f
            rel = p.relative_to(src)
            dst = target / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)


def restore_single_file(repo: Path, snapshot_id: str, rel_path: str, target: Path):
    src = repo / "snapshots" / snapshot_id / "files" / rel_path
    if not src.exists():
        raise RuntimeError("Dosya bulunamadı")
    target.mkdir(parents=True, exist_ok=True)
    dst = target / src.name
    shutil.copy2(src, dst)
    return dst
