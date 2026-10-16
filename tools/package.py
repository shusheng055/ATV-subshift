from pathlib import Path
import argparse
import hashlib
import json
import zipfile

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--folder', type=Path, default=root / 'dist' / 'ATV subshift')
parser.add_argument('--output', type=Path, default=root / 'dist' / 'ATV-subshift-1.0.0-win64.zip')
args = parser.parse_args()
folder, archive = args.folder.resolve(), args.output.resolve()
archive.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for path in sorted(folder.rglob('*')):
        if path.is_file():
            z.write(path, path.relative_to(folder.parent))
with zipfile.ZipFile(archive) as z:
    bad = z.testzip()
    if bad:
        raise RuntimeError('Archive verification failed: ' + bad)
manifest = {'file': archive.name, 'bytes': archive.stat().st_size,
            'sha256': hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest(),
            'model_included': True, 'first_run_download': False}
archive.with_suffix('.json').write_text(json.dumps(manifest, indent=2), 'utf-8')
print(json.dumps(manifest, indent=2))
