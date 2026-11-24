#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX
# (see https://github.com/iic-jku/kpex).
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

"""Validate mandatory format capabilities before interpreting an artifact."""

from __future__ import annotations

from typing import Any, Set

from .diagnostics import Diagnostic, DiagnosticsReport, Severity, Tier
from .protobuf import pex25d_capabilities_pb2, pex25d_scene_pb2


def validate_required_capabilities(message: Any, report: DiagnosticsReport) -> bool:
    """Reject unknown mandatory semantics, including numeric protobuf enum values."""
    before = report.num_errors
    schema = pex25d_capabilities_pb2()
    seen: Set[int] = set()
    for capability in message.required_capabilities:
        if capability != schema.REQUIRED_CAPABILITY_CAPACITANCE_ACCOUNTING:
            report.add(Diagnostic(code='PEX25D-E0280', severity=Severity.ERROR, tier=Tier.SEMANTIC,
                                  message=f'Unsupported required capability {capability}; supported: CAPACITANCE_ACCOUNTING'))
        if capability in seen:
            report.add(Diagnostic(code='PEX25D-E0280', severity=Severity.ERROR, tier=Tier.SEMANTIC,
                                  message=f'Required capability {capability} appears more than once'))
        seen.add(capability)
    is_scene = message.DESCRIPTOR is pex25d_scene_pb2().PEX25DScene.DESCRIPTOR
    has_parts = is_scene and any(region.accounting_part_id or region.accounting_regions
                                 for conductor in message.conductors for region in conductor.regions)
    if (message.HasField('capacitance_accounting') or has_parts) and \
            schema.REQUIRED_CAPABILITY_CAPACITANCE_ACCOUNTING not in seen:
        report.add(Diagnostic(code='PEX25D-E0280', severity=Severity.ERROR, tier=Tier.SEMANTIC,
                              message='Capacitance accounting requires REQUIRES CAPABILITIES CAPACITANCE_ACCOUNTING in the header'))
    return report.num_errors == before
