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
from typing import Any, TYPE_CHECKING

__all__ = ('KLayoutExtractedLayerInfo', 'KLayoutExtractionContext')

if TYPE_CHECKING:
    from .lvsdb_extractor import KLayoutExtractedLayerInfo, KLayoutExtractionContext


def __getattr__(name: str) -> Any:
    # Reading saved calibration dimensions needs native coordinate bounds, not
    # the layout database bindings. Preserve the existing public imports lazily.
    if name in ('KLayoutExtractedLayerInfo', 'KLayoutExtractionContext'):
        from . import lvsdb_extractor
        return getattr(lvsdb_extractor, name)
    raise AttributeError(f'{__name__} has no attribute {name!r}')
