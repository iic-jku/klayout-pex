#! /bin/bash

DIR=$(dirname -- $(realpath ${BASH_SOURCE}))

export PYTHONPATH=$DIR/:$DIR/build/python:${PYTHONPATH}
# /usr/bin/env python3 $DIR/kpex/kpex_cli.py $*
/usr/bin/env python3 -m kpex $*
