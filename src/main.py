# -*- coding: utf-8 -*-
import sys
import traceback
from pathlib import Path

def show_error(title, message):
    """
    Hata oluşursa Windows mesaj kutusu gösterir.
    Böylece --noconsole modunda bile hatayı görebilirsiniz.
    """
    try:
        import ctypes
        # 0x10 = Critical Icon
        ctypes.windll.user32.MessageBoxW(0, str(message), str(title), 0x10)
    except:
        # Eğer Windows dışı bir sistemse veya ctypes çalışmazsa
        print(f"[{title}] {message}", file=sys.stderr)

def main():
    """
    Uygulama Başlatıcı (Launcher)
    """
    try:
        # 1. Yol Ayarlaması (EXE vs Python Script)
        if getattr(sys, 'frozen', False):
            project_root = Path(sys._MEIPASS)
        else:
            current_dir = Path(__file__).resolve().parent  # src
            project_root = current_dir.parent              # proje kökü (yedekleme)

        root_str = str(project_root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)


        from src.gui.backup_gui import main as start_gui
        start_gui()

    except Exception as e:

        error_msg = traceback.format_exc()
        show_error("Yedekleme Yazılımı Başlatma Hatası", error_msg)
        sys.exit(1)

if __name__ == "__main__":
    main()
