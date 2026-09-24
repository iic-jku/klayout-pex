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
PEP 517 build backend: poetry-core, plus symlink resolution for the bundled PDKs.

Some packaged files are symlinks, e.g. PDK rule decks into another PDK's tree:
    pdk/ihp-sg13cmos5l/libs.tech/kpex/rule_decks/sram_integration.lvs
      -> ../../../../ihp-sg13g2/libs.tech/kpex/rule_decks/sram_integration.lvs

poetry-core resolves every included path before de-duplicating, so each symlink
collapses into its target and is silently missing from the wheel and the sdist
(https://github.com/iic-jku/klayout-pex/issues/210). On Windows, where git
checks symlinks out as plain text files, poetry-core packages that text instead.

The source tree keeps its symlinks. After poetry-core has built an archive,
each symlink within the `packages` of pyproject.toml is (re)placed in it as a regular file,
with the content and metadata that poetry-core already wrote for its target.
"""
from __future__ import annotations

import copy
import csv
import gzip
import hashlib
import io
import os
import tarfile
import zipfile
from base64 import urlsafe_b64encode
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from poetry.core.masonry import api as _poetry_api
from poetry.core.masonry.api import (  # noqa: F401 (re-exported PEP 517/660 hooks)
    build_editable,
    get_requires_for_build_editable,
    get_requires_for_build_sdist,
    get_requires_for_build_wheel,
    prepare_metadata_for_build_editable,
    prepare_metadata_for_build_wheel,
)

# NOTE: importable, as backend-path puts this directory on sys.path
from kpex_symlinks import Link, PackageDirs, find_symlinks, poetry_package_dirs, wheel_path_of


def add_symlinks_to_wheel(wheel_path: Path, links: List[Link], package_dirs: PackageDirs):
    link_names: Dict[str, str] = {}
    for link, target in links:
        link_name, target_name = wheel_path_of(link, package_dirs), wheel_path_of(target, package_dirs)
        if link_name is None:
            continue  # not part of the wheel
        if target_name is None:
            raise RuntimeError(f"Symlink target is not part of the wheel: {link} -> {target}")
        link_names[link_name] = target_name
    tmp_path = wheel_path.with_name(wheel_path.name + '.tmp')
    with zipfile.ZipFile(wheel_path) as src, zipfile.ZipFile(tmp_path, 'w') as dst:
        names = set(src.namelist())
        record_name = next(n for n in names
                           if n.count('/') == 1 and n.endswith('.dist-info/RECORD'))
        records = [row for row in csv.reader(io.StringIO(src.read(record_name).decode('utf-8')))
                   if row and row[0] != record_name and row[0] not in link_names]

        for info in src.infolist():
            if info.filename != record_name and info.filename not in link_names:
                # NOTE: copy, as writestr() updates the ZipInfo (header offset) in place
                dst.writestr(copy.copy(info), src.read(info))

        for link_name, target_name in link_names.items():
            if target_name not in names:
                raise RuntimeError(f"Symlink target is not part of the wheel: {link_name} -> {target_name}")
            target_info = src.getinfo(target_name)
            info = zipfile.ZipInfo(link_name, target_info.date_time)
            info.external_attr = target_info.external_attr
            data = src.read(target_info)
            dst.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
            digest = urlsafe_b64encode(hashlib.sha256(data).digest()).decode('ascii').rstrip('=')
            records.append([link_name, f"sha256={digest}", str(len(data))])

        record = io.StringIO()
        writer = csv.writer(record, delimiter=csv.excel.delimiter, quotechar=csv.excel.quotechar,
                            lineterminator='\n')
        writer.writerows(records)
        writer.writerow([record_name, '', ''])
        dst.writestr(copy.copy(src.getinfo(record_name)), record.getvalue().encode('utf-8'))
    os.replace(tmp_path, wheel_path)


def add_symlinks_to_sdist(sdist_path: Path, links: List[Link]):
    tmp_path = sdist_path.with_name(sdist_path.name + '.tmp')
    with tarfile.open(sdist_path, 'r:gz') as src:
        members = src.getmembers()
        root = members[0].name.split('/')[0]  # e.g. klayout_pex-0.4.4
        by_name = {m.name: m for m in members}
        link_names = {f"{root}/{link}" for link, _ in links}

        new_members: List[Tuple[tarfile.TarInfo, bytes]] = []
        for link, target in links:
            target_name = f"{root}/{target}"
            if target_name not in by_name:
                raise RuntimeError(f"Symlink target is not part of the sdist: {link} -> {target}")
            info = copy.copy(by_name[target_name])
            info.name = f"{root}/{link}"
            new_members.append((info, src.extractfile(by_name[target_name]).read()))

        # poetry-core writes PKG-INFO last, keep it that way
        pkg_info = by_name.get(f"{root}/PKG-INFO")
        with open(tmp_path, 'wb') as f, \
             gzip.GzipFile(filename=sdist_path.name, mode='wb', fileobj=f,
                           mtime=pkg_info.mtime if pkg_info else 0) as gz, \
             tarfile.TarFile(mode='w', fileobj=gz, format=tarfile.PAX_FORMAT) as dst:
            for m in members:
                if m.name in link_names:
                    continue
                if m is pkg_info:
                    for info, data in new_members:
                        dst.addfile(info, io.BytesIO(data))
                    new_members = []
                dst.addfile(m, src.extractfile(m) if m.isreg() else None)
            for info, data in new_members:
                dst.addfile(info, io.BytesIO(data))
    os.replace(tmp_path, sdist_path)


def _remove_on_error(archive_path: Path, fix: Callable[[], None]):
    """Don't leave an archive with unresolved symlinks behind"""
    tmp_path = archive_path.with_name(archive_path.name + '.tmp')
    try:
        fix()
    except BaseException:
        archive_path.unlink(missing_ok=True)
        raise
    finally:
        tmp_path.unlink(missing_ok=True)


def build_wheel(wheel_directory: str,
                config_settings: Optional[Dict[str, Any]] = None,
                metadata_directory: Optional[str] = None) -> str:
    name = _poetry_api.build_wheel(wheel_directory, config_settings, metadata_directory)
    wheel_path = Path(wheel_directory) / name

    def fix():
        package_dirs = poetry_package_dirs(Path.cwd())
        links = find_symlinks(Path.cwd(), package_dirs)
        if links:
            add_symlinks_to_wheel(wheel_path, links, package_dirs)

    _remove_on_error(wheel_path, fix)
    return name


def build_sdist(sdist_directory: str,
                config_settings: Optional[Dict[str, Any]] = None) -> str:
    name = _poetry_api.build_sdist(sdist_directory, config_settings)
    sdist_path = Path(sdist_directory) / name

    def fix():
        links = find_symlinks(Path.cwd(), poetry_package_dirs(Path.cwd()))
        if links:
            add_symlinks_to_sdist(sdist_path, links)

    _remove_on_error(sdist_path, fix)
    return name
