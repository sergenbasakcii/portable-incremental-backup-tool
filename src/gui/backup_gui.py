# -*- coding: utf-8 -*-
"""
Backup & Restore GUI (PyQt6)
Repo yapısı (önerilen):
  src/
    engine/backup_engine.py
    gui/backup_gui.py

Çalıştırma:
  python src/gui/backup_gui.py
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import List

# src/ klasörünü import path'e ekle (gui klasöründen engine import edebilmek için)
SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QPushButton, QVBoxLayout, QHBoxLayout,
    QFileDialog, QLabel, QTextEdit, QLineEdit, QCheckBox, QListWidget, QTabWidget
)
from PyQt6.QtCore import QObject, pyqtSignal

# ✅ Modüler import (engine)
from engine.backup_engine import backup, list_snapshots, restore


class LogEmitter(QObject):
    message = pyqtSignal(str)


class BackupRestoreApp(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Yedekleme Yazılımı - Backup & Restore GUI (Sergen Başakcı)")
        self.resize(900, 650)

        self.log_emitter = LogEmitter()
        self.log_emitter.message.connect(self.append_log)

        self._build_ui()

    # ---------------- UI ----------------

    def _build_ui(self):
        tabs = QTabWidget()

        # -------- BACKUP TAB --------
        backup_tab = QWidget()
        backup_layout = QVBoxLayout()

        self.sources_list = QListWidget()

        src_btn_layout = QHBoxLayout()
        self.btn_add_source = QPushButton("Kaynak Klasör Ekle")
        self.btn_remove_source = QPushButton("Seçili Kaynağı Sil")
        self.btn_add_source.clicked.connect(self.add_source_folder)
        self.btn_remove_source.clicked.connect(self.remove_selected_source)
        src_btn_layout.addWidget(self.btn_add_source)
        src_btn_layout.addWidget(self.btn_remove_source)

        repo_layout = QHBoxLayout()
        self.repo_edit = QLineEdit()
        self.btn_select_repo = QPushButton("Repo Klasörü Seç")
        self.btn_select_repo.clicked.connect(self.select_repo_folder)
        repo_layout.addWidget(QLabel("Repo Klasörü:"))
        repo_layout.addWidget(self.repo_edit)
        repo_layout.addWidget(self.btn_select_repo)

        excl_layout = QHBoxLayout()
        self.exclude_edit = QLineEdit("*.tmp, *.log")
        excl_layout.addWidget(QLabel("Exclude pattern (virgülle):"))
        excl_layout.addWidget(self.exclude_edit)

        self.chk_vss = QCheckBox("Windows VSS kullan (Shadow Copy)")

        self.btn_start_backup = QPushButton("Yedekleme Başlat")
        self.btn_start_backup.clicked.connect(self.start_backup)

        backup_layout.addWidget(QLabel("Kaynak Klasörler:"))
        backup_layout.addWidget(self.sources_list)
        backup_layout.addLayout(src_btn_layout)
        backup_layout.addSpacing(10)
        backup_layout.addLayout(repo_layout)
        backup_layout.addLayout(excl_layout)
        backup_layout.addWidget(self.chk_vss)
        backup_layout.addWidget(self.btn_start_backup)
        backup_layout.addStretch()
        backup_tab.setLayout(backup_layout)

        # -------- RESTORE TAB --------
        restore_tab = QWidget()
        restore_layout = QVBoxLayout()

        r_repo_layout = QHBoxLayout()
        self.restore_repo_edit = QLineEdit()
        self.btn_restore_repo = QPushButton("Repo Klasörü Seç")
        self.btn_restore_repo.clicked.connect(self.select_restore_repo)
        r_repo_layout.addWidget(QLabel("Repo Klasörü:"))
        r_repo_layout.addWidget(self.restore_repo_edit)
        r_repo_layout.addWidget(self.btn_restore_repo)

        self.snapshots_list = QListWidget()
        self.btn_load_snapshots = QPushButton("Snapshot Listele")
        self.btn_load_snapshots.clicked.connect(self.load_snapshots)

        target_layout = QHBoxLayout()
        self.restore_target_edit = QLineEdit()
        self.btn_restore_target = QPushButton("Hedef Klasör Seç")
        self.btn_restore_target.clicked.connect(self.select_restore_target)
        target_layout.addWidget(QLabel("Geri Yükleme Hedef Klasörü:"))
        target_layout.addWidget(self.restore_target_edit)
        target_layout.addWidget(self.btn_restore_target)

        self.btn_start_restore = QPushButton("Seçili Snapshot'ı Geri Yükle")
        self.btn_start_restore.clicked.connect(self.start_restore)

        restore_layout.addLayout(r_repo_layout)
        restore_layout.addWidget(QLabel("Snapshot Listesi:"))
        restore_layout.addWidget(self.snapshots_list)
        restore_layout.addWidget(self.btn_load_snapshots)
        restore_layout.addLayout(target_layout)
        restore_layout.addWidget(self.btn_start_restore)
        restore_layout.addStretch()
        restore_tab.setLayout(restore_layout)

        # -------- ORTAK LOG --------
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)

        tabs.addTab(backup_tab, "Backup")
        tabs.addTab(restore_tab, "Restore")

        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_layout.addWidget(tabs)
        main_layout.addWidget(QLabel("Log:"))
        main_layout.addWidget(self.log_output)
        main_widget.setLayout(main_layout)

        self.setCentralWidget(main_widget)

    # ---------------- LOG ----------------

    def append_log(self, text: str):
        text = (text or "").rstrip()
        if not text:
            return
        self.log_output.append(text)
        self.log_output.ensureCursorVisible()

    def log(self, msg: str):
        self.log_emitter.message.emit(msg)

    # ---------------- BACKUP ----------------

    def add_source_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Kaynak klasör seç")
        if folder:
            self.sources_list.addItem(folder)

    def remove_selected_source(self):
        for item in self.sources_list.selectedItems():
            self.sources_list.takeItem(self.sources_list.row(item))

    def select_repo_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Repo klasörü seç")
        if folder:
            self.repo_edit.setText(folder)
            self.restore_repo_edit.setText(folder)

    def set_backup_controls_enabled(self, enabled: bool):
        self.btn_add_source.setEnabled(enabled)
        self.btn_remove_source.setEnabled(enabled)
        self.btn_select_repo.setEnabled(enabled)
        self.btn_start_backup.setEnabled(enabled)
        self.chk_vss.setEnabled(enabled)

    def start_backup(self):
        sources = [self.sources_list.item(i).text() for i in range(self.sources_list.count())]
        repo = self.repo_edit.text().strip()

        if not sources:
            self.log("❌ En az bir kaynak klasör seçmelisin.")
            return
        if not repo:
            self.log("❌ Repo klasörü seçilmedi.")
            return

        excludes = [x.strip() for x in self.exclude_edit.text().split(",") if x.strip()]
        use_vss = self.chk_vss.isChecked()

        self.log("🚀 Yedekleme başlıyor...")
        self.log(f"→ Kaynaklar: {sources}")
        self.log(f"→ Repo: {repo}")
        self.log(f"→ Exclude: {excludes}")
        self.log(f"→ VSS: {use_vss}")

        self.set_backup_controls_enabled(False)

        th = threading.Thread(
            target=self._run_backup_thread,
            args=(repo, sources, excludes, use_vss),
            daemon=True
        )
        th.start()

    def _run_backup_thread(self, repo: str, sources: List[str], excludes: List[str], use_vss: bool):
        repo_path = Path(repo)
        source_paths = [Path(s) for s in sources]
        max_retries = 3

        # stdout yakalama (engine print() çıktıları log'a düşsün)
        class QtStdout:
            def write(inner_self, s):
                s = (s or "").rstrip()
                if s:
                    self.log_emitter.message.emit(s)

            def flush(inner_self):
                pass

        old_stdout = sys.stdout
        sys.stdout = QtStdout()

        try:
            backup(repo_path, source_paths, excludes, use_vss, max_retries)
            self.log_emitter.message.emit("✅ Yedekleme tamamlandı.")
        except Exception as e:
            self.log_emitter.message.emit(f"❌ Yedekleme hatası: {e}")
        finally:
            sys.stdout = old_stdout
            # UI'yi tekrar aktif et
            self.set_backup_controls_enabled(True)

    # ---------------- RESTORE ----------------

    def select_restore_repo(self):
        folder = QFileDialog.getExistingDirectory(self, "Repo klasörü seç")
        if folder:
            self.restore_repo_edit.setText(folder)

    def load_snapshots(self):
        repo = self.restore_repo_edit.text().strip()
        if not repo:
            self.log("❌ Önce bir repo klasörü seç.")
            return

        repo_path = Path(repo)
        try:
            snaps = list_snapshots(repo_path)
        except Exception as e:
            self.log(f"❌ Snapshot listeleme hatası: {e}")
            return

        self.snapshots_list.clear()
        if not snaps:
            self.log("ℹ️ Snapshot bulunamadı.")
            return

        for s in snaps:
            self.snapshots_list.addItem(s)

        self.log(f"📁 {len(snaps)} snapshot listelendi.")

    def select_restore_target(self):
        folder = QFileDialog.getExistingDirectory(self, "Geri yükleme hedef klasörü seç")
        if folder:
            self.restore_target_edit.setText(folder)

    def set_restore_controls_enabled(self, enabled: bool):
        self.btn_restore_repo.setEnabled(enabled)
        self.btn_load_snapshots.setEnabled(enabled)
        self.snapshots_list.setEnabled(enabled)
        self.btn_restore_target.setEnabled(enabled)
        self.btn_start_restore.setEnabled(enabled)

    def start_restore(self):
        repo = self.restore_repo_edit.text().strip()
        target = self.restore_target_edit.text().strip()
        selected_items = self.snapshots_list.selectedItems()

        if not repo:
            self.log("❌ Repo klasörü seçilmedi.")
            return
        if not selected_items:
            self.log("❌ Bir snapshot seçmelisin.")
            return
        if not target:
            self.log("❌ Geri yükleme hedef klasörü seçilmedi.")
            return

        snapshot_id = selected_items[0].text()

        self.log("🔄 Geri yükleme başlıyor...")
        self.log(f"→ Repo: {repo}")
        self.log(f"→ Snapshot: {snapshot_id}")
        self.log(f"→ Hedef: {target}")

        self.set_restore_controls_enabled(False)

        th = threading.Thread(
            target=self._run_restore_thread,
            args=(repo, snapshot_id, target),
            daemon=True
        )
        th.start()

    def _run_restore_thread(self, repo: str, snapshot_id: str, target: str):
        try:
            restore(Path(repo), snapshot_id, Path(target))
            self.log_emitter.message.emit("✅ Geri yükleme tamamlandı.")
        except Exception as e:
            self.log_emitter.message.emit(f"❌ Geri yükleme hatası: {e}")
        finally:
            self.set_restore_controls_enabled(True)


def main():
    app = QApplication(sys.argv)
    win = BackupRestoreApp()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
