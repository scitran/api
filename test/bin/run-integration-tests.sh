#!/usr/bin/env bash
set -e

unset CDPATH
cd "$( dirname "${BASH_SOURCE[0]}" )/../.."

USAGE="
    Usage:\n
    $0 <api-base-url> <mongodb-uri>\n
    \n
"

if [ "$#" -eq 2 ]; then
  SCITRAN_SITE_API_URL=$1
  MONGODB_URI=$2
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

SCITRAN_PERSISTENT_DB_URI="$MONGODB_URI" \
  python "bin/bootstrap.py" \
  "test/integration_tests/bootstrap-data.json"

BASE_URL="$SCITRAN_SITE_API_URL" \
    MONGO_PATH="$MONGODB_URI" \
    py.test test/integration_tests/python

# Have to change into definitions directory to resolve
# relative $ref's in the jsonschema's
pushd raml/schemas/definitions
abao ../../api.raml "--server=$SCITRAN_SITE_API_URL" "--hookfiles=../../../test/integration_tests/abao/abao_test_hooks.js"
popd

newman run test/integration_tests/postman/integration_tests.postman_collection -e test/integration_tests/postman/environments/integration_tests.postman_environment
