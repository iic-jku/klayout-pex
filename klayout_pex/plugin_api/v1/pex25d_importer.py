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

"""Version 1 PEX25D importer protocol and its errors."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Optional, Protocol

if TYPE_CHECKING:
    from klayout_pex_protobuf.kpex.pex25d.pex25d_file_pb2 import PEX25DFile

    from ...pex25d.diagnostics import DiagnosticsReport


class ImporterError(RuntimeError):
    """An external scene description could not be imported as PEX25D."""


class ImporterUnavailable(ImporterError):
    """The importer or one of its dependencies is unavailable."""


class PEX25DImporter(Protocol):
    """Translate one external scene description into an unresolved PEX25DFile.

    Resolution and PEX25D validation belong to the caller. Importers preserve
    source references where possible and must report unsupported constructs or
    missing physical information rather than inventing values. They do not run
    a solver or mutate the supplied options or supporting-file mapping.
    """

    def import_file(self,
                    input_file_path: str,
                    *,
                    supporting_files: Optional[Mapping[str, str]] = None,
                    options: Optional[Mapping[str, Any]] = None,
                    report: Optional[DiagnosticsReport] = None) -> PEX25DFile:
        """Read a primary input and optional named supporting files.

        Supporting-file keys are defined by the importer, e.g. ``process_stack``.
        Input paths are interpreted relative to the caller's working directory;
        the importer must not change it. Each call produces one PEX25DFile, so a
        batch of independent patterns remains a batch of separate calls.

        Append diagnostics to ``report`` when supplied. Raise ImporterError for
        an import that cannot complete; do not return a partial file as success.
        NotImplementedError marks what an importer does not implement yet.
        Optional dependencies should be imported only when needed.
        """
        ...


__all__ = ['ImporterError', 'ImporterUnavailable', 'PEX25DImporter']
