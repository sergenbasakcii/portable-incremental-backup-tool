# -*- coding: utf-8 -*-
r"""
Portable Incremental Backup Engine — Sergen Başakçı

Özellikler:
- Artımlı yedekleme: SHA-256 içerik adresli store (.store)
- Snapshot: repo/snapshots/<timestamp>/files altında hardlink (fallback copy)
- Manifest: snapshot/manifest.json
- Restore / Verify
- Tek dosya restore (file-level restore)
- Windows VSS (diskshadow) opsiyonel (admin gerekir)
- JSONL log (repo/logs)

Not:
- Windows path örnekleri docstring içinde C:/Users/... formatında yazılmıştır.
"""

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
# Windows VSS Context (Diskshadow)
# ----------------------------

class VSSContext:
    """Windows Volume Shadow Copy ile okuma için snapshot oluşturur."""

    def __init__(self, sources: List[Path]):
        self.enabled = IS_WIN
        self.sources = sources
        self.volumes = {p.drive.upper() for p in sources if p.drive}
        self.drive_map: dict[str, str] = {}  # "C:" -> "Z:"
        self.tmpdir = Path(tempfile.mkdtemp(prefix="vss_")) if self.enabled else None

    def __enter__(self):
        if not self.enabled:
            return self

        try:
            is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            is_admin = False

        if not is_admin:
            print("[VSS] Yönetici hakları yok → VSS devre dışı.")
            self.enabled = False
            return self

        if not self.volumes:
            print("[VSS] Drive letter bulunamadı (UNC olabilir) → VSS devre dışı.")
            self.enabled = False
            return self

        script: List[str] = ["SET CONTEXT PERSISTENT", "BEGIN BACKUP"]
        letters = list("ZYXWVUTSRQPONMLKJHGFEDCBA")

        aliases: List[Tuple[str, str]] = []
        for i, vol in enumerate(sorted(self.volumes)):
            alias = f"A{i}"
            script.append(f"ADD VOLUME {vol} ALIAS {alias}")
            aliases.append((vol, alias))

        script.append("CREATE")

        for i, (vol, alias) in enumerate(aliases):
            if i >= len(letters):
                break
            letter = letters[i]
            script.append(f"EXPOSE {alias} {letter}:")
            self.drive_map[vol] = f"{letter}:"

        script.append("END BACKUP")

        scr = self.tmpdir / "create.dsh"
        scr.write_text("\n".join(script), encoding="utf-8")

        result = subprocess.run(["diskshadow", "/s", str(scr)], capture_output=True, text=True)
        if result.returncode != 0:
            print("[VSS] diskshadow başarısız → VSS kapatıldı.")
            self.enabled = False

        return self

    def map_path(self, p: Path) -> Path:
        """Örn: C:/Users/... -> Z:/Users/..."""
        if not (self.enabled and p.drive):
            return p

        original = p.drive.upper()
        mapped_drive = self.drive_map.get(original)
        if mapped_drive:
            mapped = str(p).replace(original, mapped_drive, 1)
            return Path(mapped)
        return p

    def __exit__(self, exc_type, exc, tb):
        if not (self.enabled and self.tmpdir):
            return False

        script: List[str] = ["BEGIN BACKUP"]
        for mapped in self.drive_map.values():
            script.append(f"UNEXPOSE {mapped}")
        script.append("DELETE SHADOWS ALL")
        script.append("END BACKUP")

        scr = self.tmpdir / "cleanup.dsh"
        scr.write_text("\n".join(script), encoding="utf-8")
        subprocess.run(["diskshadow", "/s", str(scr)], capture_output=True)
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        return False


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
    """
    Pattern eşleşmesi:
    - Dosya adına göre (öncelikli)
    - Tam path'e göre (ikincil)
    """
    name = path.name
    full = str(path)
    for pat in patterns or []:
        pat = (pat or "").strip()
        if not pat:
            continue
        if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(full, pat):
            return True
    return False


def should_process(path: Path, patterns: List[str], mode: str) -> bool:
    """
    mode:
      - 'exclude': pattern match olanları alma
      - 'include': sadece pattern match olanları al
    """
    mode = (mode or "exclude").strip().lower()
    matched = match_patterns(path, patterns)

    if mode == "include":
        return matched
    # default exclude
    return not matched


