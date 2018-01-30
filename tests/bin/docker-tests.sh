#!/usr/bin/env sh

set -eu
unset CDPATH
cd "$( dirname "$0" )/../.."


USAGE="
Usage:
    $0 [OPTION...] [-- PYTEST_ARGS...]

Build scitran/core image and run tests in a Docker container.
Also displays coverage report and saves HTML in htmlcov dir.

Options:
    -h, --help          Print this help and exit

    -B, --no-build      Skip rebuilding default Docker image
    --image IMAGE       Use custom Docker image
    -- PYTEST_ARGS      Arguments passed to py.test

"


main() {
    local DOCKER_IMAGE=
    local PYTEST_ARGS=

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
        --volume $(pwd):/src/core \
        scitran/core:testing \
        sh -c "
            find . -type d -name __pycache__ -exec rm -rf {} \;;
            find . -type f -name '*.pyc' -delete;
            rm -rf .coverage htmlcov;
        "

    trap clean_up EXIT
    docker network create core-test

    # Launch core + mongo
    docker run -d \
        --name core-test-service \
        --network core-test \
        --volume $(pwd)/api:/src/core/api \
        --volume $(pwd)/tests:/src/core/tests \
        --env SCITRAN_CORE_DRONE_SECRET=secret \
        --env SCITRAN_RUNTIME_COVERAGE=true \
        --env SCITRAN_CORE_ACCESS_LOG_ENABLED=true \
        scitran/core:testing

    # Execute tests
    docker run -it \
        --name core-test-runner \
        --network core-test \
        --volume $(pwd)/api:/src/core/api \
        --volume $(pwd)/tests:/src/core/tests \
        --env SCITRAN_SITE_API_URL=http://core-test-service/api \
        --env SCITRAN_CORE_DRONE_SECRET=secret \
        --env SCITRAN_PERSISTENT_DB_URI=mongodb://core-test-service:27017/scitran \
        --env SCITRAN_PERSISTENT_DB_LOG_URI=mongodb://core-test-service:27017/logs \
        scitran/core:testing \
        tests/bin/tests.sh -- $PYTEST_ARGS
}


clean_up() {
    local TEST_RESULT_CODE=$?
    set +e

    log "INFO: Test return code = $TEST_RESULT_CODE"
    if [ "${TEST_RESULT_CODE}" = "0" ]; then
        log "INFO: Collecting coverage..."

        # Copy unit test coverage
        docker cp core-test-runner:/src/core/.coverage .coverage.unit-tests 2>/dev/null

        # Save integration test coverage
        docker wait $(docker stop core-test-service)
        docker cp core-test-service:/tmp/.coverage.integration-tests .

        # Combine unit/integ coverage and report/grenerate html
        docker run --rm \
            --name core-test-coverage \
            --volume $(pwd):/src/core \
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

    # Spin down dependencies
    docker rm --force --volumes core-test-runner
    docker rm --force --volumes core-test-service
    docker network rm core-test
    exit $TEST_RESULT_CODE
}


log() {
    printf "\n%s\n" "$@" >&2
}


main "$@"
