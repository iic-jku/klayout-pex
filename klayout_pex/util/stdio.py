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
The standard streams of the command line tools
"""

import codecs
import io
import sys


def use_utf8_stdio():
    """
    Makes stdout and stderr write UTF-8, as Python does by default from 3.15 on (PEP 686).

    A console takes any character anyway, but a pipe or a file gets the encoding of the locale,
    e.g. cp1252 on Windows, which has no ≥ or ∈ of the help and the messages:
    stdout fails on them (UnicodeEncodeError), stderr writes them as \\u2265.
    """
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper) and codecs.lookup(stream.encoding).name != 'utf-8':
            stream.reconfigure(encoding='utf-8', errors=stream.errors)
