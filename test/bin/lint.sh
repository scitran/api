#!/usr/bin/env bash

set -eu

unset CDPATH
cd "$( dirname "${BASH_SOURCE[0]}" )/../.."

echo "Running pylint ..."
# TODO: Enable Refactor and Convention reports
pylint --reports=no --disable=C,R "$@"

echo "Checking for files with DOS encoding:"
! find * -path "runtime" -prune -o -path "persistent" -prune -o \
  -type f -exec file {} \; | grep -I "with CRLF line terminators"

echo "Checking for files with windows style newline:"
! find * -path "runtime" -prune -o -path "persistent" -prune -o -type f \
  -exec grep -rI $'\r' {} \+

#echo
#
#echo "Running pep8 ..."
#pep8 --max-line-length=150 --ignore=E402 "$@"
