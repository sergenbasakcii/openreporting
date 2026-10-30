"""Build twice offline with installed locked tools; record same-environment equality."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('build/wheel-repro.json'))
    parser.add_argument('--source-date-epoch',type=int)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    stamp = args.source_date_epoch
    if stamp is None:
        stamp = int(subprocess.check_output(['git','show','-s','--format=%ct','HEAD'],cwd=root,text=True).strip())
    if not 315532800<=stamp<=4354819199:
        parser.error('SOURCE_DATE_EPOCH must be within the ZIP timestamp range')
    build_root = root / 'build'
    build_root.mkdir(exist_ok=True)
    assert build_root.resolve().is_relative_to(root)
    with tempfile.TemporaryDirectory(prefix='wheel-repro-',dir=build_root) as temporary:
        work = Path(temporary).resolve()
        assert work.is_relative_to(build_root.resolve())
        environment = {**os.environ,'SOURCE_DATE_EPOCH':str(stamp),'PIP_DISABLE_PIP_VERSION_CHECK':'1'}
        results = []
        for name in ('first','second'):
            target = work / name
            subprocess.run([sys.executable,'-m','pip','wheel','--no-index','--no-cache-dir','--no-deps',
                            '--no-build-isolation','--wheel-dir',str(target),str(root)],cwd=root,env=environment,check=True,capture_output=True)
            wheels = list(target.glob('openreporting-*.whl'))
            assert len(wheels)==1,'Expected exactly one application wheel'
            payload = wheels[0].read_bytes()
            results.append((hashlib.sha256(payload).hexdigest(),len(payload)))
        assert results[0]==results[1],'Two offline wheel builds differed'
        report = {'equal':True,'builds':2,'source_date_epoch':stamp,'wheel_sha256':results[0][0],
                  'wheel_bytes':results[0][1], 'python':sys.version.split()[0],
                  'scope':'Same source checkout, interpreter and installed locked build tools; not cross-platform equivalence or signed provenance'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report))


if __name__=='__main__':
    main()
