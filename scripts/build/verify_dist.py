#! /usr/bin/env python3
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
Verify that the built wheel(s) and sdist(s) contain the symlinked files as regular files.

poetry-core alone would silently drop them (see kpex_build_backend.py and
https://github.com/iic-jku/klayout-pex/issues/210), this guards against a
regression, e.g. `poetry build` bypassing our build backend.

Checks all symlinks within the `packages` of pyproject.toml, including those checked out
as plain text files (Windows), see kpex_symlinks.py. Only uses the standard library (python >= 3.11).

Usage:
    python scripts/build/verify_dist.py [DIST_DIR]   (default: dist)
"""
from __future__ import annotations

import os
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import List

from kpex_symlinks import Link, PackageDirs, find_symlinks, poetry_package_dirs, wheel_path_of

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def verify_wheel(wheel_path: Path, links: List[Link], package_dirs: PackageDirs) -> List[str]:
    errors = []
    with zipfile.ZipFile(wheel_path) as wheel:
        for link, target in links:
            name = wheel_path_of(link, package_dirs)
            if name is None:
                continue  # not part of the wheel
            try:
                data = wheel.read(name)
            except KeyError:
                errors.append(f"{wheel_path.name}: missing {name}")
                continue
            if data != (PROJECT_ROOT / target).read_bytes():
                errors.append(f"{wheel_path.name}: content differs from the symlink target: {name}")
    return errors


def verify_sdist(sdist_path: Path, links: List[Link]) -> List[str]:
    errors = []
    with tarfile.open(sdist_path) as sdist:
        root = sdist.getnames()[0].split('/')[0]  # e.g. klayout_pex-0.4.4
        for link, target in links:
            name = f"{root}/{link}"
            try:
                member = sdist.getmember(name)
            except KeyError:
                errors.append(f"{sdist_path.name}: missing {name}")
                continue
            if not member.isreg():
                errors.append(f"{sdist_path.name}: not a regular file: {name}")
            elif sdist.extractfile(member).read() != (PROJECT_ROOT / target).read_bytes():
                errors.append(f"{sdist_path.name}: content differs from the symlink target: {name}")
    return errors


def main(argv: List[str]) -> int:
    dist_dir = Path(argv[1]) if len(argv) > 1 else Path('dist')
    wheels = sorted(dist_dir.glob('*.whl'))
    sdists = sorted(dist_dir.glob('*.tar.gz'))
    if not wheels and not sdists:
        print(f"ERROR: no wheel or sdist found in {dist_dir}")
        return 1

    package_dirs = poetry_package_dirs(PROJECT_ROOT)
    links = find_symlinks(PROJECT_ROOT, package_dirs)
    errors = []
    for wheel_path in wheels:
        errors += verify_wheel(wheel_path, links, package_dirs)
    for sdist_path in sdists:
        errors += verify_sdist(sdist_path, links)

    prefix = '::error::' if os.environ.get('GITHUB_ACTIONS') else 'ERROR: '
    for e in errors:
        print(f"{prefix}{e}")
    print(f"Checked {len(links)} symlinks in {', '.join(f'{d}/' for d in package_dirs)} against "
          f"{len(wheels)} wheel(s) and {len(sdists)} sdist(s): {len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
