"""Configuration regressions: missing pins and incompatible declarations must fail."""
import importlib.util
from pathlib import Path
import shutil

spec = importlib.util.spec_from_file_location('dependency_check', Path(__file__).resolve().parents[2] / 'scripts/check_dependencies.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def copy_config(tmp_path):
    app = Path(__file__).resolve().parents[1]
    for name in ('pyproject.toml', 'constraints.txt', 'build-requirements.txt'):
        shutil.copyfile(app / name, tmp_path / name)
    return tmp_path


def test_new_dependency_requires_pin(tmp_path):
    folder = copy_config(tmp_path)
    path = folder / 'pyproject.toml'
    path.write_text(path.read_text().replace('dependencies = [', 'dependencies = ["unfixed-new-package>=1",', 1))
    assert any('unfixed-new-package: missing exact constraint' in x for x in module.check(folder))


def test_changed_range_and_build_mirror_are_rejected(tmp_path):
    folder = copy_config(tmp_path)
    path = folder / 'pyproject.toml'
    path.write_text(path.read_text().replace('httpx>=0.27,<1', 'httpx>=1,<2'))
    (folder / 'build-requirements.txt').write_text('setuptools==1.0\nwheel==0.48.0\n')
    errors = module.check(folder)
    assert any('does not satisfy' in x and 'httpx' in x for x in errors)
    assert any('build-requirements.txt differs' in x for x in errors)
