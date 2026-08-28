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
The PEX25D Module
-----------------

Support for the **PEX25D** interchange format for 2.5D parasitic extraction
(see https://github.com/iic-jku/klayout-pex/issues/184).

The pipeline is::

    PEX25D (text) –[reader]→ PEX25DFile (protobuf) –[resolver]→ PEX25DScene (protobuf) –[adapter]→ solver

Dependency rule
~~~~~~~~~~~~~~~

This package depends on ``protobuf`` only — no ``klayout`` import, directly or
transitively. That is what lets the standalone ``pex25d`` tool be installed and
run by other groups as a reference validator, without dragging in the whole LVS
machinery. Generating PEX25D from a layout does need that machinery, and lives
in :mod:`klayout_pex.klayout.pex25d_builder` instead.
"""

from .artifact import (
    ArtifactKind,
    ArtifactFormat,
    ArtifactSpec,
    STDIO_PATH,
    infer_artifact_spec,
)
from .diagnostics import (
    DiagnosticsFormat,
    DiagnosticsReport,
    ExitCode,
)
from .validator import validate
