#! /bin/bash

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
