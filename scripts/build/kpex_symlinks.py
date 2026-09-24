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
Helpers to package symlinked files as regular files.

Linux/macOS checkouts contain real symlinks. On Windows, git (unless core.symlinks=true)
checks out a symlink as a plain text file containing the link target path,
those are recognized by their git file mode 120000.

Shared by kpex_build_backend.py and verify_dist.py, only uses the standard library (python >= 3.11).
"""
from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

GIT_SYMLINK_MODE = b'120000'

Link = Tuple[str, str]  # (link path, resolved target path), both POSIX and relative to the project root


def git_symlinks(project_root: Path, source_dirs: Iterable[str]) -> Set[str]:
    """
    Paths (POSIX, relative to the project root) that git tracks as symlinks.

    Empty without git, e.g. when building a wheel from the sdist
    (which contains no symlinks anyway).
    """
    try:
        out = subprocess.run(['git', '-C', str(project_root), 'ls-files', '--stage', '-z', '--',
                              *source_dirs],
                             capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return set()
    links = set()
    for entry in out.split(b'\0'):
        if not entry:
            continue
        info, path = entry.split(b'\t', 1)  # <mode> <object> <stage>\t<path>
        if info.split(b' ', 1)[0] == GIT_SYMLINK_MODE:
            links.add(path.decode('utf-8'))
    return links


def read_text_symlink(path: Path) -> Optional[str]:
    """
    The link target of a symlink that git checked out as a plain text file,
    None if the file has been replaced by real content.
    """
    data = path.read_bytes().strip()
    if len(data) > 4096 or b'\n' in data:
        return None
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return None


def find_symlinks(project_root: Path, source_dirs: Iterable[str]) -> List[Link]:
    """
    Symlinks to files within source_dirs (POSIX, relative to the project root),
    both real ones and those checked out as plain text files
    """
    source_dirs = list(source_dirs)
    project_root = project_root.resolve()
    git_links = git_symlinks(project_root, source_dirs)
    links: Dict[str, str] = {}
    for source_dir in source_dirs:
        for dirpath, dirnames, filenames in os.walk(project_root / source_dir):
            for name in dirnames + filenames:
                path = Path(dirpath) / name
                rel_path = path.relative_to(project_root).as_posix()
                if path.is_symlink():
                    target = path.resolve()
                    description = f"{path} -> {os.readlink(path)}"
                elif rel_path in git_links and path.is_file():
                    link_text = read_text_symlink(path)
                    if link_text is None:
                        continue  # no longer a symlink, but a regular file
                    target = (path.parent / link_text).resolve()
                    description = f"{path} -> {link_text} (checked out as plain text file)"
                else:
                    continue
                if not target.is_file():
                    raise RuntimeError(f"Unsupported symlink (dangling, or not pointing to a file): "
                                       f"{description}")
                if not target.is_relative_to(project_root):
                    raise RuntimeError(f"Symlink points outside of the project, refusing to package: "
                                       f"{description}")
                rel_target = target.relative_to(project_root).as_posix()
                if rel_target in git_links and read_text_symlink(target) is not None:
                    # NOTE: resolve() follows chains of real symlinks, but not of text files
                    raise RuntimeError(f"Chained symlinks are unsupported: {description}")
                links[rel_path] = rel_target
    return sorted(links.items())


PackageDirs = Dict[str, Optional[str]]  # source directory → location in the wheel (None: sdist only)


def poetry_package_dirs(project_root: Path) -> PackageDirs:
    """
    The `packages` of [tool.poetry] in pyproject.toml,
    only plain directories are supported (glob patterns are skipped)
    """
    with open(project_root / 'pyproject.toml', 'rb') as f:
        packages = tomllib.load(f).get('tool', {}).get('poetry', {}).get('packages', [])
    dirs: PackageDirs = {}
    for package in packages:
        include = package['include']
        if any(c in include for c in '*?['):
            continue
        formats = package.get('format', ['sdist', 'wheel'])
        if isinstance(formats, str):
            formats = [formats]
        source_dir = Path(package.get('from', '.'), include).as_posix()
        dirs[source_dir] = Path(package.get('to', '.'), include).as_posix() if 'wheel' in formats else None
    return dirs


def wheel_path_of(source_path: str, package_dirs: PackageDirs) -> Optional[str]:
    """
    Location of a source file (POSIX, relative to the project root) in the wheel,
    None if it's not part of the wheel
    """
    for source_dir in sorted(package_dirs, key=len, reverse=True):  # most specific first
        if source_path.startswith(f"{source_dir}/"):
            wheel_dir = package_dirs[source_dir]
            return None if wheel_dir is None else wheel_dir + source_path[len(source_dir):]
    return None
