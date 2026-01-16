# -*- coding: utf-8 -*-
import sys
import traceback
from pathlib import Path

def show_error(title, msg):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, title, 0x10)
    except:
        print(msg, file=sys.stderr)

def main():
    try:
        if getattr(sys, "frozen", False):
            root = Path(sys._MEIPASS)
        else:
            root = Path(__file__).resolve().parent.parent

        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        from src.gui.backup_gui import main as gui_main
        gui_main()

    except Exception:
        show_error("Başlatma Hatası", traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    main()
