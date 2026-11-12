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

"""Apply shared capacitance policies to analytical extraction results."""

from dataclasses import replace
from typing import Collection, Optional

from .extraction_results import ExtractionSummary, NetCoupleKey
from ..netlist.coupling import CouplingPolicy, CouplingPolicyError, ground_capacitances
from ..types import NetName


def apply_coupling_policy(summary: ExtractionSummary,
                          policy: CouplingPolicy,
                          reference_net_name: NetName,
                          substrate_net_name: Optional[NetName] = None,
                          floating_net_names: Collection[NetName] = ()) -> ExtractionSummary:
    """Preserve extraction metadata while applying the shared grounding contract."""
    if CouplingPolicy(policy) == CouplingPolicy.COUPLED:
        return summary
    capacitances = ground_capacitances(
        {(pair.net1, pair.net2): value for pair, value in summary.capacitances.items()},
        reference_net_name,
        net_by_node=summary.net_by_node,
        floating_net_names=floating_net_names,
        resistive_nodes={node for pair in summary.resistances for node in (pair.net1, pair.net2)},
        reference_net_names=() if substrate_net_name is None else (substrate_net_name,),
        protected_net_names=set(summary.label_ports) | set(summary.exclusion_ports))
    return replace(summary, capacitances={NetCoupleKey(*pair): value for pair, value in capacitances.items()})
