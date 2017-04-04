#!/usr/bin/env bash
set -eu

unset CDPATH
cd "$( dirname "${BASH_SOURCE[0]}" )/../.."

rm -f .coverage.integration-tests

USAGE="
    Usage:\n
    $0 <api-base-url> <mongodb-uri> <mongodb-log-uri> <drone-secret>\n
    \n
"

if [ "$#" -eq 4 ]; then
    SCITRAN_SITE_API_URL=$1
    SCITRAN_PERSISTENT_DB_URI=$2
    SCITRAN_PERSISTENT_DB_LOG_URI=$3
    SCITRAN_CORE_DRONE_SECRET=$4
else
    echo "Wrong number of positional arguments"
    echo $USAGE >&2
    exit 1
fi

echo "Connecting to API"
until $(curl --output /dev/null --silent --head --fail "$SCITRAN_SITE_API_URL"); do
    printf '.'
    sleep 1
done

# Remove __pycache__ directory for issue with __file__ attribute
# Due to running the tests on the host creating bytecode files
# Which have a mismatched __file__ attribute when loaded in docker container
rm -rf test/integration_tests/python/__pycache__

PYTHONPATH="$( pwd )" \
SCITRAN_SITE_API_URL="$SCITRAN_SITE_API_URL" \
SCITRAN_PERSISTENT_DB_URI="$SCITRAN_PERSISTENT_DB_URI" \
SCITRAN_PERSISTENT_DB_LOG_URI="$SCITRAN_PERSISTENT_DB_LOG_URI" \
SCITRAN_CORE_DRONE_SECRET="$SCITRAN_CORE_DRONE_SECRET" \
    py.test test/integration_tests/python

# Create resources that Abao relies on:
# - user w/ api key
# - scitran group
# - test-group
# - test-project-1 (+analysis upload)
# - test-session-1 (+analysis upload)
# - test-acquisition-1 (+analysis upload)
# - test-case-gear
# - test-collection-1 (+analysis upload)
SCITRAN_SITE_API_URL="$SCITRAN_SITE_API_URL" \
SCITRAN_CORE_DRONE_SECRET="$SCITRAN_CORE_DRONE_SECRET" \
SCITRAN_PERSISTENT_DB_URI="$SCITRAN_PERSISTENT_DB_URI" \
    python test/integration_tests/abao/load_fixture.py

set +u
# If no VIRTUAL_ENV, make sure /usr/local/bin is in the path
if [ -z "$VIRTUAL_ENV" ]; then
    PATH="/usr/local/bin:$PATH"
fi
set -u

PATH="$(npm bin):$PATH"

npm install test/integration_tests

# Allow us to require modules from package.json,
# since abao_test_hooks.js is not being called from the package directory
integration_test_node_modules="$( pwd )/node_modules/scitran-core-integration-tests/node_modules"

# Have to change into definitions directory to resolve
# relative $ref's in the jsonschema's
pushd raml/schemas/definitions
NODE_PATH="$integration_test_node_modules" abao ../../api.raml "--server=$SCITRAN_SITE_API_URL" "--hookfiles=../../../test/integration_tests/abao/abao_test_hooks.js"
popd
