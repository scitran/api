#!/usr/bin/env bash
set -e

unset CDPATH
cd "$( dirname "${BASH_SOURCE[0]}" )/../.."

./test/bin/lint.sh api

./test/bin/run-unit-tests.sh

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
  --env "SCITRAN_PERSISTENT_DB_URI=$SCITRAN_PERSISTENT_DB_URI" \
  --env "SCITRAN_PERSISTENT_PATH=$SCITRAN_PERSISTENT_PATH" \
  --env "SCITRAN_PERSISTENT_DATA_PATH=$SCITRAN_PERSISTENT_DATA_PATH" &

./test/bin/run-integration-tests.sh \
    "$API_BASE_URL" \
    "$SCITRAN_PERSISTENT_DB_URI"
