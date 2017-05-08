#!/usr/bin/env bash
#
# Run all scripted tests from ubuntu 14.04 or later
#
# Assumes mongo db instance is accessible at localhost, unless
#   SCITRAN_PERSISTENT_DB_URI or SCITRAN_PERSISTENT_DB_LOG_URI specify otherwise.
#
# Forces SCITRAN_CORE_ACCESS_LOG_ENABLED=true
#
# Variables:
#   - See sample.config for options.
#   - SCITRAN_PERSISTENT_DB_URI will cause SCITRAN_PERSISTENT_DB_PORT to be
#     ignored.
#   - SCITRAN_PERSISTENT_DB_LOG_URI will cause SCITRAN_PERSISTENT_DB_PORT to be
#     ignored.

set -e

unset CDPATH
cd "$( dirname "${BASH_SOURCE[0]}" )/../.."

SCITRAN_RUN_LINT=${SCITRAN_RUN_LINT:-"true"}

if [ "$SCITRAN_RUN_LINT" == "true" ]; then
    ./test/bin/lint.sh api
fi

clean_up () {
  kill $API_PID || true
  wait 2> /dev/null

  echo -e "\nUNIT TEST COVERAGE:"
  coverage report --skip-covered

  coverage combine
  echo -e "\nOVERALL COVERAGE:"
  coverage report --show-missing
  coverage html
}

trap clean_up EXIT

API_BASE_URL="http://localhost:8081/api"
SCITRAN_PERSISTENT_DB_PORT=${SCITRAN_PERSISTENT_DB_PORT:-"9001"}
SCITRAN_PERSISTENT_DB_URI=${SCITRAN_PERSISTENT_DB_URI:-"mongodb://localhost:$SCITRAN_PERSISTENT_DB_PORT/scitran"}
SCITRAN_PERSISTENT_DB_LOG_URI=${SCITRAN_PERSISTENT_DB_LOG_URI:-"mongodb://localhost:$SCITRAN_PERSISTENT_DB_PORT/logs"}
SCITRAN_PERSISTENT_PATH=`mktemp -d`
SCITRAN_PERSISTENT_DATA_PATH="$SCITRAN_PERSISTENT_PATH/data"
SCITRAN_CORE_DRONE_SECRET=${SCITRAN_CORE_DRONE_SECRET:-$( openssl rand -base64 32 )}

SCITRAN_CORE_DRONE_SECRET=$SCITRAN_CORE_DRONE_SECRET \
  ./test/bin/run-unit-tests.sh

uwsgi --http "localhost:8081" --master --http-keepalive \
  --so-keepalive --add-header "Connection: Keep-Alive" \
  --processes 1 --threads 1 \
  --enable-threads \
  --wsgi-file bin/api.wsgi \
  --die-on-term \
  --logformat '%(addr) - %(user) [%(ltime)] "%(method) %(uri) %(proto)" %(status) %(size) "%(referer)" "%(uagent)" request_id=%(request_id)' \
  --env "SCITRAN_PERSISTENT_DB_URI=$SCITRAN_PERSISTENT_DB_URI" \
  --env "SCITRAN_PERSISTENT_DB_LOG_URI=$SCITRAN_PERSISTENT_DB_LOG_URI" \
  --env "SCITRAN_PERSISTENT_PATH=$SCITRAN_PERSISTENT_PATH" \
  --env "SCITRAN_PERSISTENT_DATA_PATH=$SCITRAN_PERSISTENT_DATA_PATH" \
  --env "SCITRAN_CORE_DRONE_SECRET=$SCITRAN_CORE_DRONE_SECRET" \
  --env 'SCITRAN_RUNTIME_COVERAGE=true' \
  --env 'SCITRAN_CORE_ACCESS_LOG_ENABLED=true' &
API_PID=$!

./test/bin/run-integration-tests.sh \
    "$API_BASE_URL" \
    "$SCITRAN_PERSISTENT_DB_URI" \
    "$SCITRAN_PERSISTENT_DB_LOG_URI" \
    "$SCITRAN_CORE_DRONE_SECRET"
