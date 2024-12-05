#! /bin/bash
##
## --------------------------------------------------------------------------------
## SPDX-FileCopyrightText: 2024 Martin Jan Köhler and Harald Pretl
## Johannes Kepler University, Institute for Integrated Circuits.
##
## This file is part of KPEX 
## (see https://github.com/martinjankoehler/klayout-pex).
##
## This program is free software: you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation, either version 3 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with this program. If not, see <http://www.gnu.org/licenses/>.
## SPDX-License-Identifier: GPL-3.0-or-later
## --------------------------------------------------------------------------------
##

DIR=$(dirname -- $(realpath ${BASH_SOURCE}))

export PYTHONPATH=$DIR/:$DIR/build/python:${PYTHONPATH}

mkdir -p $DIR/build

ALLURE_RESULTS_PATH=$DIR/build/allure-results
ALLURE_REPORT_PATH=$DIR/build/allure-report
COVERAGE_PATH=$DIR/build/coverage-results

poetry run pytest \
	--alluredir $ALLURE_RESULTS_PATH \
	--color no \
	--cov=$COVERAGE_PATH \
	--cov-report=html

allure generate \
	--single-file $ALLURE_RESULTS_PATH \
	--output $ALLURE_REPORT_PATH \
	--clean

if [[ -z "$RUNNER_OS" ]] && [[ -d "/Applications/Safari.app" ]]
then
    open -a Safari $ALLURE_REPORT_PATH/index.html
fi

