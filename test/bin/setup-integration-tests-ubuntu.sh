set -e

unset CDPATH
cd "$( dirname "${BASH_SOURCE[0]}" )/../.."

pip install -U -r "test/integration_tests/requirements-integration-test.txt"


node_source_dir=`mktemp -d`
curl https://nodejs.org/dist/v6.4.0/node-v6.4.0-linux-x64.tar.gz | tar xz -C "$node_source_dir"

if [ -z "$VIRTUAL_ENV" ]; then
    sudo mv $node_source_dir/node-v6.4.0-linux-x64/bin/* /usr/local/bin
    sudo mv $node_source_dir/node-v6.4.0-linux-x64/lib/* /usr/local/lib
    sudo npm install -g git+https://github.com/flywheel-io/abao.git#better-jsonschema-ref
    sudo npm install -g test/integration_tests
else
    mv $node_source_dir/node-v6.4.0-linux-x64/bin/* "$VIRTUAL_ENV/bin"
    mv $node_source_dir/node-v6.4.0-linux-x64/lib/* "$VIRTUAL_ENV/lib"
    rm -rf "$node_source_dir"
    npm config set prefix "$VIRTUAL_ENV"
    npm install -g test/integration_tests
fi
