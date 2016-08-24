set -e

unset CDPATH
cd "$( dirname "${BASH_SOURCE[0]}" )/../.."

echo "Checking for files with DOS encoding:"
! find * -path "virtualenv" -prune -o -path "persisten" -prune -o \
  -type f -exec file {} \; | grep -I "with CRLF line terminators"

echo "Checking for files with windows style newline:"
! find * -path "virtualenv" -prune -o -path "persisten" -prune -o -type f \
  -exec grep -rI $'\r' {} \+

PYTHONPATH="$( pwd )" py.test test/unit_tests/python
