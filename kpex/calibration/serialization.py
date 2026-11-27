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

"""Read saved calibration versions without rewriting their hashed evidence."""

from typing import TypeVar

from google.protobuf.json_format import ParseError
from google.protobuf.message import Message

from .validation import CalibrationError
from ..util.protobuf_json import parse_protobuf_json
from kpex_protobuf.kpex.calibration import qualification_pb2, solving_pb2, length_fit_pb2, overlap_fit_pb2
from kpex_protobuf.kpex.calibration.v1 import qualification_pb2 as qualification_v1
from kpex_protobuf.kpex.calibration.v1 import solving_pb2 as solving_v1
from kpex_protobuf.kpex.calibration.v1 import length_fit_pb2 as length_fit_v1
from kpex_protobuf.kpex.calibration.v1 import overlap_fit_pb2 as overlap_fit_v1
from kpex_protobuf.kpex.calibration.v2 import length_fit_pb2 as length_fit_v2
from kpex_protobuf.kpex.calibration.v2 import overlap_fit_pb2 as overlap_fit_v2
from kpex_protobuf.kpex.fastercap.calibration_pb2 import CalibrationControls, CalibrationStatistics

MessageType = TypeVar('MessageType', bound=Message)


def _statistics(source: Message, destination: Message):
    statistics = CalibrationStatistics()
    for field in statistics.DESCRIPTOR.fields:
        if field.name in source.DESCRIPTOR.fields_by_name and source.HasField(field.name):
            setattr(statistics, field.name, getattr(source, field.name))
    if statistics.ListFields():
        destination.solver_statistics.Pack(statistics)


def _convert_v1(source: Message, destination: Message) -> Message:
    # Unchanged fields retain their wire IDs and types. Removed backend fields are
    # reserved in v2 and copied explicitly into typed payloads below.
    destination.ParseFromString(source.SerializeToString())
    destination.DiscardUnknownFields()
    destination.schema_version = 2
    if isinstance(source, solving_v1.CalibrationRunManifest):
        controls = CalibrationControls.FromString(source.options.fastercap.SerializeToString())
        destination.options.solver_controls.Pack(controls)
    elif isinstance(source, solving_v1.CalibrationCollection):
        for old, new in zip(source.cases, destination.cases):
            _statistics(old, new)
    elif isinstance(source, qualification_v1.CalibrationQualificationReport):
        destination.study.schema_version = 2
        for old_case, new_case in zip(source.cases, destination.cases):
            for old_refinement, new_refinement in zip(old_case.refinements, new_case.refinements):
                for old_level, new_level in zip(old_refinement.levels, new_refinement.levels):
                    _statistics(old_level, new_level)
    elif not isinstance(source, qualification_v1.CalibrationQualificationStudy):
        raise NotImplementedError(f'Convert saved calibration message {source.DESCRIPTOR.full_name}')
    return destination


def _convert_fit_report(source: Message, destination: Message) -> Message:
    """Preserve old fit decisions while separating identity from source provenance."""
    destination.ParseFromString(source.SerializeToString())
    destination.DiscardUnknownFields()
    destination.schema_version = 3
    if isinstance(destination, length_fit_pb2.CalibrationLengthFitReport):
        for old, new in zip(source.fits, destination.fits):
            case_ids = set(old.case_ids)
            case_ids.update(sample.case_id for sample in (*old.training_samples, *old.validation_samples))
            if old.series.HasField('technology'):
                new.series.physical_stack_sha256 = old.series.technology.physical_stack_sha256
                for case_id in case_ids:
                    new.case_technologies[case_id].CopyFrom(old.series.technology)
    elif isinstance(destination, overlap_fit_pb2.CalibrationOverlapFitReport):
        destination.physical_stack_sha256 = source.technology.physical_stack_sha256
        if source.HasField('technology'):
            for sample in (*source.fit.training_samples, *source.fit.validation_samples):
                destination.case_technologies[sample.case_id].CopyFrom(source.technology)
    else:
        raise NotImplementedError(f'Convert saved fit report {source.DESCRIPTOR.full_name}')
    return destination


def _parse_fit_report(text: str, message: MessageType) -> MessageType:
    older = ({1: length_fit_v1.CalibrationLengthFitReport, 2: length_fit_v2.CalibrationLengthFitReport}
             if isinstance(message, length_fit_pb2.CalibrationLengthFitReport) else
             {1: overlap_fit_v1.CalibrationOverlapFitReport, 2: overlap_fit_v2.CalibrationOverlapFitReport})
    try:
        parsed = parse_protobuf_json(text, type(message)())
    except ParseError as current_error:
        for version, schema in older.items():
            try:
                saved = parse_protobuf_json(text, schema())
            except ParseError:
                continue
            if saved.schema_version == version:
                return _convert_fit_report(saved, message)
        raise current_error
    if parsed.schema_version in older:
        saved = parse_protobuf_json(text, older[parsed.schema_version]())
        return _convert_fit_report(saved, message)
    if parsed.schema_version != 3:
        raise CalibrationError(f'Unsupported calibration fit report version {parsed.schema_version}')
    message.CopyFrom(parsed)
    return message


def parse_calibration_message(text: str, message: MessageType) -> MessageType:
    """Strictly parse artifacts, translating defined older schemas in memory.

    Backend descriptors are imported above so Any payloads are schema-checked by
    protobuf, including their JSON fields. No unknown options or types are ignored.
    Original files remain untouched: callers verify hashes over the saved bytes.
    """
    if isinstance(message, (length_fit_pb2.CalibrationLengthFitReport,
                            overlap_fit_pb2.CalibrationOverlapFitReport)):
        return _parse_fit_report(text, message)
    older = {
        solving_pb2.CalibrationRunManifest: solving_v1.CalibrationRunManifest,
        solving_pb2.CalibrationCollection: solving_v1.CalibrationCollection,
        qualification_pb2.CalibrationQualificationStudy: qualification_v1.CalibrationQualificationStudy,
        qualification_pb2.CalibrationQualificationReport: qualification_v1.CalibrationQualificationReport,
    }.get(type(message))
    if older is None:
        return parse_protobuf_json(text, message)
    try:
        parsed = parse_protobuf_json(text, type(message)())
    except ParseError as current_error:
        try:
            saved = parse_protobuf_json(text, older())
        except ParseError:
            raise current_error
        if saved.schema_version != 1:
            raise CalibrationError('Version-1 calibration fields require schema_version 1')
        return _convert_v1(saved, message)
    if parsed.schema_version == 1:
        # Even a file with no solver controls must conform completely to v1.
        saved = parse_protobuf_json(text, older())
        return _convert_v1(saved, message)
    message.CopyFrom(parsed)
    return message
