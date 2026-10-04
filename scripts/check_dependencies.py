"""Validate direct dependency pins and installed dependency closure without network."""
import argparse
from importlib import metadata
from pathlib import Path
import sys
import tomllib
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]


def requirements(path):
    return [Requirement(line.strip()) for line in path.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith('#')]


def check(app):
    project = tomllib.loads((app / 'pyproject.toml').read_text())
    pins = requirements(app / 'constraints.txt')
    errors = []
    by_name = {}
    for pin in pins:
        specs = list(pin.specifier)
        if len(specs) != 1 or specs[0].operator != '==' or '*' in specs[0].version:
            errors.append(f'{pin.name}: constraint must be one exact version')
            continue
        by_name.setdefault(canonicalize_name(pin.name), []).append(pin)
    if errors:
        return errors
    declared = [Requirement(x) for x in project['project']['dependencies']]
    for group in project['project'].get('optional-dependencies', {}).values():
        declared.extend(Requirement(x) for x in group)
    build = [Requirement(x) for x in project['build-system']['requires']]
    mirror = requirements(app / 'build-requirements.txt')
    if {str(x) for x in build} != {str(x) for x in mirror}:
        errors.append('build-requirements.txt differs from build-system.requires')
    for req in [*declared, *build]:
        matches = by_name.get(canonicalize_name(req.name), [])
        if not matches:
            errors.append(f'{req.name}: missing exact constraint')
        for pin in matches:
            version = next(iter(pin.specifier)).version
            if req.url or not req.specifier.contains(version, prereleases=True):
                errors.append(f'{req.name}: pinned {version} does not satisfy {req.specifier}')
    # Inspect installed metadata for transitive dependencies of every active pin.
    # Inactive OS pins stay in the universal file and their direct ranges are checked above.
    build_names = {canonicalize_name(x.name) for x in build}
    for pin in pins:
        # Build backends are installed in pip's isolated build environment.
        if canonicalize_name(pin.name) in build_names:
            continue
        if pin.marker and not pin.marker.evaluate():
            continue
        try:
            dist = metadata.distribution(pin.name)
        except metadata.PackageNotFoundError:
            errors.append(f'{pin.name}: not installed; install with --browser --postgres --identity --storage before checking')
            continue
        if not pin.specifier.contains(dist.version, prereleases=True):
            errors.append(f'{pin.name}: installed {dist.version} differs from {pin.specifier}')
        for raw in dist.requires or []:
            req = Requirement(raw)
            if req.marker and not req.marker.evaluate({'extra': ''}):
                continue
            active = [p for p in by_name.get(canonicalize_name(req.name), [])
                      if not p.marker or p.marker.evaluate()]
            if not active:
                errors.append(f'{pin.name} -> {req.name}: transitive dependency is not pinned')
            for child in active:
                version = next(iter(child.specifier)).version
                if req.url or not req.specifier.contains(version, prereleases=True):
                    errors.append(f'{pin.name} -> {req.name}: pin {version} outside {req.specifier}')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, default=ROOT / 'app')
    args = parser.parse_args()
    try:
        errors = check(args.app)
    except (ValueError, OSError, KeyError) as exc:
        errors = [str(exc)]
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print('Dependency definitions, exact pins, build requirements and installed closure agree.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
