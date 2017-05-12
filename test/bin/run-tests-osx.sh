#!/usr/bin/env bash

set -e

unset CDPATH
cd "$( dirname "${BASH_SOURCE[0]}" )/../.."

set -a
# Use port 9003 to hopefully avoid conflicts
SCITRAN_RUNTIME_PATH=${SCITRAN_RUNTIME_PATH:-"$( pwd )/runtime"}
SCITRAN_PERSISTENT_DB_PORT=9003
SCITRAN_PERSISTENT_DB_URI="mongodb://localhost:$SCITRAN_PERSISTENT_DB_PORT/integration-tests"
SCITRAN_PERSISTENT_DB_LOG_URI=${SCITRAN_PERSISTENT_DB_LOG_URI:-"mongodb://localhost:$SCITRAN_PERSISTENT_DB_PORT/logs"}
SCITRAN_PERSISTENT_PATH="$( mktemp -d )"
SCITRAN_CORE_DRONE_SECRET=${SCITRAN_CORE_DRONE_SECRET:-$( openssl rand -base64 32 )}

clean_up () {
  kill $API_PID || true
  wait 2> /dev/null
  rm -rf "$SCITRAN_PERSISTENT_PATH"

  # NOTE on omit: cross-site feature unused and planned for removal
  local OMIT="--omit api/centralclient.py"
  echo -e "\nUNIT TEST COVERAGE:"
  coverage report $OMIT --skip-covered

  coverage combine
  echo -e "\nOVERALL COVERAGE:"
  coverage report $OMIT --show-missing
  coverage html $OMIT
}

trap clean_up EXIT

./bin/install-dev-osx.sh

source $SCITRAN_RUNTIME_PATH/bin/activate # will fail with `set -u`

# Install Node.js
if [ ! -f "$SCITRAN_RUNTIME_PATH/bin/node" ]; then
    echo "Installing Node.js"
    NODE_URL="https://nodejs.org/dist/v6.10.2/node-v6.10.2-darwin-x64.tar.gz"
    curl $NODE_URL | tar xz -C $VIRTUAL_ENV --strip-components 1
fi

# Install testing dependencies
echo "Installing testing dependencies"
pip install --no-cache-dir -r "test/integration_tests/requirements-integration-test.txt"

./test/bin/lint.sh api

SCITRAN_CORE_DRONE_SECRET=$SCITRAN_CORE_DRONE_SECRET \
  ./test/bin/run-unit-tests.sh

SCITRAN_RUNTIME_PORT=8081 \
    SCITRAN_CORE_DRONE_SECRET="$SCITRAN_CORE_DRONE_SECRET" \
    SCITRAN_RUNTIME_COVERAGE="true" \
    ./bin/run-dev-osx.sh -T -U -I &
API_PID=$!

./test/bin/run-integration-tests.sh \
    "http://localhost:8081/api" \
    "$SCITRAN_PERSISTENT_DB_URI" \
    "$SCITRAN_PERSISTENT_DB_LOG_URI" \
    "$SCITRAN_CORE_DRONE_SECRET"
