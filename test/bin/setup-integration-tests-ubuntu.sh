set -e

unset CDPATH
cd "$( dirname "${BASH_SOURCE[0]}" )/../.."

pip install -U -r "test/integration_tests/requirements-integration-test.txt"

NODE_URL="https://nodejs.org/dist/v6.4.0/node-v6.4.0-linux-x64.tar.gz"

if [ -z "$VIRTUAL_ENV" ]; then
    curl $NODE_URL | sudo tar xz -C /usr/local --strip-components 1
    npm install test/integration_tests
else
    curl $NODE_URL | tar xz -C $VIRTUAL_ENV --strip-components 1
    npm install test/integration_tests
fi
