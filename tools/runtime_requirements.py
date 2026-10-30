"""Inventory installed runtime dependency closure without exporting local paths/secrets.

Run after installing the application. Test/audit tools are excluded unless a runtime
package itself requires them. This is an inventory, not a cross-platform lock file.
"""
import argparse
from importlib import metadata
from pathlib import Path
import tomllib

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def inventory(project):
    with project.open('rb') as handle:
        roots = tomllib.load(handle)['project']['dependencies']
    queue = [Requirement(raw) for raw in roots]
    result, visited = {}, set()
    while queue:
        requirement = queue.pop()
        if requirement.url:
            raise ValueError('Runtime audit inventory does not export URL requirements')
        if requirement.marker and not requirement.marker.evaluate({'extra':''}):
            continue
        name = canonicalize_name(requirement.name)
        distribution = metadata.distribution(name)
        version = distribution.version
        if requirement.specifier and not requirement.specifier.contains(version, prereleases=True):
            raise ValueError(f'Installed {name} does not meet the runtime version constraint')
        result[name] = version
        key = (name, tuple(sorted(requirement.extras)))
        if key in visited:
            continue
        visited.add(key)
        for raw in distribution.requires or []:
            dependency = Requirement(raw)
            extras = requirement.extras or {''}
            if dependency.marker and not any(dependency.marker.evaluate({'extra':extra}) for extra in extras):
                continue
            # Already evaluated in the declaring package's extra context.
            dependency.marker = None
            queue.append(dependency)
    return dict(sorted(result.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[1] / 'pyproject.toml')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    data = inventory(args.project)
    text = ''.join(f'{name}=={version}\n' for name, version in data.items())
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf8')
        print(f'Inventoried {len(data)} installed runtime packages; no private package paths exported')
    else:
        print(text, end='')


if __name__ == '__main__':
    main()
