#!/bin/bash

# Convenience script for unit and integration test execution consumed by
# continous integration workflow (travis)
#
# Must return non-zero on any failure.
set -e

unit_test_path=test/unit_tests/
integration_test_path=test/integration_tests/
code_path=api/

cd "$( dirname "${BASH_SOURCE[0]}" )/.."

(
case "$1-$2" in
  unit-)
    PYTHONPATH=. py.test $unit_test_path
    ;;
  unit---ci)
    PYTHONPATH=. py.test --cov=api --cov-report=term-missing $unit_test_path
    ;;
  unit---watch)
    PYTHONPATH=. ptw $unit_test_path $code_path --poll -- $unit_test_path
    ;;
  integration---ci|integration-)
    # Bootstrap and run integration test.
    #  - always stop and remove docker containers
    #  - always exit non-zero if either bootstrap or integration tests fail
    #  - only execute tests after core is confirmed up
    #  - only run integration tests on bootstrap success

    # launch core
    docker-compose \
      -f test/docker-compose.yml \
      up \
      -d \
      scitran-core &&
    # wait for core to be ready.
    (
      for((i=1;i<=30;i++))
      do
        # ignore return code
        apiResponse=$(docker-compose -f test/docker-compose.yml run --rm core-check) && true

        # reformat response string for comparison
        apiResponse="${apiResponse//[$'\r\n ']}"
        if [ "${apiResponse}" == "200" ]  ; then
          >&2 echo "INFO: Core API is available."
          exit 0
        fi
        >&2 echo "INFO (${apiResponse}): Waiting for Core API to become available after ${i} attempts to connect."
        sleep 1
      done
      exit 1
    ) &&
    # execute tests
    
    docker-compose \
      -f test/docker-compose.yml \
      run \
      --rm \
      bootstrap  &&
    docker-compose \
      -f test/docker-compose.yml \
      run \
      --rm \
      integration-test &&
    docker-compose \
      -f test/docker-compose.yml \
      run \
      --rm \
      --entrypoint "abao /usr/src/raml/api.raml --server=http://scitran-core:8080/api --hookfiles=/usr/src/tests/abao_test_hooks.js" \
      integration-test ||
    # set failure exit code in the event any previous commands in chain failed.
    exit_code=1

    docker-compose -f test/docker-compose.yml down -v
    exit $exit_code
    ;;
  integration---watch)
    echo "Not implemented"
    ;;
  *)
    echo "Usage: $0 unit|integration [--ci|--watch]"
    ;;
esac
)
