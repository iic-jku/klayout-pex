#! /bin/bash

DIR=$(dirname -- $(realpath ${BASH_SOURCE}))

export PYTHONPATH=$DIR/:$DIR/build/python:${PYTHONPATH}

poetry run pytest
#/usr/bin/env python3 -m kpex.test $*
