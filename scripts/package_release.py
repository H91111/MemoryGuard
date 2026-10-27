"""Create a source release with exact file hashes; exclude local runtime state."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent.parent
VERSION = '0.2.0'
FILES = ['README.md','LICENSE','NOTICE','pyproject.toml','requirements-semantic.lock','app.py','start.ps1','启动工作台.cmd']
DIRS = ['memory_guard','examples','evaluation','data','tests','scripts','docs','output/evaluation-v020','output/acceptance']
paths = [ROOT/f for f in FILES]
for folder in DIRS:
    paths.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.db'})
paths = sorted(set(paths))
manifest = {p.relative_to(ROOT).as_posix(): {'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths}
(ROOT/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2),encoding='utf-8')
zip_path = ROOT.parent/f'MemoryGuard-v{VERSION}.zip'
with ZipFile(zip_path,'w',ZIP_DEFLATED,compresslevel=7) as z:
    for p in paths+[ROOT/'manifest.json']:
        z.write(p,f'MemoryGuard-v{VERSION}/'+p.relative_to(ROOT).as_posix())
with ZipFile(zip_path) as z:
    assert z.testzip() is None
    for name, entry in manifest.items():
        assert hashlib.sha256(z.read(f'MemoryGuard-v{VERSION}/'+name)).hexdigest()==entry['sha256'], name
result = {'file':zip_path.name,'files':len(paths)+1,'bytes':zip_path.stat().st_size,'sha256':hashlib.sha256(zip_path.read_bytes()).hexdigest()}
(ROOT.parent/'release-checksums.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
