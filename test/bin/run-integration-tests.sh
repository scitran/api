#!/usr/bin/env bash
set -eu

unset CDPATH
cd "$( dirname "${BASH_SOURCE[0]}" )/../.."

rm -f .coverage.integration-tests

USAGE="
    Usage:\n
    $0 <api-base-url> <mongodb-uri> <drone-secret>\n
    \n
"

if [ "$#" -eq 3 ]; then
  SCITRAN_SITE_API_URL=$1
  MONGODB_URI=$2
  SCITRAN_CORE_DRONE_SECRET=$3
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

echo "Bootstrapping test data..."
# Don't call things bootstrap.json because that's in root .gitignore

PYTHONPATH="$( pwd )" \
SCITRAN_PERSISTENT_DB_URI="$MONGODB_URI" \
  python "bin/load_users_drone_secret.py" \
  --secret "$SCITRAN_CORE_DRONE_SECRET" \
  "$SCITRAN_SITE_API_URL" \
  "test/integration_tests/bootstrap-test-accounts.json"

# Remove __pycache__ directory for issue with __file__ attribute
# Due to running the tests on the host creating bytecode files
# Which have a mismatched __file__ attribute when loaded in docker container
rm -rf test/integration_tests/python/__pycache__

PYTHONPATH="$( pwd )" \
    SCITRAN_PERSISTENT_DB_URI="$MONGODB_URI" \
    python test/bin/inject_api_key.py admin@user.com \
    "XZpXI40Uk85eozjQkU1zHJ6yZHpix+j0mo1TMeGZ4dPzIqVPVGPmyfeK"

BASE_URL="$SCITRAN_SITE_API_URL" \
    MONGO_PATH="$MONGODB_URI" \
    py.test test/integration_tests/python

PATH=$(npm bin):$PATH

# Allow us to require modules from package.json,
# since abao_test_hooks.js is not being called from the package directory
integration_test_node_modules="$( pwd )/node_modules/scitran-core-integration-tests/node_modules"

newman run test/integration_tests/postman/integration_tests.postman_collection -e test/integration_tests/postman/environments/integration_tests.postman_environment

# Have to change into definitions directory to resolve
# relative $ref's in the jsonschema's
pushd raml/schemas/definitions
# NODE_PATH="$integration_test_node_modules"
NODE_PATH="$integration_test_node_modules" abao ../../api.raml "--server=$SCITRAN_SITE_API_URL" "--hookfiles=../../../test/integration_tests/abao/abao_test_hooks.js"
popd
