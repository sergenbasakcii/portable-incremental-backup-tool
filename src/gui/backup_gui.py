# -*- coding: utf-8 -*-
import sys
import os
import threading
from pathlib import Path

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent.parent
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


# ----------------- Log emitter -----------------

class LogEmitter(QObject):
    message = pyqtSignal(str)


# ----------------- Main Window -----------------

class BackupRestoreApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Portable Incremental Backup Tool - GUI (Sergen Başakcı)")
        self.resize(1100, 650)

        self.log_emitter = LogEmitter()
        self.log_emitter.message.connect(self.append_log)

        self._build_ui()

    # ---------------- UI ----------------

    def _build_ui(self):
        tabs = QTabWidget()

        # ---------- BACKUP TAB ----------
        backup_tab = QWidget()
        backup_layout = QVBoxLayout()

        self.sources_list = QListWidget()

        src_btns = QHBoxLayout()
        btn_add = QPushButton("Kaynak Klasör Ekle")
        btn_del = QPushButton("Seçili Kaynağı Sil")
        btn_add.clicked.connect(self.add_source)
        btn_del.clicked.connect(self.remove_source)
        src_btns.addWidget(btn_add)
        src_btns.addWidget(btn_del)

        repo_layout = QHBoxLayout()
        self.repo_edit = QLineEdit()
        btn_repo = QPushButton("Repo Seç")
        btn_repo.clicked.connect(self.select_repo)
        repo_layout.addWidget(QLabel("Repo:"))
        repo_layout.addWidget(self.repo_edit)
        repo_layout.addWidget(btn_repo)

        mode_layout = QHBoxLayout()
        self.rb_exclude = QRadioButton("Exclude")
        self.rb_include = QRadioButton("Include")
        self.rb_exclude.setChecked(True)
        mode_layout.addWidget(QLabel("Filtre Modu:"))
        mode_layout.addWidget(self.rb_exclude)
        mode_layout.addWidget(self.rb_include)
        mode_layout.addStretch()

        pat_layout = QHBoxLayout()
        self.patterns_edit = QLineEdit("*.tmp, *.log")
        pat_layout.addWidget(QLabel("Pattern:"))
        pat_layout.addWidget(self.patterns_edit)

        self.chk_vss = QCheckBox("Windows VSS Kullan")

        self.btn_backup = QPushButton("Yedekleme Başlat")
        self.btn_backup.clicked.connect(self.start_backup)

        backup_layout.addWidget(QLabel("Kaynaklar"))
        backup_layout.addWidget(self.sources_list)
        backup_layout.addLayout(src_btns)
        backup_layout.addLayout(repo_layout)
        backup_layout.addLayout(mode_layout)
        backup_layout.addLayout(pat_layout)
        backup_layout.addWidget(self.chk_vss)
        backup_layout.addWidget(self.btn_backup)
        backup_layout.addStretch()

        backup_tab.setLayout(backup_layout)

        # ---------- RESTORE TAB ----------
        restore_tab = QWidget()
        restore_layout = QVBoxLayout()

        repo_r = QHBoxLayout()
        self.restore_repo = QLineEdit()
        btn_r = QPushButton("Repo Seç")
        btn_r.clicked.connect(self.select_restore_repo)
        repo_r.addWidget(QLabel("Repo:"))
        repo_r.addWidget(self.restore_repo)
        repo_r.addWidget(btn_r)

        self.btn_list = QPushButton("Snapshot Listele")
        self.btn_list.clicked.connect(self.load_snapshots)

        self.snapshot_tree = QTreeWidget()
        self.snapshot_tree.setHeaderLabels(["Snapshot (+)"])
        self.snapshot_tree.itemSelectionChanged.connect(self.snapshot_selected)

        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderLabels(["Dosya / Klasör", "Boyut (GB)"])
        self.file_tree.setColumnWidth(0, 520)

        split = QHBoxLayout()
        split.addWidget(self.snapshot_tree, 1)
        split.addWidget(self.file_tree, 2)

        tgt_layout = QHBoxLayout()
        self.restore_target = QLineEdit()
        btn_tgt = QPushButton("Hedef Seç")
        btn_tgt.clicked.connect(self.select_restore_target)
        tgt_layout.addWidget(QLabel("Hedef:"))
        tgt_layout.addWidget(self.restore_target)
        tgt_layout.addWidget(btn_tgt)

        btns = QHBoxLayout()
        btn_full = QPushButton("TAM Restore")
        btn_file = QPushButton("Tek Dosya Restore")
        btn_full.clicked.connect(self.restore_full)
        btn_file.clicked.connect(self.restore_file)
        btns.addWidget(btn_full)
        btns.addWidget(btn_file)

        restore_layout.addLayout(repo_r)
        restore_layout.addWidget(self.btn_list)
        restore_layout.addLayout(split)
        restore_layout.addLayout(tgt_layout)
        restore_layout.addLayout(btns)
        restore_layout.addStretch()

        restore_tab.setLayout(restore_layout)

        # ---------- LOG ----------
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)

        main = QWidget()
        lay = QVBoxLayout()
        lay.addWidget(tabs)
        lay.addWidget(QLabel("Log"))
        lay.addWidget(self.log_output)

        tabs.addTab(backup_tab, "Backup")
        tabs.addTab(restore_tab, "Restore")

        main.setLayout(lay)
        self.setCentralWidget(main)

    # ---------------- Helpers ----------------

    def append_log(self, txt):
        if txt:
            self.log_output.append(txt)
            self.log_output.ensureCursorVisible()

    def add_source(self):
        d = QFileDialog.getExistingDirectory(self, "Kaynak Seç")
        if d:
            self.sources_list.addItem(d)

    def remove_source(self):
        for i in self.sources_list.selectedItems():
            self.sources_list.takeItem(self.sources_list.row(i))

    def select_repo(self):
        d = QFileDialog.getExistingDirectory(self, "Repo Seç")
        if d:
            self.repo_edit.setText(d)
            self.restore_repo.setText(d)

    def select_restore_repo(self):
        d = QFileDialog.getExistingDirectory(self, "Repo Seç")
        if d:
            self.restore_repo.setText(d)

    def select_restore_target(self):
        d = QFileDialog.getExistingDirectory(self, "Hedef Seç")
        if d:
            self.restore_target.setText(d)

    # ---------------- Backup ----------------

    def start_backup(self):
        repo = self.repo_edit.text().strip()
        sources = [self.sources_list.item(i).text()
                   for i in range(self.sources_list.count())]

        if not repo or not sources:
            self.append_log("❌ Repo veya kaynak eksik")
            return

        patterns = [x.strip() for x in self.patterns_edit.text().split(",") if x.strip()]
        mode = "exclude" if self.rb_exclude.isChecked() else "include"
        vss = self.chk_vss.isChecked()

        self.append_log("🚀 Yedekleme başlatıldı")

        th = threading.Thread(
            target=self._run_backup,
            args=(repo, sources, patterns, mode, vss),
            daemon=True
        )
        th.start()

    def _run_backup(self, repo, sources, patterns, mode, vss):
        class Out:
            def write(_, s):
                s = s.strip()
                if s:
                    self.log_emitter.message.emit(s)
            def flush(_): pass

        old = sys.stdout
        sys.stdout = Out()
        try:
            backup(Path(repo), [Path(s) for s in sources],
                   patterns, mode, vss, 3)
            self.log_emitter.message.emit("✅ Yedekleme tamamlandı")
        except Exception as e:
            self.log_emitter.message.emit(f"❌ Hata: {e}")
        finally:
            sys.stdout = old

    # ---------------- Restore ----------------

    def load_snapshots(self):
        self.snapshot_tree.clear()
        self.file_tree.clear()

        repo = Path(self.restore_repo.text().strip())
        for s in list_snapshots(repo):
            it = QTreeWidgetItem([s])
            it.setData(0, Qt.ItemDataRole.UserRole, s)
            it.addChild(QTreeWidgetItem(["(+)"]))
            self.snapshot_tree.addTopLevelItem(it)

    def snapshot_selected(self):
        items = self.snapshot_tree.selectedItems()
        if not items:
            return
        snap = items[0].data(0, Qt.ItemDataRole.UserRole)
        self.load_files(snap)

    def load_files(self, snap):
        self.file_tree.clear()
        root = Path(self.restore_repo.text()) / "snapshots" / snap / "files"

        root_item = QTreeWidgetItem([snap])
        self.file_tree.addTopLevelItem(root_item)
        node_map = {root: root_item}

        for dp, dns, fns in os.walk(root):
            dp = Path(dp)
            parent = node_map.get(dp)
            if not parent:
                continue

            for d in dns:
                p = dp / d
                it = QTreeWidgetItem([d, ""])
                it.setData(0, Qt.ItemDataRole.UserRole,
                           str(p.relative_to(root)))
                parent.addChild(it)
                node_map[p] = it

            for f in fns:
                p = dp / f
                gb = p.stat().st_size / (1024 ** 3)
                it = QTreeWidgetItem([f, f"{gb:.3f}"])
                it.setData(0, Qt.ItemDataRole.UserRole,
                           str(p.relative_to(root)))
                parent.addChild(it)

    def restore_full(self):
        restore_full_snapshot(
            Path(self.restore_repo.text()),
            self.snapshot_tree.selectedItems()[0].text(0),
            Path(self.restore_target.text())
        )
        self.append_log("✅ TAM restore tamamlandı")

    def restore_file(self):
        item = self.file_tree.selectedItems()
        if not item:
            return
        rel = item[0].data(0, Qt.ItemDataRole.UserRole)
        restore_single_file(
            Path(self.restore_repo.text()),
            self.snapshot_tree.selectedItems()[0].text(0),
            rel,
            Path(self.restore_target.text())
        )
        self.append_log("✅ Tek dosya restore edildi")


# ---------------- Main ----------------

def main():
    app = QApplication(sys.argv)
    w = BackupRestoreApp()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
