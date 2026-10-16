# Build a portable directory; the model is bundled, never downloaded at runtime.
from pathlib import Path
import importlib.util
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH)
datas = [(str(root / 'models'), 'models'),
         (str(root / 'model-manifest.json'), '.'),
         (str(root / 'MODEL-ATTRIBUTION.md'), '.'),
         (str(root / 'README.zh-CN.md'), '.'),
         (str(root / 'MODEL-CATALOG.md'), '.'),
         (str(root / 'THIRD-PARTY-NOTICES.md'), '.'),
         (str(root / 'licenses'), 'licenses'),
         (str(root / 'assets'), 'assets'),
         (str(root / 'native'), 'native'),
         (str(root / 'LICENSE'), '.'),
         (str(root / 'RIGHTS-WAIVER.zh-CN.md'), '.'),
         (str(root / 'AI-GENERATED.md'), '.'),
         (str(root / 'RELEASE-NOTES.zh-CN.md'), '.'),
         (str(root / 'docs'), 'docs')]
binaries = []
hiddenimports = []
for package in ('uiautomation', 'winrt', 'ctranslate2', 'frida'):
    data, binary, hidden = collect_all(package)
    datas += data
    binaries += binary
    hiddenimports += hidden

a = Analysis([str(root / 'main.py')], pathex=[str(root)], binaries=binaries,
             datas=datas, hiddenimports=hiddenimports,
             excludes=['tkinter', 'matplotlib', 'torch', 'scipy', 'pandas', 'PySide6.QtWebEngineCore',
                       'PySide6.QtQuick', 'PySide6.QtQml', 'PySide6.QtMultimedia'], noarchive=False)
# PyWinRT and Qt ship different MSVC runtime revisions. Use Qt's newer compatible
# runtime everywhere so Windows never loads PyWinRT's older DLL ahead of Qt.
qt_dir = Path(importlib.util.find_spec('PySide6').origin).parent
msvcp = str(qt_dir / 'MSVCP140.dll')
a.binaries = [(target, msvcp if Path(target).name.lower() == 'msvcp140.dll' else source, kind)
              for target, source, kind in a.binaries]
a.binaries.append(('MSVCP140.dll', msvcp, 'BINARY'))
# Qt on Windows 11 uses the OS ICU shim (unversioned exports). A Poppler directory
# on this build host's PATH otherwise supplies an incompatible renamed ICU DLL.
# Never bundle the build host's unrelated Poppler ICU libraries into this app.
a.binaries = [(target, source, kind) for target, source, kind in a.binaries
              if Path(target).name.lower() not in {'icuuc.dll', 'icudt78.dll'}]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ATV subshift',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          version=str(root / 'version_info.txt'),
          console=os.environ.get('ATV_BUILD_CONSOLE') == '1', icon=str(root / 'assets' / 'app.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='ATV subshift')

