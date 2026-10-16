import sys


def main():
    if sys.argv[1:] == ['--pacing-check-worker']:
        # Bounded idle target for the explicitly invoked packaged-runtime test.
        # It never opens a window, loads settings, or attaches to Apple TV.
        import time
        time.sleep(20)
        return 0
    if len(sys.argv) >= 3 and sys.argv[1] == '--native-check':
        import argparse
        from pathlib import Path
        from subtitle_app.acceptance import run
        parser = argparse.ArgumentParser()
        parser.add_argument('output', type=Path)
        parser.add_argument('--seconds', type=int, default=90)
        parser.add_argument('--min-cues', type=int, default=20)
        args = parser.parse_args(sys.argv[2:])
        return run(args.output.resolve(), max(15, min(900, args.seconds)), max(1, args.min_cues))
    if len(sys.argv) == 3 and sys.argv[1] == "--self-check":
        from pathlib import Path
        import json
        import traceback
        output = Path(sys.argv[2]).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"stage": "bootstrap"}), "utf-8")
        try:
            import os
            import tempfile
            with tempfile.TemporaryDirectory() as profile:
                os.environ['LOCALAPPDATA'] = profile
                from subtitle_app.selfcheck import run
                return run(output)
        except Exception:
            output.write_text(json.dumps({"passed": False, "traceback": traceback.format_exc()}, ensure_ascii=False), "utf-8")
            return 1
    from PySide6.QtWidgets import QApplication, QMessageBox
    from subtitle_app.windows import InstanceLock
    from subtitle_app.ui import MainWindow, app_icon

    app = QApplication(sys.argv)
    app.setApplicationName("ATV subshift")
    app.setOrganizationName("LocalTools")
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")
    lock = InstanceLock()
    if lock.already_running:
        QMessageBox.information(None, "ATV subshift", "应用已在运行，请切换到已打开的窗口。")
        lock.close()
        return 0
    window = MainWindow()
    window.show()
    result = app.exec()
    lock.close()
    return result


if __name__ == "__main__":
    # Spawned model workers need the same runtime selection, without a GUI or lock.
    if getattr(sys, 'frozen', False):
        import ctypes
        from pathlib import Path
        ctypes.WinDLL(str(Path(sys._MEIPASS) / 'MSVCP140.dll'))
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
