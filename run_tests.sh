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

# REPORT_PATH=$DIR/build/kpex_test_report.html
# poetry run pytest --html=$REPORT_PATH --self-contained-html

RESULTS_PATH=$DIR/build/allure-results
REPORT_PATH=$DIR/build/allure-report
poetry run pytest --alluredir $RESULTS_PATH --color no
allure generate --single-file $RESULTS_PATH --output $REPORT_PATH --clean

open -a Safari $REPORT_PATH/index.html
