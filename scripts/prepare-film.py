"""Prepare a relocatable Python 3.13 runtime and the pinned, unmodified film core."""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REVISION = '3bb2c2d2801ff68b92019cf1dbcbb133d60832bc'
VENDOR = ROOT / 'third_party' / 'spektrafilm'
RUNTIME = ROOT / '.tools' / 'film-runtime'


def prepare_vendor():
    if (VENDOR / 'SOURCE.json').exists():
        assert json.loads((VENDOR / 'SOURCE.json').read_text())['revision'] == REVISION
        return
    import httpx
    tree = httpx.get(f'https://api.github.com/repos/andreavolpato/spektrafilm/git/trees/{REVISION}?recursive=1', timeout=45).json()['tree']
    archive = ROOT / 'work' / 'spektrafilm-source.zip'
    if not archive.exists():
        archive.parent.mkdir(exist_ok=True)
        with httpx.stream('GET', f'https://codeload.github.com/andreavolpato/spektrafilm/zip/{REVISION}', timeout=120) as response:
            response.raise_for_status()
            with archive.open('wb') as stream:
                for chunk in response.iter_bytes():
                    stream.write(chunk)
    with zipfile.ZipFile(archive) as bundle:
        prefix = bundle.namelist()[0].split('/')[0] + '/'
        selected = [x for x in tree if x['type']=='blob' and (x['path'].startswith('src/spektrafilm/') or x['path'] in ('LICENSE','SPEKTRAFILM_LICENSE.txt','CITATION.cff','README.md','pyproject.toml'))]
        # Verify the archive against the pinned Git tree, even when reusing a download.
        for item in selected:
            data = bundle.read(prefix + item['path'])
            blob_hash = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
            if blob_hash != item['sha']:
                raise RuntimeError('Downloaded source does not match the pinned revision: ' + item['path'])
        for item in selected:
            target = VENDOR / item['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bundle.read(prefix + item['path']))
    (VENDOR / 'SOURCE.json').write_text(json.dumps({'url':'https://github.com/andreavolpato/spektrafilm','revision':REVISION,'version':'0.3.4','modifications':'None; only the runtime package and its data are included.'},indent=2),encoding='utf-8')


def main():
    os.chdir(ROOT)
    prepare_vendor()
    uv = ROOT / '.venv' / 'Scripts' / 'uv.exe'
    if not uv.exists():
        subprocess.run([sys.executable,'-m','pip','install','uv==0.13.6'],check=True)
    installations = ROOT / '.tools' / 'film-python'
    subprocess.run([str(uv),'python','install','3.13.18','--install-dir',str(installations)],check=True)
    bases = sorted(installations.glob('cpython-3.13.18-windows-x86_64-none'))
    if not bases:
        raise RuntimeError('Python 3.13 installation missing')
    base = bases[-1]
    if not (RUNTIME / 'python.exe').exists():
        shutil.copytree(base,RUNTIME,dirs_exist_ok=True)
    lock = ROOT / 'requirements-film.lock'
    if not lock.exists():
        subprocess.run([str(uv),'pip','compile','requirements-film.in','--python',str(RUNTIME/'python.exe'),'--output-file',str(lock),'--generate-hashes'],check=True,stdout=subprocess.DEVNULL)
    local_wheels=ROOT/'.tools/film-wheels'
    extra=['--find-links',str(local_wheels)] if local_wheels.exists() else []
    if local_wheels.exists():
        from packaging.utils import canonicalize_name, parse_wheel_filename
        expected={(canonicalize_name(n),v) for n,v in re.findall(r'^([a-z0-9-]+)==([^\s\\]+)',lock.read_text(),re.M)}
        available={(str(parse_wheel_filename(p.name)[0]),str(parse_wheel_filename(p.name)[1])) for p in local_wheels.glob('*.whl')}
        if expected <= available:extra=['--no-index',*extra]
    subprocess.run([str(uv),'pip','install','--python',str(RUNTIME/'python.exe'),'--break-system-packages','--require-hashes','-r',str(lock),*extra],check=True)
    shutil.copytree(VENDOR/'src'/'spektrafilm',RUNTIME/'Lib'/'site-packages'/'spektrafilm',dirs_exist_ok=True)
    films,papers=[],[]
    for path in sorted((VENDOR/'src/spektrafilm/data/profiles').glob('*.json')):
        info=json.loads(path.read_text(encoding='utf-8'))['info']
        value={'id':path.stem,'name':info['name'],'type':info['type']}
        if info['stage']=='filming':films.append(value)
        elif info['stage']=='printing':papers.append(value)
    for name in ('LICENSE','SPEKTRAFILM_LICENSE.txt','CITATION.cff','SOURCE.json','ADDITIONAL-NOTICES.txt'):
        shutil.copy2(VENDOR/name,RUNTIME/name)
    subprocess.run([str(RUNTIME/'python.exe'),'-I','-c','from spektrafilm import init_params; print(init_params().film.info.name)'],check=True)
    (RUNTIME/'catalog.json').write_text(json.dumps({'engine':'spektrafilm','version':'0.3.4','revision':REVISION,'films':films,'papers':papers},ensure_ascii=False,indent=2),encoding='utf-8')
    print('Film runtime ready:', RUNTIME)


if __name__=='__main__':main()
