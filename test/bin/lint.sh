#!/usr/bin/env bash

set -eu

unset CDPATH
cd "$( dirname "${BASH_SOURCE[0]}" )/../.."

echo "Checking for files with DOS encoding:"
(! git ls-files | xargs file | grep -I "with CRLF line terminators")

echo "Checking for files with windows-style newlines:"
(! git ls-files | xargs grep -I $'\r')

echo $?

echo keeps running

exit 0

echo "Running pylint ..."
# TODO: Enable Refactor and Convention reports
pylint --reports=no --disable=C,R api

#echo
#
#echo "Running pep8 ..."
#pep8 --max-line-length=150 --ignore=E402 api
