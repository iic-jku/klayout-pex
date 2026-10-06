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
Translation of external scene descriptions into an unresolved ``PEX25DFile``.

The CLI exposes this operation as ``pex25d import``. Importers are plugins in the
``klayout_pex.importers.v1`` entry-point group; the built-in ``openrcx-uf`` is a stub.
Resolving and validating the result stay with the caller.
"""

from __future__ import annotations

from typing import *

from ..plugin_api.v1 import ImporterError, ImporterUnavailable, PEX25DImporter
from . import protobuf

if TYPE_CHECKING:
    from ..plugin.importer_registry import ImporterRegistry
    from klayout_pex_protobuf.kpex.pex25d.pex25d_file_pb2 import PEX25DFile

    from .diagnostics import DiagnosticsReport


class ImporterExecutionError(ImporterError):
    """An importer crashed or returned no PEX25DFile; any original exception is the cause."""


def import_file(input_file_path: str,
                source: str,
                *,
                supporting_files: Optional[Mapping[str, str]] = None,
                options: Optional[Mapping[str, Any]] = None,
                report: Optional[DiagnosticsReport] = None,
                registry: Optional[ImporterRegistry] = None) -> PEX25DFile:
    """
    Import ``input_file_path`` with the importer ``source`` as an unresolved PEX25DFile.

    ``source`` is an importer entry-point name or a qualified ``distribution:name``.
    Supporting-file keys and options are defined by the importer, which validates
    them. Pass a registry to reuse its metadata snapshot across multiple imports.

    ImporterError, NotImplementedError and OSError pass through unchanged; unexpected
    exceptions, and results that are not a PEX25DFile, become ImporterExecutionError.
    """
    registry = registry if registry is not None else importer_registry()
    backend = registry.load(source)
    provider = registry.get_info(source).qualified_name
    try:
        result = backend.import_file(input_file_path,
                                     supporting_files=supporting_files,
                                     options=options,
                                     report=report)
    except (ImporterError, NotImplementedError, OSError):
        raise
    except Exception as exc:
        raise ImporterExecutionError(
            f"Importer '{provider}' crashed: {type(exc).__name__}: {exc}") from exc

    if not isinstance(result, protobuf.pex25d_file_pb2().PEX25DFile):
        raise ImporterExecutionError(
            f"Importer '{provider}' returned {type(result).__name__}, not a PEX25DFile")
    return result


def importer_registry() -> ImporterRegistry:
    """Discover installed importers alongside the built-in implementations."""
    from ..plugin.importer_registry import ImporterRegistry
    return ImporterRegistry({
        'openrcx-uf': create_openrcx_uf_importer,
    })


def create_openrcx_uf_importer() -> PEX25DImporter:
    """OpenRCX Universal Pattern Format input: a stub, not implemented yet.

    Imports raise NotImplementedError; ``klayout_pex/openrcx/pex25d_importer.py``
    holds the template for the implementation.
    """
    from ..openrcx.pex25d_importer import OpenRCXUFImporter
    return OpenRCXUFImporter()
