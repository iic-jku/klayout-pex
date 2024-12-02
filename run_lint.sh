#! /bin/bash

DIR=$(dirname -- $(realpath ${BASH_SOURCE}))

export PYTHONPATH=$DIR/:$DIR/build/python:${PYTHONPATH}

mkdir -p $DIR/build

RESULTS_PATH=$DIR/build/pylint-results.json
REPORT_PATH=$DIR/build/pylint-report.html
pylint --rcfile $DIR/.pylintrc \
       --output-format json2 \
       --ignore build \
	$DIR/kpex > $RESULTS_PATH

pylint-json2html -f jsonextended $RESULTS_PATH -o $REPORT_PATH

open -a Safari $REPORT_PATH
