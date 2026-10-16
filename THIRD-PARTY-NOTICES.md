# Third-party components

The distribution includes dynamically linked Qt for Python / PySide6 Essentials and
Shiboken6 (LGPLv3/GPLv3/commercial), CTranslate2 (MIT), SentencePiece (Apache-2.0),
NumPy (BSD), python-mss (MIT), HTTPX and dependencies (BSD/MIT/MPL-2.0 as applicable),
Pillow (HPND), Python-UIAutomation-for-Windows (Apache-2.0), comtypes (MIT),
PyWinRT (MIT), and the Python runtime (PSF). Original license texts included by
installed distributions are retained in the application package and `licenses/`.

The native caption integration uses Frida (wxWindows Library Licence 3.1) to read
version-gated subtitle inputs and send translated temporary copies to the original
renderer. The original scheduled samples and installed Apple TV files are preserved.

Qt libraries in `_internal/PySide6/` remain replaceable dynamic libraries.
Qt source: https://code.qt.io/cgit/pyside/pyside-setup.git/
Qt licensing: https://www.qt.io/licensing/open-source-lgpl-obligations

The bundled English → Chinese model is Argos en_zh 1.9, derived from OPUS-MT
(CC BY 4.0). See `MODEL-ATTRIBUTION.md` for authorship. The application uses the
model locally through CTranslate2; it does not run an Argos server.

This is an independent experimental tool and is not affiliated with Apple.
