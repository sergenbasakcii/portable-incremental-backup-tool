# -*- coding: utf-8 -*-
import sys
import os
import threading
from pathlib import Path


current_dir = Path(__file__).resolve().parent  # .../src/gui
project_root = current_dir.parent.parent       # .../ (proje kökü)
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QPushButton, QVBoxLayout, QHBoxLayout,
    QFileDialog, QLabel, QTextEdit, QLineEdit, QCheckBox, QListWidget, QTabWidget,
    QRadioButton, QTreeWidget, QTreeWidgetItem, QMessageBox
)
from PyQt6.QtCore import Qt, QObject, pyqtSignal

from src.engine.backup_engine import (
    backup, list_snapshots, restore_full_snapshot, restore_single_file
)


# ----------------- Log emitter (thread-safe) -----------------

class LogEmitter(QObject):
    message = pyqtSignal(str)


# ----------------- Ana Pencere -----------------

class BackupRestoreApp(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Portable Incremental Backup Tool - GUI (Sergen Başakcı)")
        self.resize(1100, 650)

        self.log_emitter = LogEmitter()
        self.log_emitter.message.connect(self.append_log)

        self._build_ui()

    # --------- UI Kurulum ---------

    def _build_ui(self):
        tabs = QTabWidget()

        # ------------------ BACKUP TAB ------------------
        backup_tab = QWidget()
        backup_layout = QVBoxLayout()

        # Source list
        self.sources_list = QListWidget()
        src_btn_layout = QHBoxLayout()
        self.btn_add_source = QPushButton("Kaynak Klasör Ekle")
        self.btn_remove_source = QPushButton("Seçili Kaynağı Sil")
        self.btn_add_source.clicked.connect(self.add_source_folder)
        self.btn_remove_source.clicked.connect(self.remove_selected_source)
        src_btn_layout.addWidget(self.btn_add_source)
        src_btn_layout.addWidget(self.btn_remove_source)

        # Repo
        repo_layout = QHBoxLayout()
        self.repo_edit = QLineEdit()
        self.btn_select_repo = QPushButton("Repo Klasörü Seç")
        self.btn_select_repo.clicked.connect(self.select_repo_folder)
        repo_layout.addWidget(QLabel("Repo Klasörü:"))
        repo_layout.addWidget(self.repo_edit)
        repo_layout.addWidget(self.btn_select_repo)

        # Include/Exclude mode (Radio)
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Filtre modu:"))
        self.rb_exclude = QRadioButton("Exclude (eşleşenleri alma)")
        self.rb_include = QRadioButton("Include (sadece eşleşenleri al)")
        self.rb_exclude.setChecked(True)
        mode_layout.addWidget(self.rb_exclude)
        mode_layout.addWidget(self.rb_include)
        mode_layout.addStretch()

        # Patterns
        pat_layout = QHBoxLayout()
        self.patterns_edit = QLineEdit("*.tmp, *.log")
        pat_layout.addWidget(QLabel("Pattern (virgülle):"))
        pat_layout.addWidget(self.patterns_edit)

        # VSS
        self.chk_vss = QCheckBox("Windows VSS kullan (Shadow Copy)")

        # Backup start
        self.btn_start_backup = QPushButton("Yedekleme Başlat")
        self.btn_start_backup.clicked.connect(self.start_backup)

        backup_layout.addWidget(QLabel("Kaynak Klasörler:"))
        backup_layout.addWidget(self.sources_list)
        backup_layout.addLayout(src_btn_layout)
        backup_layout.addSpacing(10)
        backup_layout.addLayout(repo_layout)
        backup_layout.addLayout(mode_layout)
        backup_layout.addLayout(pat_layout)
        backup_layout.addWidget(self.chk_vss)
        backup_layout.addWidget(self.btn_start_backup)
        backup_layout.addStretch()
        backup_tab.setLayout(backup_layout)

        # ------------------ RESTORE TAB ------------------
        restore_tab = QWidget()
        restore_layout = QVBoxLayout()

        # Repo (restore için)
        r_repo_layout = QHBoxLayout()
        self.restore_repo_edit = QLineEdit()
        self.btn_restore_repo = QPushButton("Repo Klasörü Seç")
        self.btn_restore_repo.clicked.connect(self.select_restore_repo)
        r_repo_layout.addWidget(QLabel("Repo Klasörü:"))
        r_repo_layout.addWidget(self.restore_repo_edit)
        r_repo_layout.addWidget(self.btn_restore_repo)

        # Sol: Snapshot list (+) -> QTreeWidget
        self.snapshot_tree = QTreeWidget()
        self.snapshot_tree.setHeaderLabels(["Snapshot (+)"])
        self.snapshot_tree.itemSelectionChanged.connect(self.on_snapshot_selected)

        self.btn_load_snapshots = QPushButton("Snapshot Listele")
        self.btn_load_snapshots.clicked.connect(self.load_snapshots)

        # Sağ: Seçilen snapshot içindeki dosyalar
        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderLabels(["Dosya / Klasör", "Boyut"])
        self.file_tree.setColumnWidth(0, 520)

        # Target folder
        target_layout = QHBoxLayout()
        self.restore_target_edit = QLineEdit()
        self.btn_restore_target = QPushButton("Hedef Klasör Seç")
        self.btn_restore_target.clicked.connect(self.select_restore_target)
        target_layout.addWidget(QLabel("Geri Yükleme Hedef Klasörü:"))
        target_layout.addWidget(self.restore_target_edit)
        target_layout.addWidget(self.btn_restore_target)

        # Restore buttons
        btns_layout = QHBoxLayout()
        self.btn_restore_full = QPushButton("Seçili Snapshot'ı TAM Geri Yükle")
        self.btn_restore_file = QPushButton("Seçili DOSYAYI Geri Yükle (Tek Dosya)")
        self.btn_restore_full.clicked.connect(self.start_restore_full)
        self.btn_restore_file.clicked.connect(self.start_restore_file)
        btns_layout.addWidget(self.btn_restore_full)
        btns_layout.addWidget(self.btn_restore_file)

        # Split layout (sol snapshot + sağ file tree)
        split = QHBoxLayout()
        split.addWidget(self.snapshot_tree, 1)
        split.addWidget(self.file_tree, 2)

        restore_layout.addLayout(r_repo_layout)
        restore_layout.addWidget(self.btn_load_snapshots)
        restore_layout.addLayout(split)
        restore_layout.addLayout(target_layout)
        restore_layout.addLayout(btns_layout)
        restore_layout.addStretch()
        restore_tab.setLayout(restore_layout)

        # ------------------ ORTAK LOG ------------------
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)

        main_widget = QWidget()
        main_layout = QVBoxLayout()
        tabs.addTab(backup_tab, "Backup")
        tabs.addTab(restore_tab, "Restore")

        main_layout.addWidget(tabs)
        main_layout.addWidget(QLabel("Log:"))
        main_layout.addWidget(self.log_output)

        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

    # --------- Genel Log ---------

    def append_log(self, text: str):
        text = (text or "").rstrip()
        if not text:
            return
        self.log_output.append(text)
        self.log_output.ensureCursorVisible()

    def msg(self, title: str, text: str):
        QMessageBox.information(self, title, text)

    # --------- Backup kısmı ---------

    def add_source_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Kaynak klasör seç")
        if folder:
            self.sources_list.addItem(folder)

    def remove_selected_source(self):
        for item in self.sources_list.selectedItems():
            row = self.sources_list.row(item)
            self.sources_list.takeItem(row)

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
        self.rb_exclude.setEnabled(enabled)
        self.rb_include.setEnabled(enabled)
        self.patterns_edit.setEnabled(enabled)

    def start_backup(self):
        sources = [self.sources_list.item(i).text() for i in range(self.sources_list.count())]
        repo = self.repo_edit.text().strip()

        if not sources:
            self.append_log("❌ En az bir kaynak klasör seçmelisin.")
            return
        if not repo:
            self.append_log("❌ Repo klasörü seçilmedi.")
            return

        patterns = [x.strip() for x in self.patterns_edit.text().split(",") if x.strip()]
        mode = "exclude" if self.rb_exclude.isChecked() else "include"
        use_vss = self.chk_vss.isChecked()
        max_retries = 3

        self.append_log("🚀 Yedekleme başlıyor...")
        self.append_log(f"→ Kaynaklar: {sources}")
        self.append_log(f"→ Repo: {repo}")
        self.append_log(f"→ Mode: {mode}")
        self.append_log(f"→ Patterns: {patterns}")
        self.append_log(f"→ VSS: {use_vss}")

        self.set_backup_controls_enabled(False)

        th = threading.Thread(
            target=self._run_backup_thread,
            args=(repo, sources, patterns, mode, use_vss, max_retries),
            daemon=True
        )
        th.start()

    def _run_backup_thread(self, repo, sources, patterns, mode, use_vss, max_retries):
        repo_path = Path(repo)
        source_paths = [Path(s) for s in sources]

        class QtStdout:
            def write(inner_self, s):
                s = s.rstrip()
                if s:
                    self.log_emitter.message.emit(s)
            def flush(inner_self):
                pass

        old_stdout = sys.stdout
        sys.stdout = QtStdout()

        try:
            backup(repo_path, source_paths, patterns, mode, use_vss, max_retries)
            self.log_emitter.message.emit("✅ Yedekleme tamamlandı.")
        except Exception as e:
            self.log_emitter.message.emit(f"❌ Yedekleme hatası: {e}")
        finally:
            sys.stdout = old_stdout
            self.set_backup_controls_enabled(True)

    # --------- Restore kısmı ---------

    def select_restore_repo(self):
        folder = QFileDialog.getExistingDirectory(self, "Repo klasörü seç")
        if folder:
            self.restore_repo_edit.setText(folder)

    def load_snapshots(self):
        repo = self.restore_repo_edit.text().strip()
        if not repo:
            self.append_log("❌ Önce bir repo klasörü seç.")
            return

        repo_path = Path(repo)
        try:
            snaps = list_snapshots(repo_path)
        except Exception as e:
            self.append_log(f"❌ Snapshot listeleme hatası: {e}")
            return

        self.snapshot_tree.clear()
        self.file_tree.clear()

        if not snaps:
            self.append_log("ℹ️ Snapshot bulunamadı.")
            return

        for snap in snaps:
            item = QTreeWidgetItem([snap])
            # “+” görünmesi için dummy child ekliyoruz
            item.addChild(QTreeWidgetItem(["(+)"]))
            item.setData(0, Qt.ItemDataRole.UserRole, snap)
            self.snapshot_tree.addTopLevelItem(item)

        self.append_log(f"📁 {len(snaps)} snapshot listelendi. Birini seç.")

    def on_snapshot_selected(self):
        repo = self.restore_repo_edit.text().strip()
        if not repo:
            return
        items = self.snapshot_tree.selectedItems()
        if not items:
            return

        snap_item = items[0]
        snapshot_id = snap_item.data(0, Qt.ItemDataRole.UserRole)
        if not snapshot_id:
            return

        self.load_snapshot_files(repo, snapshot_id)

    def load_snapshot_files(self, repo: str, snapshot_id: str):
        """
        Sağ panelde snapshot içindeki files/ ağacını gösterir.
        Dosyaların relative path'i item data içine yazılır.
        """
        self.file_tree.clear()

        repo_path = Path(repo)
        files_root = repo_path / "snapshots" / snapshot_id / "files"

        if not files_root.exists():
            self.append_log("❌ Seçilen snapshot'ta files klasörü yok.")
            return

        root_item = QTreeWidgetItem([f"{snapshot_id} (files)"])
        root_item.setExpanded(True)
        root_item.setData(0, Qt.ItemDataRole.UserRole, "")  # root
        self.file_tree.addTopLevelItem(root_item)

        # Klasör->QTreeWidgetItem cache
        node_map = {files_root: root_item}

        for dirpath, dirnames, filenames in os.walk(files_root):
            dir_path = Path(dirpath)
            parent_item = node_map.get(dir_path)
            if parent_item is None:
                continue

            # Dizinleri ekle
            for d in sorted(dirnames):
                p = dir_path / d
                it = QTreeWidgetItem([d, ""])
                it.setData(0, Qt.ItemDataRole.UserRole, str(p.relative_to(files_root)).replace("\\", "/"))
                parent_item.addChild(it)
                node_map[p] = it

            # Dosyaları ekle
            for f in sorted(filenames):
                p = dir_path / f
                size = ""
                try:
                    size = str(p.stat().st_size)
                except Exception:
                    size = ""
                it = QTreeWidgetItem([f, size])
                it.setData(0, Qt.ItemDataRole.UserRole, str(p.relative_to(files_root)).replace("\\", "/"))
                parent_item.addChild(it)

        self.append_log(f"✅ Snapshot dosyaları yüklendi: {snapshot_id}")

    def select_restore_target(self):
        folder = QFileDialog.getExistingDirectory(self, "Geri yükleme hedef klasörü seç")
        if folder:
            self.restore_target_edit.setText(folder)

    def get_selected_snapshot(self) -> str | None:
        items = self.snapshot_tree.selectedItems()
        if not items:
            return None
        snapshot_id = items[0].data(0, Qt.ItemDataRole.UserRole)
        return snapshot_id

    def get_selected_file_relpath(self) -> str | None:
        """
        File tree’de seçilen item dosyaysa relative path döndürür.
        """
        items = self.file_tree.selectedItems()
        if not items:
            return None

        rel = items[0].data(0, Qt.ItemDataRole.UserRole)
        if rel is None:
            return None

        rel = str(rel).strip()
        if rel == "":
            return None  # root seçilmiş olabilir

        # Dosya mı? (boyut sütunu doluysa dosya kabul ediyoruz)
        is_file = bool(items[0].text(1).strip())
        return rel if is_file else None

    def start_restore_full(self):
        repo = self.restore_repo_edit.text().strip()
        target = self.restore_target_edit.text().strip()
        snapshot_id = self.get_selected_snapshot()

        if not repo:
            self.append_log("❌ Repo seçilmedi.")
            return
        if not snapshot_id:
            self.append_log("❌ Bir snapshot seçmelisin.")
            return
        if not target:
            self.append_log("❌ Hedef klasör seçmelisin.")
            return

        self.append_log(f"🔄 TAM Restore başlıyor → Snapshot: {snapshot_id} → Target: {target}")

        th = threading.Thread(
            target=self._run_restore_full_thread,
            args=(repo, snapshot_id, target),
            daemon=True
        )
        th.start()

    def _run_restore_full_thread(self, repo: str, snapshot_id: str, target: str):
        try:
            restore_full_snapshot(Path(repo), snapshot_id, Path(target))
            self.log_emitter.message.emit("✅ TAM restore tamamlandı.")
        except Exception as e:
            self.log_emitter.message.emit(f"❌ Restore hatası: {e}")

    def start_restore_file(self):
        repo = self.restore_repo_edit.text().strip()
        target = self.restore_target_edit.text().strip()
        snapshot_id = self.get_selected_snapshot()
        rel = self.get_selected_file_relpath()

        if not repo:
            self.append_log("❌ Repo seçilmedi.")
            return
        if not snapshot_id:
            self.append_log("❌ Bir snapshot seçmelisin.")
            return
        if not target:
            self.append_log("❌ Hedef klasör seçmelisin.")
            return
        if not rel:
            self.append_log("❌ Sağdaki listeden bir DOSYA seçmelisin (klasör olmaz).")
            return

        self.append_log(f"🔄 Tek dosya restore → Snapshot: {snapshot_id} → File: {rel} → Target: {target}")

        th = threading.Thread(
            target=self._run_restore_file_thread,
            args=(repo, snapshot_id, rel, target),
            daemon=True
        )
        th.start()

    def _run_restore_file_thread(self, repo: str, snapshot_id: str, rel: str, target: str):
        try:
            out = restore_single_file(Path(repo), snapshot_id, rel, Path(target))
            self.log_emitter.message.emit(f"✅ Tek dosya restore tamamlandı: {out}")
        except Exception as e:
            self.log_emitter.message.emit(f"❌ Tek dosya restore hatası: {e}")


# ----------------- Main -----------------

def main():
    app = QApplication(sys.argv)
    win = BackupRestoreApp()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
