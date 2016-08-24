#!/usr/bin/env bash

set -eu

unset CDPATH
cd "$( dirname "${BASH_SOURCE[0]}" )/../.."

echo "Running pylint ..."
# TODO: Enable Refactor and Convention reports
pylint --reports=no --disable=C,R "$@"

#echo
#
#echo "Running pep8 ..."
#pep8 --max-line-length=150 --ignore=E402 "$@"
