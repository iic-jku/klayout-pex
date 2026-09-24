#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX
# (see https://github.com/iic-jku/klayout-pex).
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
# --------------------------------------------------------------------------------
#
"""
Smoke test suite: tests of the *installed* wheel, one module per aspect.

Tests running from the source checkout can't catch packaging bugs, e.g. rule decks
missing from the wheel (https://github.com/iic-jku/klayout-pex/issues/210),
as the checkout has all files. So the `installed_wheel` fixture installs the wheel
into a fresh venv, and smoke tests run its console scripts outside of the checkout.

All tests of this suite are marked 'smoke', and skipped unless KPEX_SMOKE_TEST_WHEEL points to the wheel.
Locally, run_smoke_tests.sh builds the wheel and runs the suite, or manually:
    poetry build
    KPEX_SMOKE_TEST_WHEEL=dist/klayout_pex-<version>-py3-none-any.whl poetry run pytest -m smoke

Requires network access, to install the wheel's dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from typing import *
import venv

import pytest


WHEEL_ENV_VAR = 'KPEX_SMOKE_TEST_WHEEL'

SMOKE_TESTS_DIR = Path(__file__).resolve().parent


@pytest.hookimpl(tryfirst=True)  # NOTE: before `-m` deselects by marker
def pytest_collection_modifyitems(config, items):
    """Marks all tests of this suite as 'smoke' (including future modules)"""
    for item in items:
        if Path(item.path).resolve().is_relative_to(SMOKE_TESTS_DIR):
            item.add_marker(pytest.mark.smoke)


def _isolated_env() -> Dict[str, str]:
    """Environment for processes of the wheel venv, which must not see the source checkout"""
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    return env


@dataclass(frozen=True)
class InstalledWheel:
    venv_dir: Path

    @property
    def bin_dir(self) -> Path:
        return self.venv_dir / ('Scripts' if os.name == 'nt' else 'bin')

    def executable(self, name: str) -> Path:
        """A console script (e.g. 'kpex') or 'python' of the venv"""
        return self.bin_dir / (f"{name}.exe" if os.name == 'nt' else name)

    def run(self,
            name: str,
            *args: Any,
            cwd: Path,
            timeout: float = 600) -> subprocess.CompletedProcess:
        """Runs a console script (or 'python') of the venv, the caller checks the return code"""
        return subprocess.run([str(self.executable(name)), *(str(a) for a in args)],
                              cwd=cwd, env=_isolated_env(), stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=timeout)

    def check_run(self, name: str, *args: Any, cwd: Path) -> subprocess.CompletedProcess:
        proc = self.run(name, *args, cwd=cwd)
        returncode = proc.returncode
        assert returncode == 0, \
            f"Command failed with status {returncode}: {' '.join(proc.args)}\n{proc.stdout}\n{proc.stderr}"
        return proc


@pytest.fixture(scope='session')
def installed_wheel(tmp_path_factory) -> InstalledWheel:
    """A fresh venv with the wheel (KPEX_SMOKE_TEST_WHEEL) installed"""
    if WHEEL_ENV_VAR not in os.environ:
        pytest.skip(f"{WHEEL_ENV_VAR} is not set")
    wheel_path = Path(os.environ[WHEEL_ENV_VAR]).resolve()
    assert wheel_path.is_file() and wheel_path.suffix == '.whl', \
        f"{WHEEL_ENV_VAR}={os.environ[WHEEL_ENV_VAR]} is not a wheel file"

    wheel = InstalledWheel(venv_dir=tmp_path_factory.mktemp('installed_wheel'))
    venv.create(wheel.venv_dir, with_pip=True)
    wheel.check_run('python', '-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', wheel_path,
                    cwd=wheel.venv_dir)

    # NOTE: guard against testing the source checkout by accident
    module_path = wheel.check_run('python', '-c', 'import klayout_pex; print(klayout_pex.__file__)',
                                  cwd=wheel.venv_dir).stdout.strip()
    assert Path(module_path).resolve().is_relative_to(wheel.venv_dir.resolve()), \
        f"klayout_pex is not imported from the wheel venv {wheel.venv_dir}, but from {module_path}"
    return wheel
