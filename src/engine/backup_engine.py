# -*- coding: utf-8 -*-
r"""
Portable Incremental Backup Engine — Sergen Başakçı

Özellikler:
- Artımlı yedekleme: SHA-256 içerik adresli store (.store)
- Snapshot: repo/snapshots/<timestamp>/files altında hardlink (fallback copy)
- Manifest: snapshot/manifest.json
- Restore / Verify
- Windows VSS (diskshadow) opsiyonel (admin gerekir)
- JSONL log (repo/logs)
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
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import List, Tuple, Optional

# ----------------------------
# Genel Ayarlar / Sabitler
# ----------------------------

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
    """
    Windows Volume Shadow Copy ile okuma için snapshot oluşturur.
    diskshadow ile volume snapshot alır, sonrasında expose eder.

    Admin yetkisi gerektirir. Admin yoksa otomatik devre dışı kalır.
    """

    def __init__(self, sources: List[Path]):
        self.enabled = IS_WIN
        self.sources = sources
        self.volumes = {p.drive.upper() for p in sources if p.drive}
        self.drive_map: dict[str, str] = {}  # "C:" -> "Z:"
        self.tmpdir = Path(tempfile.mkdtemp(prefix="vss_")) if self.enabled else None

    def __enter__(self):
        if not self.enabled:
            return self

        # Yönetici kontrolü
        try:
            is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            is_admin = False

        if not is_admin:
            print("[VSS] Yönetici hakları yok → VSS devre dışı.")
            self.enabled = False
            return self

        if not self.volumes:
            # Sürücü harfi yoksa (örn. UNC path) VSS yapamayız
            print("[VSS] Drive letter bulunamadı (UNC path olabilir) → VSS devre dışı.")
            self.enabled = False
            return self

        # Diskshadow script üretimi:
        # Önemli: CREATE -> sonra EXPOSE
        script: List[str] = [
            "SET CONTEXT PERSISTENT",
            "BEGIN BACKUP",
        ]

        letters = list("ZYXWVUTSRQPONMLKJHGFEDCBA")

        # önce volume ekle
        aliases: List[Tuple[str, str]] = []  # (vol, alias)
        for i, vol in enumerate(sorted(self.volumes)):
            alias = f"A{i}"
            script.append(f"ADD VOLUME {vol} ALIAS {alias}")
            aliases.append((vol, alias))

        script.append("CREATE")

        # sonra expose et
        for i, (vol, alias) in enumerate(aliases):
            if i >= len(letters):
                break
            letter = letters[i]
            script.append(f"EXPOSE {alias} {letter}:")
            self.drive_map[vol] = f"{letter}:"

        script.append("END BACKUP")

        scr = self.tmpdir / "create.dsh"
        scr.write_text("\n".join(script), encoding="utf-8")

        result = subprocess.run(
            ["diskshadow", "/s", str(scr)],
            capture_output=True, text=True
        )

        if result.returncode != 0:
            print("[VSS] diskshadow başarısız, VSS kapatıldı.")
            # Debug gerekirse:
            # print(result.stdout)
            # print(result.stderr)
            self.enabled = False

        return self

    def map_path(self, p: Path) -> Path:
        """
        Örn: C:/Users/... -> Z:/Users/...

        Bu fonksiyon, kaynak dosya yolu bir sürücü harfi içeriyorsa
        (örn. C:) bunu VSS expose edilen sürücüye (örn. Z:) map eder.
        """
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

        # Temizlik
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
# Yardımcı Fonksiyonlar
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


def should_exclude(path: Path, patterns: List[str]) -> bool:
    """
    Exclude pattern kontrolü:
    - Tam path'e göre
    - Dosya adına göre
    """
    s_full = str(path)
    s_name = path.name
    for pat in patterns or []:
        pat = pat.strip()
        if not pat:
            continue
        if fnmatch.fnmatch(s_full, pat) or fnmatch.fnmatch(s_name, pat):
            return True
    return False


def ensure_hardlink_or_copy(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        if dst.exists():
            dst.unlink()
        os.link(src, dst)  # hardlink
    except Exception:
        shutil.copy2(src, dst)  # fallback copy


# ----------------------------
# Snapshot / Restore yardımcıları
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


def restore(repo: Path, snapshot_id: str, target: Path):
    snap = resolve_snapshot(repo, snapshot_id)
    files_dir = snap / "files"
    if not files_dir.exists():
        raise RuntimeError("Geçersiz snapshot: files klasörü yok.")

    target.mkdir(parents=True, exist_ok=True)

    for dirpath, dirnames, filenames in os.walk(files_dir):
        for name in filenames:
            src = Path(dirpath) / name
            rel = src.relative_to(files_dir)
            dst = target / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


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

def backup(repo: Path, sources: List[Path], exclude: List[str], use_vss: bool, max_retries: int):
    """
    repo: yedekleme deposu
    sources: yedeklenecek klasörler
    exclude: pattern listesi
    use_vss: Windows VSS kullan
    max_retries: başarısız dosyada retry sayısı
    """
    print("BACKUP BAŞLADI")
    print("Repo:", repo)
    print("Sources:", sources)

    if not sources:
        raise RuntimeError("En az bir kaynak klasör gerekli.")

    repo = repo.expanduser().resolve()
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
    logger.write({"event": "start", "timestamp": timestamp, "repo": str(repo), "sources": [str(s) for s in sources]})

    manifest = {"timestamp": timestamp, "entries": []}

    # VSS context hazırlığı
    srcs = [p.expanduser().resolve() for p in sources]
    ctx = VSSContext(srcs) if (use_vss and IS_WIN) else None

    # fallback – boş context manager
    class Dummy:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    context = ctx if ctx else Dummy()

    with context:
        for root in srcs:
            mapped_root = ctx.map_path(root) if (ctx and ctx.enabled) else root

            if not mapped_root.exists():
                logger.write({"event": "source_missing", "path": str(mapped_root)})
                print(f"❌ Kaynak bulunamadı: {mapped_root}")
                continue

            print("İşleniyor:", mapped_root)
            logger.write({"event": "walk_start", "path": str(mapped_root)})

            for dirpath, dirnames, filenames in os.walk(mapped_root):
                for name in filenames:
                    s = Path(dirpath) / name

                    if should_exclude(s, exclude):
                        logger.write({"event": "skip", "path": str(s)})
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

    # manifest kaydet
    with (snapshot / "manifest.json").open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    logger.write({"event": "done", "snapshot": str(snapshot), "entry_count": len(manifest["entries"])})
    print("✔ Snapshot oluşturuldu:", snapshot)


# ----------------------------
# Config
# ----------------------------

def load_config(path: Path) -> Tuple[Path, List[Path], List[str], bool, int]:
    cfg = json.loads(path.read_text(encoding="utf-8"))

    repo = Path(cfg["repo_path"]).expanduser()
    sources = [Path(s["path"]).expanduser() for s in cfg.get("sources", [])]

    exclude: List[str] = []
    for s in cfg.get("sources", []):
        exclude.extend(s.get("exclude", []))

    use_vss = bool(cfg.get("use_vss", False))
    max_retries = int(cfg.get("max_retries", 3))

    return repo, sources, exclude, use_vss, max_retries


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

    ap_r = sub.add_parser("restore", help="Snapshot geri yükle")
    ap_r.add_argument("--repo", required=True)
    ap_r.add_argument("--snapshot", required=True, help="snapshot id veya latest")
    ap_r.add_argument("--to", required=True, help="hedef klasör")

    ap_v = sub.add_parser("verify", help="Bütünlük kontrolü")
    ap_v.add_argument("--repo", required=True)
    ap_v.add_argument("--snapshot", required=True, help="snapshot id veya latest")

    args = ap.parse_args()

    if args.cmd == "backup":
        repo, sources, exclude, use_vss, max_r = load_config(Path(args.config))
        backup(repo, sources, exclude, use_vss, max_r)

    elif args.cmd == "list":
        snaps = list_snapshots(Path(args.repo))
        for s in snaps:
            print(s)

    elif args.cmd == "restore":
        restore(Path(args.repo), args.snapshot, Path(args.to))
        print("✅ Restore tamamlandı.")

    elif args.cmd == "verify":
        verify(Path(args.repo), args.snapshot)

    else:
        ap.print_help()


if __name__ == "__main__":
    main()
