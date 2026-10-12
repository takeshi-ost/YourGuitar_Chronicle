"""Serve local ES module dependencies without relaxing API fixture assertions."""
import re
from pathlib import Path

IMPORT = re.compile(r"(?:from\s*|import\s*\()\s*['\"](\./[^'\"]+)['\"]")


def include_module_dependencies(static, assets):
    pending = list(assets)
    while pending:
        name = pending.pop()
        if not name.endswith('.js'):
            continue
        for relative in IMPORT.findall(assets[name]):
            path = (static / Path(name).parent / relative).resolve()
            if path.parent != static.resolve() or path.suffix != '.js':
                raise ValueError('Nonlocal fixture module: ' + relative)
            dependency = path.name
            if dependency not in assets:
                assets[dependency] = path.read_text(encoding='utf-8')
                pending.append(dependency)
