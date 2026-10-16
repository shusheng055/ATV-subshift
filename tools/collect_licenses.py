from importlib.metadata import distributions
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
destination = root / 'licenses'
destination.mkdir(exist_ok=True)
for distribution in distributions():
    name = distribution.metadata['Name']
    if name.lower() in {'pip', 'setuptools', 'pyinstaller', 'altgraph', 'pyinstaller-hooks-contrib', 'pefile', 'pywin32-ctypes'}:
        continue
    for file in distribution.files or []:
        if any(part.lower().startswith(('license', 'copying', 'copyright', 'notice')) for part in file.parts):
            source = Path(distribution.locate_file(file))
            if source.is_file() and source.suffix.lower() not in {".py", ".pyc", ".pyo"}:
                target = destination / name / Path(*file.parts[-2:])
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
print('License files collected:', sum(p.is_file() for p in destination.rglob('*')))
