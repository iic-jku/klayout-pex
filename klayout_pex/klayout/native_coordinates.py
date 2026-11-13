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

"""Native grid interval safe for KLayout geometry operations used by exports."""

NATIVE_COORDINATE_MIN = -(1 << 31)
NATIVE_COORDINATE_MAX = (1 << 31) - 1


def is_supported_native_coordinate(value: int) -> bool:
    """Exclude endpoints that can hang booleans or lose genuine interactions.

    KLayout 0.30.13 endpoint reproducers and adjacent interior controls are
    recorded in https://github.com/KLayout/klayout/issues/2552. This bound
    describes observed behavior, without assuming its native implementation cause.
    """
    return NATIVE_COORDINATE_MIN < value < NATIVE_COORDINATE_MAX