def ensure_hardlink_or_copy(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        if dst.exists():
            dst.unlink()
        os.link(src, dst)
    except Exception:
        shutil.copy2(src, dst)


# ----------------------------
# Snapshot Helpers
# ----------------------------

def list_snapshots(repo: Path) -> List[str]:
    snaps_root = repo / "snapshots"
    if not snaps_root.exists():
        return []
    return sorted([p.name for p in snaps_root.iterdir() if p.is_dir()])


def resolve_snapshot(repo: Path, snapshot_id: str) -> Path:
    snaps_root = repo / "snapshots"

    if snapshot_id.lower() == "latest":
        snaps = list_snapshots(repo)
        if not snaps:
            raise RuntimeError("Snapshot bulunamadı.")
        snapshot_id = snaps[-1]

    snap = snaps_root / snapshot_id
    if not snap.exists():
        raise RuntimeError(f"Snapshot bulunamadı: {snapshot_id}")

    return snap


def snapshot_files_root(repo: Path, snapshot_id: str) -> Path:
    snap = resolve_snapshot(repo, snapshot_id)
    root = snap / "files"
    if not root.exists():
        raise RuntimeError("Geçersiz snapshot: files klasörü yok.")
    return root


# ----------------------------
# Restore / Verify
# ----------------------------

def restore_full_snapshot(repo: Path, snapshot_id: str, target: Path):
    files_dir = snapshot_files_root(repo, snapshot_id)
    target.mkdir(parents=True, exist_ok=True)

    for dirpath, _, filenames in os.walk(files_dir):
        for name in filenames:
            src = Path(dirpath) / name
            rel = src.relative_to(files_dir)
            dst = target / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def restore_single_file(repo: Path, snapshot_id: str, rel_path: str, target_dir: Path) -> Path:
    """
    rel_path: snapshot files root altındaki relative path (örn: TestData/a/b.pdf)
    """
    files_dir = snapshot_files_root(repo, snapshot_id)
    src = files_dir / rel_path

    if not src.exists() or not src.is_file():
        raise RuntimeError(f"Dosya bulunamadı: {rel_path}")

    target_dir.mkdir(parents=True, exist_ok=True)
    dst = target_dir / Path(rel_path).name
    shutil.copy2(src, dst)
    return dst


def verify(repo: Path, snapshot_id: str):
    snap = resolve_snapshot(repo, snapshot_id)
    manifest_path = snap / "manifest.json"
    if not manifest_path.exists():
        raise RuntimeError("Manifest yok.")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ok = 0
    bad = 0

    for e in manifest.get("entries", []):
        h = e.get("hash")
        if not h:
            continue
        blob = repo / ".store" / h[:2] / h
        if blob.exists():
            ok += 1
        else:
            bad += 1

    print(f"VERIFY → OK: {ok}, EKSİK: {bad}")


# ----------------------------
# Backup Engine
# ----------------------------

def backup(
    repo: Path,
    sources: List[Path],
    patterns: List[str],
    pattern_mode: str,
    use_vss: bool,
    max_retries: int
):
    """
    patterns + pattern_mode:
      - mode 'exclude': pattern match olanları SKIP
      - mode 'include': pattern match olmayanları SKIP
    """
    repo = repo.expanduser().resolve()
    srcs = [p.expanduser().resolve() for p in sources]

    if not srcs:
        raise RuntimeError("En az bir kaynak klasör gerekli.")

    repo.mkdir(parents=True, exist_ok=True)
    (repo / "snapshots").mkdir(parents=True, exist_ok=True)
    (repo / "logs").mkdir(parents=True, exist_ok=True)

    timestamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    snapshot = repo / "snapshots" / timestamp
    files_dir = snapshot / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    store = repo / ".store"
    store.mkdir(parents=True, exist_ok=True)

    logger = Logger(repo / "logs" / f"backup-{timestamp}.jsonl")
    logger.write({
        "event": "start",
        "timestamp": timestamp,
        "repo": str(repo),
        "sources": [str(s) for s in srcs],
        "pattern_mode": pattern_mode,
        "patterns": patterns
    })

    manifest = {"timestamp": timestamp, "entries": []}

    ctx = VSSContext(srcs) if (use_vss and IS_WIN) else None

    class Dummy:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    context = ctx if ctx else Dummy()

    print("BACKUP BAŞLADI")
    print("Repo:", repo)
    print("Sources:", srcs)
    print("Mode:", pattern_mode)
    print("Patterns:", patterns)

    with context:
        for root in srcs:
            mapped_root = ctx.map_path(root) if (ctx and ctx.enabled) else root

            if not mapped_root.exists():
                logger.write({"event": "source_missing", "path": str(mapped_root)})
                print(f"❌ Kaynak bulunamadı: {mapped_root}")
                continue

            print("İşleniyor:", mapped_root)

            for dirpath, _, filenames in os.walk(mapped_root):
                for name in filenames:
                    s = Path(dirpath) / name

                    if not should_process(s, patterns, pattern_mode):
                        logger.write({"event": "skip_by_filter", "path": str(s)})
                        continue

                    try:
                        rel = s.relative_to(mapped_root)
                    except Exception:
                        rel = Path(name)

                    dst = files_dir / root.name / rel

                    attempt = 0
                    while True:
                        try:
                            h = sha256_file(s)
                            blob = store / h[:2] / h
                            blob.parent.mkdir(parents=True, exist_ok=True)

                            if not blob.exists():
                                shutil.copy2(s, blob)
                                logger.write({"event": "blob_copy", "path": str(s), "hash": h})
                            else:
                                logger.write({"event": "blob_reuse", "path": str(s), "hash": h})

                            ensure_hardlink_or_copy(blob, dst)

                            try:
                                st = s.stat()
                                size = st.st_size
                                mtime = int(st.st_mtime)
                            except Exception:
                                size = None
                                mtime = None

                            manifest["entries"].append({
                                "path": f"{root.name}/{rel.as_posix()}",
                                "hash": h,
                                "size": size,
                                "mtime": mtime
                            })
                            break

                        except Exception as e:
                            attempt += 1
                            logger.write({"event": "error", "path": str(s), "error": str(e), "attempt": attempt})
                            if attempt >= int(max_retries):
                                print(f"HATA: {s} → {e}")
                                break
                            time.sleep(min(5 * attempt, 30))

    with (snapshot / "manifest.json").open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    logger.write({"event": "done", "snapshot": str(snapshot), "entry_count": len(manifest["entries"])})
    print("✔ Snapshot oluşturuldu:", snapshot)


# ----------------------------
# Config
# ----------------------------

def load_config(path: Path) -> Tuple[Path, List[Path], List[str], str, bool, int]:
    """
    Geriye dönük uyumluluk:
      - eski config: exclude vardı
      - yeni: patterns + pattern_mode
    """
    cfg = json.loads(path.read_text(encoding="utf-8"))

    repo = Path(cfg["repo_path"]).expanduser()
    sources = [Path(s["path"]).expanduser() for s in cfg.get("sources", [])]

    # Eski config: sources[*].exclude
    patterns: List[str] = []
    for s in cfg.get("sources", []):
        patterns.extend(s.get("exclude", []))

    # Yeni alanlar:
    patterns = cfg.get("patterns", patterns)
    pattern_mode = cfg.get("pattern_mode", "exclude")

    use_vss = bool(cfg.get("use_vss", False))
    max_retries = int(cfg.get("max_retries", 3))

    return repo, sources, patterns, pattern_mode, use_vss, max_retries


# ----------------------------
# CLI
# ----------------------------

def main():
    ap = argparse.ArgumentParser(description="Portable Incremental Backup Tool (Engine)")
    sub = ap.add_subparsers(dest="cmd")

    ap_b = sub.add_parser("backup", help="Yedek al")
    ap_b.add_argument("--config", required=True, help="JSON config yolu")

    ap_l = sub.add_parser("list", help="Snapshot listele")
    ap_l.add_argument("--repo", required=True)

    ap_r = sub.add_parser("restore", help="Snapshot restore (tam)")
    ap_r.add_argument("--repo", required=True)
    ap_r.add_argument("--snapshot", required=True, help="snapshot id veya latest")
    ap_r.add_argument("--to", required=True, help="hedef klasör")

    ap_rf = sub.add_parser("restore-file", help="Snapshot içinden tek dosya restore")
    ap_rf.add_argument("--repo", required=True)
    ap_rf.add_argument("--snapshot", required=True)
    ap_rf.add_argument("--rel", required=True, help="files altında relative path (örn: TestData/a.pdf)")
    ap_rf.add_argument("--to", required=True, help="hedef klasör")

    ap_v = sub.add_parser("verify", help="Bütünlük kontrolü")
    ap_v.add_argument("--repo", required=True)
    ap_v.add_argument("--snapshot", required=True, help="snapshot id veya latest")

    args = ap.parse_args()

    if args.cmd == "backup":
        repo, sources, patterns, mode, use_vss, max_r = load_config(Path(args.config))
        backup(repo, sources, patterns, mode, use_vss, max_r)

    elif args.cmd == "list":
        for s in list_snapshots(Path(args.repo)):
            print(s)

    elif args.cmd == "restore":
        restore_full_snapshot(Path(args.repo), args.snapshot, Path(args.to))
        print("✅ Restore tamamlandı.")

    elif args.cmd == "restore-file":
        out = restore_single_file(Path(args.repo), args.snapshot, args.rel, Path(args.to))
        print(f"✅ Tek dosya restore: {out}")

    elif args.cmd == "verify":
        verify(Path(args.repo), args.snapshot)

    else:
        ap.print_help()


if __name__ == "__main__":
    main()