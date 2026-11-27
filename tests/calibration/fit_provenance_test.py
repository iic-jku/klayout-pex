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

"""Fit reports preserve each case's source technology and numerical result."""

from pathlib import Path

import pytest

from kpex.calibration.artifacts import read_message, sha256_file, write_message
from kpex_protobuf.kpex.calibration.length_fit_pb2 import CalibrationLengthFitReport
from kpex_protobuf.kpex.calibration.overlap_fit_pb2 import CalibrationOverlapFitReport
from kpex_protobuf.kpex.calibration.preparation_pb2 import CalibratedTechnology


@pytest.mark.parametrize('kind', ['length', 'overlap'])
def test_fit_preserves_technology_for_every_case(tmp_path: Path, kind: str):
    source = CalibratedTechnology(name='test', resolved_technology_sha256='1' * 64,
                                 physical_stack_sha256='2' * 64)
    source.selection.technology_id = 'test-catalog'
    source.selection.resolved_technology_sha256 = source.resolved_technology_sha256
    if kind == 'length':
        report = CalibrationLengthFitReport(schema_version=1)
        fit = report.fits.add(case_ids=['training', 'holdout', 'unusable'])
        fit.series.physical_stack_sha256 = source.physical_stack_sha256
        sources = fit.case_technologies
    else:
        report = CalibrationOverlapFitReport(schema_version=1, physical_stack_sha256=source.physical_stack_sha256)
        fit = report.fit
        sources = report.case_technologies
    fit.status = fit.REJECTED
    fit.training_samples.add(case_id='training', residual_f=3e-18)
    fit.validation_samples.add(case_id='holdout', residual_f=-4e-18)
    fit.diagnostics.append('Rejection survives serialization')
    sources['training'].CopyFrom(source)
    source.resolved_technology_sha256 = '3' * 64
    source.selection.resolved_technology_sha256 = source.resolved_technology_sha256
    sources['holdout'].CopyFrom(source)
    if kind == 'length':
        # Unusable cases need provenance even when they have no fitted samples.
        sources['unusable'].CopyFrom(source)
    path = write_message(tmp_path / 'fit.pb.json', report)
    before = sha256_file(path)
    assert read_message(path, type(report)()) == report
    assert sha256_file(path) == before
