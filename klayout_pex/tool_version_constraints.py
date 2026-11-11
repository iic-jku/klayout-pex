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

"""Version requirements for the external tools, and the checks against them."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
import subprocess
from typing import *

from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

from .env import EnvVar
from .log import debug, error, rule, subproc, warning
from .pdk_config import PDK


class Tool(StrEnum):
    FASTCAP = 'FastCap2'
    FASTERCAP = 'FasterCap'
    KLAYOUT = 'KLayout'
    MAGIC = 'MAGIC'

    @property
    def env_var(self) -> EnvVar:
        match self:
            case Tool.FASTCAP: return EnvVar.FASTCAP_EXE
            case Tool.FASTERCAP: return EnvVar.FASTERCAP_EXE
            case Tool.KLAYOUT: return EnvVar.KLAYOUT_EXE
            case Tool.MAGIC: return EnvVar.MAGIC_EXE
            case _: raise NotImplementedError(f"Unexpected tool '{self.name}'")

    @property
    def version_argument(self) -> str:
        match self:
            case Tool.KLAYOUT: return '-v'
            case _: return '--version'

    def parse_version(self, text: str) -> Optional[Version]:
        """
        The version a tool reports, as a comparable PEP 440 version.

        MAGIC spells its patch level 'revision' and prints it in the banner of
        every run ('Magic 8.3 revision 681'), so that becomes 8.3.681 and the
        banner an extraction already captured can be used as-is.
        """
        match self:
            case Tool.MAGIC:
                m = re.search(r'(?:Magic\s+)?(\d+)\.(\d+)(?:\s+revision\s+|\.)(\d+)',
                              text, flags=re.IGNORECASE)
                candidate = None if m is None else '.'.join(m.groups())
            case _:
                # A packaging release ('0.30.4-1' from the KLayout .deb) is not
                # part of the tool's own version and is left out.
                m = re.search(rf'(?:{re.escape(self.value)}\s+)?v?(\d+\.\d+(?:\.\d+)?)',
                              text, flags=re.IGNORECASE)
                candidate = None if m is None else m.group(1)

        if candidate is None:
            return None
        try:
            return Version(candidate)
        except InvalidVersion:
            return None

    def detect_version(self, exe_path: str) -> Optional[Version]:
        """
        Ask the tool for its version. None when it could not be determined,
        which is never fatal: an unknown version only means unchecked.
        """
        try:
            proc = subprocess.run([exe_path, self.version_argument],
                                  capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
        except (OSError, subprocess.SubprocessError) as e:
            debug(f"Could not run '{exe_path} {self.version_argument}': {e}")
            return None

        # Some tools print their banner and then complain about the argument,
        # so the output is parsed whatever the exit code was.
        return self.parse_version(f"{proc.stdout}\n{proc.stderr}")


class Severity(StrEnum):
    ERROR = 'error'
    WARNING = 'warning'


class VersionCheckMode(StrEnum):
    ON = 'on'
    """Report a violated constraint at its own severity."""

    OFF = 'off'
    """Do not look at tool versions at all."""

    WARN = 'warn'
    """Report every violated constraint as a warning, never as an error."""

    DEFAULT = 'on'


@dataclass(frozen=True)
class ToolVersionConstraint:
    """
    One requirement on the version of an external tool.

    Constraints are declared rather than checked inline so that they compose:
    the effective requirement for a tool is the conjunction of everything that
    applies to it, which is what gets reported.
    """

    id: str
    """Names this constraint in the log."""

    tool: Tool

    specifier: str
    """A PEP 440 specifier: '>= 0.30.3', '!= 0.30.5', '< 9.0'."""

    reason: str
    """Why the constraint exists. Printed when it is violated."""

    severity: Severity = Severity.ERROR

    pdk: Optional[PDK] = None
    """The PDK that needs this. None applies to every PDK."""

    @property
    def specifier_set(self) -> SpecifierSet:
        return SpecifierSet(self.specifier)

    def is_satisfied_by(self, version: Version) -> bool:
        return self.specifier_set.contains(version, prereleases=True)

    def applies_to(self, pdk: Optional[PDK]) -> bool:
        return self.pdk is None or self.pdk == pdk


TOOL_VERSION_CONSTRAINTS: Tuple[ToolVersionConstraint, ...] = (
    ToolVersionConstraint(
        id='KLAYOUT_NEIGHBORHOOD_VISITOR',
        tool=Tool.KLAYOUT,
        specifier='>= 0.30.1',
        reason="the KPEX/2.5D engine needs PolygonNeighborhoodVisitor, "
               "EdgeNeighborhoodVisitor and the *WithProperties geometry classes",
    ),
    ToolVersionConstraint(
        id='KLAYOUT_PEX_MODULE',
        tool=Tool.KLAYOUT,
        specifier='>= 0.30.2',
        reason="resistance extraction needs the klayout.pex module",
    ),
    ToolVersionConstraint(
        id='KLAYOUT_RESISTANCE_FIXES',
        tool=Tool.KLAYOUT,
        specifier='>= 0.30.3',
        reason="earlier releases have bugs in resistance extraction",
    ),
    ToolVersionConstraint(
        id='KLAYOUT_03013_FIXES',
        tool=Tool.KLAYOUT,
        specifier='>= 0.30.13',
        reason="0.30.13 fixes slow terminal lookup, neighborhood-visitor memory leaks "
               "and resistance-extraction crashes. Upgrading is recommended",
        severity=Severity.WARNING,
    ),
    ToolVersionConstraint(
        id='FASTERCAP_BASELINE',
        tool=Tool.FASTERCAP,
        specifier='>= 6.2.1',
        reason="the version the integration tests are run against",
        severity=Severity.WARNING,
    ),
    ToolVersionConstraint(
        id='MAGIC_SIDEWALL_DEFINITION',
        tool=Tool.MAGIC,
        specifier='>= 8.3.693',
        reason="8.3.693 removes the extra halving of `sidewall` and "
               "`defaultsidewall` coefficients so the two directed edge visits "
               "sum to the full pair value. Earlier versions can report half "
               "the sidewall capacitance. See "
               "https://github.com/RTimothyEdwards/magic/commit/9fd4ee57386c08346b20389a55e4eb9d32553979",
    ),
)


def applicable_constraints(tool: Tool,
                           pdk: Optional[PDK] = None) -> List[ToolVersionConstraint]:
    return [c for c in TOOL_VERSION_CONSTRAINTS
            if c.tool == tool and c.applies_to(pdk)]


def effective_version_range(tool: Tool,
                            pdk: Optional[PDK] = None,
                            severity: Optional[Severity] = None) -> SpecifierSet:
    """The conjunction of applicable constraints, optionally limited to one severity."""
    return SpecifierSet(','.join(c.specifier for c in applicable_constraints(tool, pdk)
                                if severity is None or c.severity == severity))


def check_tool_versions(exe_path_by_tool: Dict[Tool, str],
                        pdk: Optional[PDK] = None,
                        mode: VersionCheckMode = VersionCheckMode.ON,
                        klayout_python_version: Optional[str] = None) -> bool:
    """
    Report the version of every tool a run will use against its constraints.

    Returns False when a constraint was violated that the mode treats as an
    error, so that the caller can refuse the run. When supplied, the in-process
    KLayout Python version is checked independently of the executable.
    """
    if mode == VersionCheckMode.OFF or (not exe_path_by_tool and klayout_python_version is None):
        return True

    rule('Tool versions')

    found_errors = False
    rows: List[Tuple[str, str, str, str]] = []
    detected: List[Tuple[Tool, str, Optional[Version], str]] = []
    for tool, exe_path in exe_path_by_tool.items():
        label = 'KLayout executable' if tool == Tool.KLAYOUT else tool.value
        detected.append((tool, label, tool.detect_version(exe_path), f'{exe_path} {tool.version_argument}'))
    if klayout_python_version is not None:
        try:
            module_version = Version(klayout_python_version)
        except InvalidVersion:
            module_version = None
        detected.append((Tool.KLAYOUT, 'KLayout Python module', module_version, 'klayout.db.__version__'))

    for tool, label, version, source in detected:
        constraints = applicable_constraints(tool, pdk)
        rows.append((label, 'unknown' if version is None else str(version),
                     str(effective_version_range(tool, pdk, Severity.ERROR)) or 'any',
                     str(effective_version_range(tool, pdk, Severity.WARNING)) or 'none'))

        for constraint in constraints:
            debug(f"{constraint.id}: {label} {constraint.specifier} — {constraint.reason}")

        if version is None:
            if constraints:
                warning(f"Can't determine the {label} version from '{source}', "
                        f"so its version requirements stay unchecked")
            continue

        for constraint in constraints:
            if constraint.is_satisfied_by(version):
                continue
            message = (f"{label} {version} does not satisfy "
                       f"{constraint.specifier} ({constraint.id}): {constraint.reason}")
            if constraint.severity == Severity.ERROR and mode == VersionCheckMode.ON:
                error(message)
                found_errors = True
            else:
                warning(message)

    header = ('Tool', 'Found', 'Required', 'Recommended')
    widths = [max(len(cell) for cell in column)
              for column in zip(header, *rows)]
    for row in (header, *rows):
        subproc('  '.join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip())

    return not found_errors
