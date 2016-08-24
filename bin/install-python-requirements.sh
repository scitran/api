#!/usr/bin/env bash
set -e

unset CDPATH
cd "$( dirname "${BASH_SOURCE[0]}" )/.."

pip install -U pip wheel setuptools

pip install -U -r requirements.txt
