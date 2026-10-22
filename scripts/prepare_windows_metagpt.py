"""Build a local MetaGPT wheel with the unavailable LanceDB pin updated.

Run from the repository root after downloading the official 0.8.2 wheel:
python -m pip download --no-deps metagpt==0.8.2 --dest .environment-wheels
python scripts/prepare_windows_metagpt.py
No MetaGPT Python source is modified. The changed dependency is not used by
MediGraphRAG's Neo4j/FAISS retrieval path.
"""
import base64
import csv
import hashlib
import io
from pathlib import Path
import zipfile

folder = Path(__file__).resolve().parents[1] / '.environment-wheels'
source = folder / 'metagpt-0.8.2-py3-none-any.whl'
version = '0.8.2+medigraphrag.1'
old_info = 'metagpt-0.8.2.dist-info'
new_info = f'metagpt-{version}.dist-info'
target = folder / f'metagpt-{version}-py3-none-any.whl'
with zipfile.ZipFile(source) as archive:
    files = {name.replace(old_info, new_info): archive.read(name)
             for name in archive.namelist() if not name.endswith('/RECORD')}
metadata_key = f'{new_info}/METADATA'
metadata = files[metadata_key].decode('utf-8')
assert 'Requires-Dist: lancedb ==0.4.0' in metadata or 'Requires-Dist: lancedb==0.4.0' in metadata
metadata = metadata.replace('Version: 0.8.2\n', f'Version: {version}\n', 1)
metadata = metadata.replace('Requires-Dist: lancedb ==0.4.0', 'Requires-Dist: lancedb ==0.14.0')
metadata = metadata.replace('Requires-Dist: lancedb==0.4.0', 'Requires-Dist: lancedb==0.14.0')
files[metadata_key] = metadata.encode('utf-8')
record = io.StringIO(newline='')
writer = csv.writer(record, lineterminator='\n')
for name, data in files.items():
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
    writer.writerow([name, f'sha256={digest}', len(data)])
writer.writerow([f'{new_info}/RECORD', '', ''])
files[f'{new_info}/RECORD'] = record.getvalue().encode('utf-8')
with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
    for name, data in files.items():
        archive.writestr(name, data)
print(f'Official wheel SHA256: {hashlib.sha256(source.read_bytes()).hexdigest()}')
print(f'Prepared {target.name}: only package version and LanceDB dependency metadata changed.')
