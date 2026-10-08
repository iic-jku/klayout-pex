#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
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
Cached LVS databases, which are reused only while the inputs of the LVS run are unchanged
(see protos/kpex/klayout/lvs_input_fingerprint.proto)
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import PurePath
import shutil
import tempfile
from typing import *

import google.protobuf.json_format

from klayout_pex_protobuf.kpex.klayout.lvs_input_fingerprint_pb2 import (
    FileFingerprint,
    LVSDeckFingerprint,
    LVSInputFingerprint
)


# NOTE: increment whenever the fingerprint is computed differently,
#       so that the fingerprints written by an older KPEX never match
FINGERPRINT_FORMAT_VERSION = 1

# NOTE: an upgrade may change every file of a deck, only name a few of them
MAX_NAMED_DECK_FILES = 5


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def file_fingerprint(path: str) -> FileFingerprint:
    return FileFingerprint(path=os.path.abspath(path),
                           sha256=file_sha256(path))


def deck_fingerprint(lvs_script_path: str) -> LVSDeckFingerprint:
    """
    Every file in the directory of the LVS script and below, as the script includes further files
    (%include, require, load) in ways that are not practical to trace.

    Hidden files (e.g. .DS_Store) are skipped, as are dangling symbolic links.
    """
    script_path = os.path.abspath(lvs_script_path)
    deck_dir_path = os.path.dirname(script_path)
    fingerprint = LVSDeckFingerprint(script_path=script_path)
    for dir_path, dir_names, file_names in os.walk(deck_dir_path, followlinks=True):
        dir_names[:] = [n for n in dir_names if not n.startswith('.')]
        for file_name in file_names:
            path = os.path.join(dir_path, file_name)
            if file_name.startswith('.') or not os.path.isfile(path):
                continue
            relative_path = PurePath(os.path.relpath(path, deck_dir_path)).as_posix()
            fingerprint.sha256_by_relative_path[relative_path] = file_sha256(path)
    return fingerprint


def lvs_input_fingerprint(pdk: str,
                          klayout_version: str,
                          lvs_script_path: str,
                          script_parameters: Dict[str, str],
                          gds_path: str,
                          cell_name: str,
                          schematic_path: str) -> LVSInputFingerprint:
    fingerprint = LVSInputFingerprint(format_version=FINGERPRINT_FORMAT_VERSION,
                                      pdk=pdk,
                                      klayout_version=klayout_version,
                                      cell_name=cell_name)
    fingerprint.deck.CopyFrom(deck_fingerprint(lvs_script_path))
    fingerprint.script_parameters.update(script_parameters)
    fingerprint.layout.CopyFrom(file_fingerprint(gds_path))
    fingerprint.schematic.CopyFrom(file_fingerprint(schematic_path))
    return fingerprint


def fingerprint_differences(cached: LVSInputFingerprint,
                            current: LVSInputFingerprint) -> List[str]:
    """
    What changed between the inputs of the cached LVS run and those of the current one,
    empty if the cached LVS database can be reused. Paths are not compared.
    """
    if cached.format_version != current.format_version:
        return [f"the fingerprint format changed ({cached.format_version} → {current.format_version})"]

    differences: List[str] = []

    def compare(what: str, cached_value: str, current_value: str):
        if cached_value != current_value:
            differences.append(f"{what} changed ({cached_value or 'unknown'} → {current_value or 'unknown'})")

    compare('the PDK', cached.pdk, current.pdk)
    compare('the KLayout version', cached.klayout_version, current.klayout_version)

    cached_files = dict(cached.deck.sha256_by_relative_path)
    current_files = dict(current.deck.sha256_by_relative_path)
    changed_files = sorted(p for p in cached_files.keys() | current_files.keys()
                           if cached_files.get(p) != current_files.get(p))
    if changed_files:
        named = ', '.join(changed_files[:MAX_NAMED_DECK_FILES])
        more = len(changed_files) - MAX_NAMED_DECK_FILES
        differences.append(f"the LVS deck changed ({named}{f' and {more} more files' if more > 0 else ''})")

    cached_parameters = dict(cached.script_parameters)
    current_parameters = dict(current.script_parameters)
    changed_parameters = [f"{n}: {cached_parameters.get(n, 'unset')} → {current_parameters.get(n, 'unset')}"
                          for n in sorted(cached_parameters.keys() | current_parameters.keys())
                          if cached_parameters.get(n) != current_parameters.get(n)]
    if changed_parameters:
        differences.append(f"the LVS script parameters changed ({', '.join(changed_parameters)})")

    if cached.layout.sha256 != current.layout.sha256:
        differences.append("the input layout changed")
    compare('the cell', cached.cell_name, current.cell_name)
    if cached.schematic.sha256 != current.schematic.sha256:
        differences.append("the schematic changed")

    return differences


def read_fingerprint(path: str) -> Optional[LVSInputFingerprint]:
    """
    None if there is none, or it can't be read (e.g. written by an incompatible KPEX version)
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return google.protobuf.json_format.Parse(f.read(), LVSInputFingerprint())
    except (OSError, google.protobuf.json_format.ParseError):
        return None


def write_fingerprint(path: str, fingerprint: LVSInputFingerprint):
    json_str = google.protobuf.json_format.MessageToJson(fingerprint,
                                                         preserving_proto_field_name=True,
                                                         sort_keys=True,
                                                         ensure_ascii=False)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(json_str)


@dataclass(frozen=True)
class LVSCacheEntry:
    """
    The cached LVS database of a cell, and the fingerprint of the LVS inputs it was created from
    """
    dir_path: str
    cell_name: str

    @property
    def lvsdb_path(self) -> str:
        return os.path.join(self.dir_path, f"{self.cell_name}.lvsdb.gz")

    @property
    def fingerprint_path(self) -> str:
        return os.path.join(self.dir_path, f"{self.cell_name}.lvs_fingerprint.pb.json")

    def cache_miss_reasons(self, fingerprint: LVSInputFingerprint) -> List[str]:
        """
        Why the cached LVS database can't be reused, empty if it can
        """
        if not os.path.isfile(self.lvsdb_path):
            return ["there is no cached LVSDB"]
        cached_fingerprint = read_fingerprint(self.fingerprint_path)
        if cached_fingerprint is None:
            return ["the cached LVSDB has no fingerprint of its LVS inputs"]
        return fingerprint_differences(cached_fingerprint, fingerprint)

    def store(self, lvsdb_path: str, fingerprint: LVSInputFingerprint):
        os.makedirs(self.dir_path, exist_ok=True)
        # NOTE: the fingerprint is written last, so an interrupted store leaves an entry without one,
        #       which is never reused
        if os.path.exists(self.fingerprint_path):
            os.remove(self.fingerprint_path)
        # NOTE: each file is written beside its place and renamed into it, so that a concurrent run
        #       reading the entry (e.g. parallel tests sharing the cache) never reads a partly written file
        self._replace(self.lvsdb_path, lambda tmp_path: shutil.copyfile(lvsdb_path, tmp_path))
        self._replace(self.fingerprint_path, lambda tmp_path: write_fingerprint(tmp_path, fingerprint))

    def _replace(self, path: str, write: Callable[[str], Any]):
        fd, tmp_path = tempfile.mkstemp(dir=self.dir_path, prefix=f".{os.path.basename(path)}.", suffix='.tmp')
        os.close(fd)
        try:
            write(tmp_path)
            os.replace(tmp_path, path)
        except BaseException:
            os.remove(tmp_path)
            raise
