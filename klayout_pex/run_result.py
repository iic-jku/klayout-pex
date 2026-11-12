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
The result file of a kpex run, for the scripts that drive kpex, so that they neither hard-code the paths
of its outputs nor parse its log (#427): kpex_result.json in the run directory, also written to --out-result.
Its keys, and when it is written, are described in 'Result file' of DEVELOPMENT.md.

Each write replaces it as a whole (a temporary file, renamed), so that it is never read half-written.
FORMAT_VERSION goes up when a key is removed or changes its meaning, not for new keys.
"""

from __future__ import annotations

import contextlib
import dataclasses
from dataclasses import dataclass, field
from enum import StrEnum
import json
import logging
import os
from typing import *

from .extraction_engine import ExtractionEngine
from .log import (
    deregister_additional_handler,
    error,
    info,
    register_additional_handler,
)
from .netlist.netlist_format import NetlistFormat
from .pex25d.diagnostics import ExitCode
from .util.peak_memory import peak_memory
from .version import __version__

FORMAT_VERSION = 1

RESULT_FILE_NAME = 'kpex_result.json'


class Stage(StrEnum):
    """What the run is doing, in this order"""
    ARGUMENTS = 'arguments'  # checking the arguments, reading the tech info
    MAGIC = 'magic'
    LVS = 'lvs'  # LVS, or reading --lvsdb, and preparing the extraction from the LVS database
    FASTERCAP = 'fastercap'  # also the input of FastCap2, if run with FasterCap
    FASTCAP2 = 'fastcap2'
    K25D = '2.5d'
    PEX25D = 'pex25d'  # kpex pex25d
    DONE = 'done'  # ended with exit code 0


class FileKind(StrEnum):
    NETLIST = 'netlist'
    OUT_NETLIST = 'out_netlist'  # --out-netlist
    NETLIST_OPTIONS = 'netlist_options'  # companion for the simulator's control block
    NETLIST_CSV = 'netlist_csv'
    CAPACITANCE_MATRIX = 'capacitance_matrix'
    REPORT = 'report'  # KLayout report database
    LVSDB = 'lvsdb'
    LOG = 'log'
    PEX25D_FILE = 'pex25d_file'  # --out-file of kpex pex25d
    PEX25D_SCENE = 'pex25d_scene'  # --out-scene of kpex pex25d


NETLIST_KINDS = (FileKind.NETLIST, FileKind.OUT_NETLIST)


@dataclass(frozen=True)
class WrittenFile:
    kind: FileKind
    path: str  # absolute
    engine: Optional[ExtractionEngine] = None  # None for the files of the run, e.g. its log
    netlist_format: Optional[NetlistFormat] = None  # of a netlist
    reduced: bool = False  # of a netlist
    ports: Optional[List[str]] = None  # of a netlist, as its .SUBCKT line of the cell has them, None without it

    def to_json(self) -> Dict[str, Any]:
        written = {'kind': self.kind.value, 'path': self.path,
                   'engine': self.engine.value if self.engine is not None else None}
        if self.kind in NETLIST_KINDS:
            written.update({'format': self.netlist_format.value, 'reduced': self.reduced, 'ports': self.ports})
        return written


@dataclass(frozen=True)
class DeviceCounts:
    """Of the devices of the LVS netlist of the cell"""
    black_boxed: int  # left to their models with --blackbox y, of the classes the white-box mode removes
    white_boxed: int  # removed with --blackbox n (e.g. MIM and MOM caps), their capacitances extracted
    excluded: int  # left out for a model, of the cells of --cut


class _LoggedProblems(logging.Handler):
    """The warnings and errors logged during the run"""

    def __init__(self, result: RunResult):
        super().__init__(level=logging.WARNING)
        self.result = result

    def emit(self, record: logging.LogRecord):
        try:
            message = record.getMessage()
        except Exception:
            self.handleError(record)
            return
        (self.result.errors if record.levelno >= logging.ERROR else self.result.warnings).append(message)


@dataclass
class RunResult:
    """
    What the result file has of the run: its callers note what they know, when they know it
    """
    command: Optional[str] = None  # e.g. 'extract'
    arguments: List[str] = field(default_factory=list)  # of the command line, after the program name
    pdk: Optional[str] = None
    cell: Optional[str] = None
    technology_selection: Optional[Dict[str, Any]] = None
    engines: List[ExtractionEngine] = field(default_factory=list)
    mode: Optional[str] = None  # --mode of the 2.5D engine
    inputs: Dict[str, Optional[str]] = field(default_factory=dict)  # e.g. {'gds': …}, absolute paths
    run_dir: Optional[str] = None  # absolute
    out_result_path: Optional[str] = None  # --out-result
    stage: Stage = Stage.ARGUMENTS
    exit_code: Optional[int] = None  # None until the run ends
    halo_um: Optional[float] = None
    devices: Optional[DeviceCounts] = None
    check_problems: Optional[List[str]] = None
    device_capacitance_checks: Optional[List[Dict[str, Any]]] = None
    files: List[WrittenFile] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    _announced_paths: Set[str] = field(default_factory=set, repr=False)
    _failed_paths: Set[str] = field(default_factory=set, repr=False)

    def add_file(self,
                 kind: FileKind,
                 path: str,
                 engine: Optional[ExtractionEngine] = None,
                 netlist_format: Optional[NetlistFormat] = None,
                 reduced: bool = False,
                 ports: Optional[List[str]] = None):
        """
        :param path: of a file the run wrote
        """
        self.files.append(WrittenFile(kind=kind, path=os.path.abspath(path), engine=engine,
                                      netlist_format=netlist_format, reduced=reduced, ports=ports))

    def enter(self, stage: Stage):
        self.stage = stage
        self.write()

    def paths(self) -> List[str]:
        """
        :return: where the result file goes: into the run directory once it is known, and to --out-result
        """
        paths = [os.path.join(self.run_dir, RESULT_FILE_NAME)] if self.run_dir is not None else []
        if self.out_result_path is not None and os.path.abspath(self.out_result_path) not in paths:
            paths.append(os.path.abspath(self.out_result_path))
        return paths

    def to_json(self) -> Dict[str, Any]:
        memory = peak_memory()
        return {
            'format_version': FORMAT_VERSION,
            'kpex_version': __version__,
            'command': self.command,
            'arguments': self.arguments,
            'pdk': self.pdk,
            'technology_selection': self.technology_selection,
            'cell': self.cell,
            'engines': [engine.value for engine in self.engines],
            'mode': self.mode,
            'inputs': self.inputs,
            'run_dir': self.run_dir,
            'stage': self.stage.value,
            'exit_code': self.exit_code,
            'halo_um': self.halo_um,
            'devices': dataclasses.asdict(self.devices) if self.devices is not None else None,
            'check_problems': self.check_problems,
            'device_capacitance_checks': self.device_capacitance_checks,
            'peak_memory': {'process_bytes': memory.process, 'largest_subprocess_bytes': memory.largest_subprocess},
            'files': [written.to_json() for written in self.files],
            'warnings': self.warnings,
            'errors': self.errors,
        }

    def write(self, announce: bool = True) -> bool:
        """
        Writes the result file to its paths (see paths), each as a whole, and logs the first failure of each path
        as an error, but the run goes on (e.g. a reader on Windows may keep it open for a moment)

        :param announce: whether to log the first write to each path (e.g. not before the log files are open)
        :return: whether it could write each of them
        """
        text = json.dumps(self.to_json(), indent=2, ensure_ascii=False) + '\n'
        all_written = True
        for path in self.paths():
            temporary_path = f"{path}.tmp"
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(temporary_path, 'w', encoding='utf-8') as f:
                    f.write(text)
                os.replace(temporary_path, path)
            except OSError as e:
                all_written = False
                if path not in self._failed_paths:
                    self._failed_paths.add(path)
                    error(f"Can't write the result file to: {path}: {e}")
                continue
            if announce and path not in self._announced_paths:
                self._announced_paths.add(path)
                info(f"Wrote result file to: {path}")
        return all_written

    @contextlib.contextmanager
    def recording(self) -> Iterator[RunResult]:
        """
        Collects the warnings and errors logged within, and writes the result file in the end,
        with the exit code of the run, also if it fails
        """
        handler = _LoggedProblems(self)
        register_additional_handler(handler)
        try:
            yield self
            self.exit_code = int(ExitCode.OK)
        except SystemExit as e:
            # NOTE: as Python exits with it, e.g. 1 for a message
            self.exit_code = 0 if e.code is None else int(e.code) if isinstance(e.code, int) else 1
            raise
        except Exception as e:
            self.exit_code = 1  # NOTE: as Python exits with it, after the traceback
            self.errors.append(f"{type(e).__name__}: {e}")
            raise
        finally:
            deregister_additional_handler(handler)
            if self.exit_code == ExitCode.OK:
                self.stage = Stage.DONE
            self.write()
