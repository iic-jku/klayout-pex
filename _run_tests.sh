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

# Usage: run_tests <pattern>
# Example:  run_tests "not slow"
function run_tests() {
    PATTERN="$1"

    DIR=$(dirname -- $(realpath ${BASH_SOURCE}))

    mkdir -p "$DIR"/build

    ALLURE_RESULTS_PATH="$DIR/build/allure-results"
    ALLURE_REPORT_PATH="$DIR/build/allure-report"
    COVERAGE_PATH="$DIR/build/coverage-results"

    rm -rf "$ALLURE_RESULTS_PATH"
    rm -rf "$ALLURE_REPORT_PATH"
    rm -rf "$COVERAGE_PATH"

    set -x
    set -e

    poetry run coverage run -m pytest -m "$PATTERN" \
        --alluredir "$ALLURE_RESULTS_PATH" \
        --color no

    poetry run coverage html --directory "$COVERAGE_PATH"

    allure generate \
        --single-file "$ALLURE_RESULTS_PATH" \
        --output "$ALLURE_REPORT_PATH" \
        --clean

    if [[ -z "$RUNNER_OS" ]] && [[ -d "/Applications/Safari.app" ]]
    then
        open -a Safari "$ALLURE_REPORT_PATH"/index.html
        open -a Safari "$COVERAGE_PATH"/index.html
    fi
}
