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

"""Saved fit reports preserve source technologies without claiming a new fit."""

import importlib
from pathlib import Path

import pytest
from google.protobuf.json_format import MessageToJson, ParseError

from kpex.calibration.artifacts import read_message, sha256_file, write_message
from kpex.calibration.serialization import parse_calibration_message
from kpex.calibration.validation import CalibrationError
from kpex_protobuf.kpex.calibration.length_fit_pb2 import CalibrationLengthFitReport
from kpex_protobuf.kpex.calibration.overlap_fit_pb2 import CalibrationOverlapFitReport
from kpex_protobuf.kpex.calibration.preparation_pb2 import CalibratedTechnology


@pytest.mark.parametrize('version', [1, 2])
@pytest.mark.parametrize('kind', ['length', 'overlap'])
def test_saved_fit_preserves_technology_for_every_case(tmp_path: Path, version: int, kind: str):
    module = importlib.import_module(f'kpex_protobuf.kpex.calibration.v{version}.{kind}_fit_pb2')
    source = CalibratedTechnology(name='test', resolved_technology_sha256='1' * 64,
                                 physical_stack_sha256='2' * 64)
    source.selection.technology_id = 'test-catalog'
    source.selection.resolved_technology_sha256 = source.resolved_technology_sha256
    if kind == 'length':
        saved = module.CalibrationLengthFitReport(schema_version=version)
        fit = saved.fits.add(status=module.CalibrationLengthFitResult.REJECTED,
                             case_ids=['training', 'holdout', 'unusable'])
        fit.series.technology.CopyFrom(source)
        fit.training_samples.add(case_id='training', residual_f=3e-18)
        fit.validation_samples.add(case_id='holdout', residual_f=-4e-18)
        fit.diagnostics.append('Existing rejection remains a rejection')
        current = CalibrationLengthFitReport()
    else:
        saved = module.CalibrationOverlapFitReport(schema_version=version, technology=source)
        saved.fit.status = module.CalibrationOverlapFitResult.REJECTED
        saved.fit.training_samples.add(case_id='training', residual_f=3e-18)
        saved.fit.validation_samples.add(case_id='holdout', residual_f=-4e-18)
        saved.fit.diagnostics.append('Existing rejection remains a rejection')
        current = CalibrationOverlapFitReport()
    path = write_message(tmp_path / 'saved.pb.json', saved)
    before = sha256_file(path)
    result = read_message(path, current)
    assert sha256_file(path) == before
    assert result.schema_version == 3
    if kind == 'length':
        fit, = result.fits
        assert fit.series.physical_stack_sha256 == source.physical_stack_sha256
        sources = fit.case_technologies
        assert set(sources) == {'training', 'holdout', 'unusable'}
    else:
        fit = result.fit
        assert result.physical_stack_sha256 == source.physical_stack_sha256
        sources = result.case_technologies
        assert set(sources) == {'training', 'holdout'}
    assert all(technology == source for technology in sources.values())
    assert fit.status == fit.REJECTED
    assert fit.training_samples[0].residual_f == 3e-18
    assert fit.validation_samples[0].residual_f == -4e-18
    assert list(fit.diagnostics) == ['Existing rejection remains a rejection']
    assert parse_calibration_message(MessageToJson(result), type(current)()) == result


@pytest.mark.parametrize('version', [0, 1, 2, 4])
@pytest.mark.parametrize('schema', [CalibrationLengthFitReport, CalibrationOverlapFitReport])
def test_fit_version_cannot_relabel_new_provenance(version: int, schema):
    # Current fields cannot be smuggled into an older schema, and unknown
    # versions must not be mistaken for a supported saved report.
    report = schema(schema_version=version)
    sources = report.fits.add().case_technologies if schema is CalibrationLengthFitReport else report.case_technologies
    sources['case'].resolved_technology_sha256 = '1' * 64
    with pytest.raises((CalibrationError, ParseError)):
        parse_calibration_message(MessageToJson(report), schema())
