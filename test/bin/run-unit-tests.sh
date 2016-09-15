set -e

unset CDPATH
cd "$( dirname "${BASH_SOURCE[0]}" )/../.."

# Remove __pycache__ directory for issue with __file__ attribute
# Due to running the tests on the host creating bytecode files
# Which have a mismatched __file__ attribute when loaded in docker container
rm -rf test/unit_tests/python/__pycache__

rm -f .coverage

PYTHONPATH="$( pwd )"  py.test --cov=api test/unit_tests/python
