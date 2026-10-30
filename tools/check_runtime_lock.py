"""Fail CI when the installed application closure drifts from the reviewed lock."""
from pathlib import Path
import argparse
import platform
import re

if __package__:
    from .runtime_requirements import inventory
else:
    from runtime_requirements import inventory


def check(root,scope='runtime'):
    if scope not in {'runtime','build','test'}:
        raise ValueError('Unknown dependency scope')
    expected = {}
    hashes = 0
    filename = f'requirements-{scope}.lock'
    for line in (root / filename).read_text(encoding='utf8').splitlines():
        if not line or line.startswith('#'):
            continue
        package = re.fullmatch(r'([a-z0-9-]+)==([0-9A-Za-z.+-]+)(; platform_system == "Windows")? \\',line)
        if package:
            if bool(package[3]) != (package[1] in {'tzdata','colorama'}):
                raise ValueError('Unexpected platform marker in runtime lock')
            if expected and not hashes:
                raise ValueError('Unhashed runtime lock entry')
            if package[1] in expected:
                raise ValueError('Duplicate runtime lock entry')
            expected[package[1]] = package[2]
            hashes = 0
        elif re.fullmatch(r'    --hash=sha256:[a-f0-9]{64}( \\)?',line) and expected:
            hashes += 1
        else:
            raise ValueError('Unexpected runtime lock syntax')
    if not hashes:
        raise ValueError('Empty or unhashed runtime lock')
    if platform.system() != 'Windows':
        expected.pop('tzdata',None)
        expected.pop('colorama',None)
    actual = inventory(root / 'pyproject.toml',scope)
    if actual != expected:
        raise ValueError(f'{scope} lock drift: '+', '.join(sorted(name for name in set(actual) | set(expected) if actual.get(name)!=expected.get(name))))
    print(f'Installed {scope} closure matches {len(actual)} locked packages')


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope',choices=['runtime','build','test'],default='runtime')
    check(Path(__file__).resolve().parents[1],parser.parse_args().scope)
