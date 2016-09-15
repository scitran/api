#!/usr/bin/env bash
set -e

unset CDPATH
cd "$( dirname "${BASH_SOURCE[0]}" )/../.."

SCITRAN_RUN_LINT=${SCITRAN_RUN_LINT:-"true"}

if [ "$SCITRAN_RUN_LINT" == "true" ]; then
    ./test/bin/lint.sh api
fi

./test/bin/run-unit-tests.sh

clean_up () {
  kill $API_PID || true
  wait 2> /dev/null
  # Report on unit tests and integration tests separately
  # Only submit integration test coverage to coveralls
  coverage report -m
  rm .coverage
  coverage combine
  coverage report -m
}

trap clean_up EXIT

API_BASE_URL="http://localhost:8081/api"
SCITRAN_PERSISTENT_DB_PORT=${SCITRAN_PERSISTENT_DB_PORT:-"9001"}
SCITRAN_PERSISTENT_DB_URI=${SCITRAN_PERSISTENT_DB_URI:-"mongodb://localhost:$SCITRAN_PERSISTENT_DB_PORT/scitran"}
SCITRAN_PERSISTENT_PATH=`mktemp -d`
SCITRAN_PERSISTENT_DATA_PATH="$SCITRAN_PERSISTENT_PATH/data"

uwsgi --http "localhost:8081" --master --http-keepalive \
  --so-keepalive --add-header "Connection: Keep-Alive" \
  --processes 1 --threads 1 \
  --enable-threads \
  --wsgi-file bin/api.wsgi \
  --die-on-term \
  --logformat '%(addr) - %(user) [%(ltime)] "%(method) %(uri) %(proto)" %(status) %(size) "%(referer)" "%(uagent)" request_id=%(request_id)' \
  --env "SCITRAN_PERSISTENT_DB_URI=$SCITRAN_PERSISTENT_DB_URI" \
  --env "SCITRAN_PERSISTENT_PATH=$SCITRAN_PERSISTENT_PATH" \
  --env "SCITRAN_PERSISTENT_DATA_PATH=$SCITRAN_PERSISTENT_DATA_PATH" \
  --env 'SCITRAN_RUNTIME_COVERAGE=true' &
API_PID=$!

./test/bin/run-integration-tests.sh \
    "$API_BASE_URL" \
    "$SCITRAN_PERSISTENT_DB_URI"
