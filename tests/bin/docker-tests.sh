#!/usr/bin/env sh

set -eu
unset CDPATH
cd "$( dirname "$0" )/../.."


USAGE="
Usage:
    $0 [OPTION...] [-- PYTEST_ARGS...]

Build scitran/core image and run tests in a Docker container.
Also displays coverage report and saves HTML under htmlcov/

Options:
    -h, --help          Print this help and exit

    -B, --no-build      Skip rebuilding default Docker image
        --image IMAGE   Use custom Docker image
        --shell         Enter shell instead of running tests

    -- PYTEST_ARGS      Arguments passed to py.test

"


main() {
    local DOCKER_IMAGE=
    local PYTEST_ARGS=
    local RUN_SHELL=

    while [ $# -gt 0 ]; do
        case "$1" in
            -h|--help)
                log "$USAGE"
                exit 0
                ;;
            -B|--no-build)
                DOCKER_IMAGE="scitran/core:testing"
                ;;
            --image)
                DOCKER_IMAGE="$2"
                shift
                ;;
            --shell)
                RUN_SHELL=true
                ;;
            --)
                shift
                PYTEST_ARGS="$@"
                break
                ;;
            *)
                log "Invalid argument: $1"
                log "$USAGE"
                exit 1
                ;;
        esac
        shift
    done

    # Docker build
    if [ -z "${DOCKER_IMAGE}" ]; then
        log "Building scitran/core:testing ..."
        docker build -t scitran/core:testing .
    else
        docker tag "$DOCKER_IMAGE" "scitran/core:testing"
    fi

    log "Cleaning pyc and previous coverage results ..."
    # Run within container to avoid permission problems
    docker run --rm \
        --name core-test-cleanup \
        --volume $(pwd):/var/scitran/code/api \
        scitran/core:testing \
        sh -c "
            find . -type d -name __pycache__ -exec rm -rf {} \;;
            find . -type f -name '*.pyc' -delete;
            rm -rf .coverage htmlcov;
        "

    trap clean_up EXIT
    docker network create core-test

    # Launch core test service (includes mongo)
    docker run -d \
        --name core-test-service \
        --network core-test \
        --volume $(pwd)/api:/var/scitran/code/api/api \
        --volume $(pwd)/tests:/var/scitran/code/api/tests \
        --env PRE_RUNAS_CMD='[ "$1" = uwsgi ] && mongod > /dev/null 2>&1 &' \
        --env SCITRAN_CORE_DRONE_SECRET=secret \
        --env SCITRAN_RUNTIME_COVERAGE=true \
        --env SCITRAN_CORE_ACCESS_LOG_ENABLED=true \
        scitran/core:testing \
            uwsgi --ini /var/scitran/config/uwsgi-config.ini --http [::]:9000 \
            --processes 1 --threads 1 --enable-threads \
            --http-keepalive --so-keepalive --add-header "Connection: Keep-Alive" \
            --logformat '[%(ltime)] "%(method) %(uri) %(proto)" %(status) %(size) request_id=%(request_id)'

    # Run core test cmd
    local CORE_TEST_CMD
    [ $RUN_SHELL ] && CORE_TEST_CMD=bash || \
                      CORE_TEST_CMD="tests/bin/tests.sh -- $PYTEST_ARGS"
    docker run -it \
        --name core-test-runner \
        --network core-test \
        --volume $(pwd)/api:/var/scitran/code/api/api \
        --volume $(pwd)/tests:/var/scitran/code/api/tests \
        --env SCITRAN_SITE_API_URL=http://core-test-service:9000/api \
        --env SCITRAN_CORE_DRONE_SECRET=secret \
        --env SCITRAN_PERSISTENT_DB_URI=mongodb://core-test-service:27017/scitran \
        --env SCITRAN_PERSISTENT_DB_LOG_URI=mongodb://core-test-service:27017/logs \
        scitran/core:testing \
        $CORE_TEST_CMD
}


clean_up() {
    local TEST_RESULT_CODE=$?
    set +e

    log "INFO: Test return code = $TEST_RESULT_CODE"
    if [ "${TEST_RESULT_CODE}" = "0" ]; then
        log "INFO: Collecting coverage..."

        # Copy unit test coverage
        docker cp core-test-runner:/var/scitran/code/api/.coverage .coverage.unit-tests

        # Save integration test coverage
        docker wait $(docker stop core-test-service)
        docker cp core-test-service:/var/scitran/code/api/.coverage.integration-tests .

        # Combine unit/integ coverage and report/grenerate html
        docker run --rm \
            --name core-test-coverage \
            --volume $(pwd):/var/scitran/code/api \
            scitran/core:testing \
            sh -c '
                coverage combine;
                coverage report --skip-covered --show-missing;
                coverage html;
            '
    else
        log "INFO: Printing container logs..."
        docker logs core-test-service
        log "ERROR: Test return code = $TEST_RESULT_CODE. Container logs printed above."
    fi

    # Spin down core service
    docker rm --force --volumes core-test-runner
    docker rm --force --volumes core-test-service
    docker network rm core-test
    exit $TEST_RESULT_CODE
}


log() {
    printf "\n%s\n" "$@" >&2
}


main "$@"
