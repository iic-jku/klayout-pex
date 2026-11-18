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

"""Schema-based JSON checks for lossy numeric coercion and ambiguous field aliases."""

from __future__ import annotations

from decimal import Decimal
import json
from typing import Any, Dict, TypeVar

from google.protobuf.descriptor import Descriptor, FieldDescriptor
from google.protobuf.json_format import Parse, ParseError
from google.protobuf.message import Message


MessageType = TypeVar('MessageType', bound=Message)


def _check_representation(value: Any, descriptor: Descriptor):
    if not isinstance(value, dict):
        return  # The protobuf parser supplies the schema/type diagnostic.
    names: Dict[str, FieldDescriptor] = {
        name: field for field in descriptor.fields for name in (field.name, field.json_name)
    }
    seen = set()
    for name, item in value.items():
        field = names.get(name)
        if field is None:
            continue  # Unknown fields are rejected by Parse, never ignored.
        if field.number in seen:
            raise ParseError(f'Field {descriptor.full_name}.{field.name} occurs through multiple JSON aliases')
        seen.add(field.number)
        if field.message_type is not None and field.message_type.GetOptions().map_entry:
            values = list(item.values()) if isinstance(item, dict) else []
            member = field.message_type.fields_by_name['value']
        else:
            values = item if field.is_repeated and isinstance(item, list) else [item]
            member = field
        for scalar in values:
            if member.type == FieldDescriptor.TYPE_ENUM and isinstance(scalar, bool):
                raise ParseError(f'Boolean is not an enum value for {descriptor.full_name}.{field.name}')
            integer_type = member.type in (
                FieldDescriptor.TYPE_ENUM, FieldDescriptor.TYPE_INT32, FieldDescriptor.TYPE_INT64,
                FieldDescriptor.TYPE_UINT32, FieldDescriptor.TYPE_UINT64, FieldDescriptor.TYPE_SINT32,
                FieldDescriptor.TYPE_SINT64, FieldDescriptor.TYPE_FIXED32, FieldDescriptor.TYPE_FIXED64,
                FieldDescriptor.TYPE_SFIXED32, FieldDescriptor.TYPE_SFIXED64)
            if integer_type and isinstance(scalar, Decimal) and (
                    not scalar.is_finite() or scalar != scalar.to_integral_value()):
                raise ParseError(f'Nonintegral number for {descriptor.full_name}.{field.name}')
            if member.message_type is not None:
                _check_representation(scalar, member.message_type)


def parse_protobuf_json(text: str, message: MessageType) -> MessageType:
    """Use the protobuf schema and reject ambiguous representations it may coerce.

    Parse runs first to diagnose unknown fields, duplicate keys, oneof conflicts,
    types and recursion limits. Exact decimal inspection then catches fractional
    integer/enum tokens even when float parsing rounded or truncated them.
    Requiredness and physical rules remain domain checks.
    """
    parsed = Parse(text, message, ignore_unknown_fields=False)
    _check_representation(json.loads(text, parse_float=Decimal), message.DESCRIPTOR)
    return parsed
