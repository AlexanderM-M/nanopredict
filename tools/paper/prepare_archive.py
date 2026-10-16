"""Build a local, tracked-file preparation archive. Does not upload or publish."""
import argparse
import gzip
import hashlib
import json
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--output',type=Path,required=True); a=p.parse_args()
    if subprocess.check_output(['git','status','--porcelain','--untracked-files=normal'],cwd=ROOT,text=True).strip():
        raise ValueError('Commit reviewed changes first; archive only a clean tracked snapshot')
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    names=subprocess.check_output(['git','ls-files'],cwd=ROOT,text=True).splitlines()
    if any('.study/' in n or n.endswith(('.sqlite','.sqlite-wal','.sqlite-shm')) for n in names):
        raise ValueError('Study database unexpectedly tracked; do not archive')
    a.output.mkdir(parents=True,exist_ok=True)
    target=a.output/f'nanopredict-preparation-{revision[:12]}.tar.gz'
    tar=subprocess.check_output(['git','archive','--format=tar','--prefix=nanopredict/',revision],cwd=ROOT)
    with target.open('xb') as handle: handle.write(gzip.compress(tar,mtime=0))
    manifest={'revision':revision,'archive':target.name,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
              'status':'PREPARATION ONLY — independent validation outstanding; not submission-ready',
              'files':{n:hashlib.sha256(subprocess.check_output(['git','show',f'{revision}:{n}'],cwd=ROOT)).hexdigest() for n in names},
              'exclusions':'Untracked/ignored data, virtual environment, local study records, git metadata and this archive directory are excluded.'}
    target.with_suffix('.manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(target)


if __name__=='__main__': main()
