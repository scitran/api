#!/usr/bin/env bash
set -eu
unset CDPATH
cd "$( dirname "${BASH_SOURCE[0]}" )/../.."


function usage() {
cat >&2 <<EOF
Run scitran-core tests

Usage:
    $0 [OPTION...]

Runs linting and all tests if no options are provided.
Runs subset of tests when using the filtering options.
Displays coverage report if all tests ran and passed.

Options:
    -l, --lint           Run linting
    -u, --unit           Run unit tests
    -i, --integ          Run integration tests
    -h, --help           Print this help and exit
    -- PYTEST_ARGS       Arguments passed to py.test

Envvars:
    SCITRAN_PERSISTENT_DB_PORT    (9001)
    SCITRAN_PERSISTENT_DB_URI     (mongodb://localhost:9001/scitran)
    SCITRAN_PERSISTENT_DB_LOG_URI (mongodb://localhost:9001/logs)

Assumes mongo db instance is accessible at localhost, unless
SCITRAN_PERSISTENT_DB_URI or SCITRAN_PERSISTENT_DB_LOG_URI specify otherwise.

EOF
}


function main() {
    export RUN_ALL=true
    local RUN_LINT=false
    local RUN_UNIT=false
    local RUN_INTEG=false
    local PYTEST_ARGS=

    while [[ "$#" > 0 ]]; do
        case "$1" in
            -l|--lint)      RUN_ALL=false; RUN_LINT=true      ;;
            -u|--unit)      RUN_ALL=false; RUN_UNIT=true      ;;
            -i|--integ)     RUN_ALL=false; RUN_INTEG=true     ;;
            -h|--help)      usage;                     exit 0 ;;
            --)             PYTEST_ARGS="${@:2}";      break  ;;
            *) echo "Invalid argument: $1" >&2; usage; exit 1 ;;
        esac
        shift
    done

    if ${RUN_ALL}; then
        # No filtering options used, run everything by default
        RUN_LINT=true
        RUN_UNIT=true
        RUN_INTEG=true
    elif ${RUN_LINT} && ${RUN_UNIT} && ${RUN_INTEG}; then
        # All filtering options were used, the same as none
        RUN_ALL=true
    fi

    trap clean_up EXIT

    # Remove __pycache__ directories for issue with __file__ attribute due to
    # running the tests on the host creating bytecode files hich have a
    # mismatched __file__ attribute when loaded in docker container
    rm -rf tests/unit_tests/python/__pycache__
    rm -rf tests/integration_tests/python/__pycache__

    export PYTHONPATH="$(pwd)"
    export SCITRAN_SITE_API_URL="http://localhost:8081/api"
    export SCITRAN_PERSISTENT_DB_PORT=${SCITRAN_PERSISTENT_DB_PORT:-"9001"}
    export SCITRAN_PERSISTENT_DB_URI=${SCITRAN_PERSISTENT_DB_URI:-"mongodb://localhost:$SCITRAN_PERSISTENT_DB_PORT/scitran"}
    export SCITRAN_PERSISTENT_DB_LOG_URI=${SCITRAN_PERSISTENT_DB_LOG_URI:-"mongodb://localhost:$SCITRAN_PERSISTENT_DB_PORT/logs"}
    export SCITRAN_PERSISTENT_PATH=`mktemp -d`
    export SCITRAN_PERSISTENT_DATA_PATH="$SCITRAN_PERSISTENT_PATH/data"
    mkdir -p "$SCITRAN_PERSISTENT_DATA_PATH/v1"
    export SCITRAN_PERSISTENT_FS_URL="osfs://$SCITRAN_PERSISTENT_PATH/data/v1"
    export SCITRAN_CORE_DRONE_SECRET=${SCITRAN_CORE_DRONE_SECRET:-$( openssl rand -base64 32 )}

    if ${RUN_LINT}; then
        echo "Running pylint ..."
        # TODO Enable Refactor and Convention reports
        # TODO Move --disable into rc
        pylint --reports=no --disable=C,R,W0312,W0141,W0110 api

        # echo "Running pep8 ..."
        # pep8 --max-line-length=150 --ignore=E402 api
    fi

    if ${RUN_UNIT}; then
        echo "Running unit tests ..."
        rm -f .coverage
        py.test --cov=api --cov-report= tests/unit_tests/python $PYTEST_ARGS
    fi

    if ${RUN_INTEG}; then
        echo "Spinning up dependencies ..."
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
            --env "SCITRAN_RUNTIME_COVERAGE=true" \
            --env "SCITRAN_COLLECT_ENDPOINTS=true" \
            --env "SCITRAN_CORE_ACCESS_LOG_ENABLED=true" &
        export API_PID=$!

        echo "Connecting to API"
        until $(curl --output /dev/null --silent --head --fail "$SCITRAN_SITE_API_URL"); do
            printf '.'
            sleep 1
        done

        echo "Running integration tests ..."
        py.test tests/integration_tests/python $PYTEST_ARGS
    fi
}


function clean_up () {
    local TEST_RESULT_CODE=$?
    set +e

    echo
    echo "Test return code = $TEST_RESULT_CODE"

    if [[ -n "${API_PID:-}" ]]; then
        # Killing uwsgi
        kill $API_PID
        wait 2> /dev/null
    fi

    if ${RUN_ALL} && [[ "${TEST_RESULT_CODE}" == "0" ]]; then
        echo
        echo "UNIT TEST COVERAGE:"
        coverage report --skip-covered
        echo
        echo "OVERALL COVERAGE:"
        coverage combine
        coverage report --show-missing
        coverage html
    else
        echo "Some tests were skipped or failed, skipping coverage report"
    fi

    exit $TEST_RESULT_CODE
}


main "$@"
