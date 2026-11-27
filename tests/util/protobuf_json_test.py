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

"""Schema validation also applies to typed protobuf Any payloads."""

import json

import pytest
from google.protobuf.any_pb2 import Any
from google.protobuf.json_format import MessageToJson, ParseError

from kpex.util.protobuf_json import parse_protobuf_json
from kpex_protobuf.kpex.fastercap.calibration_pb2 import CalibrationStatistics


@pytest.mark.parametrize('mutation', ['unknown-field', 'unknown-type', 'alias', 'fractional', 'overflow', 'negative'])
def test_any_payload_is_strictly_schema_checked(mutation: str):
    message = Any()
    message.Pack(CalibrationStatistics(input_panels=10))
    data = json.loads(MessageToJson(message, preserving_proto_field_name=True))
    payload = data
    if mutation == 'unknown-field':
        payload['unrecognized'] = 1
    elif mutation == 'unknown-type':
        payload['@type'] = 'type.googleapis.com/unrecognized.Message'
    elif mutation == 'alias':
        payload['inputPanels'] = 10
    else:
        payload['input_panels'] = {'fractional': 'FRACTION', 'overflow': str(2**64), 'negative': '-1'}[mutation]
    # Decimal token rounds to an integer in a float parser. Strict protobuf
    # checking must also inspect the message inside Any with exact decimals.
    text = json.dumps(data).replace('"FRACTION"', '10.0000000000000000001')
    with pytest.raises(ParseError):
        parse_protobuf_json(text, Any())
