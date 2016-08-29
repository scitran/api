#!/usr/bin/env bash
set -e

unset CDPATH
cd "$( dirname "${BASH_SOURCE[0]}" )/.."

VIRTUALENV_PATH=${VIRTUALENV_PATH:-"./virtualenv"}

if [ -f "`which brew`" ]; then
    echo "Homebrew is installed"
else
    echo "Installing Homebrew"
    ruby -e "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install)"
    echo "Installed Homebrew"
fi

if brew list | grep -q openssl; then
    echo "OpenSSL is installed"
else
    echo "Installing OpenSSL"
    brew install openssl
    echo "Installed OpenSSL"
fi

if brew list | grep -q python; then
    echo "Python is installed"
else
    echo "Installing Python"
    brew install python
    echo "Installed Python"
fi

if [ -f "`which virtualenv`" ]; then
    echo "Virtualenv is installed"
else
    echo "Installing Virtualenv"
    pip install virtualenv
    echo "Installed Virtualenv"
fi

if [ -d "$VIRTUALENV_PATH" ]; then
    echo "Virtualenv exists at $VIRTUALENV_PATH"
else
    echo "Creating 'scitran' Virtualenv at $VIRTUALENV_PATH"
    virtualenv -p `brew --prefix`/bin/python --prompt="(scitran) " $VIRTUALENV_PATH
    echo "Created 'scitran' Virtualenv at $VIRTUALENV_PATH"
fi

echo "Activating Virtualenv"
set -a
. $VIRTUALENV_PATH/bin/activate

pip install -U pip
env LDFLAGS="-L$(brew --prefix openssl)/lib" \
  CFLAGS="-I$(brew --prefix openssl)/include" \
  pip install cryptography

echo "Installing Python requirements"
./bin/install-python-requirements.sh

echo "Installing node and dev dependencies"
if [ ! -f "$VIRTUALENV_PATH/bin/node" ]; then
  # Node doesn't exist in the virtualenv, install
  echo "Installing nodejs"
  node_source_dir=`mktemp -d`
  curl https://nodejs.org/dist/v6.4.0/node-v6.4.0-darwin-x64.tar.gz | tar xvz -C "$node_source_dir"
  mv $node_source_dir/node-v6.4.0-darwin-x64/bin/* "$VIRTUALENV_PATH/bin"
  mv $node_source_dir/node-v6.4.0-darwin-x64/lib/* "$VIRTUALENV_PATH/lib"
  rm -rf "$node_source_dir"
  npm config set prefix "$VIRTUALENV_PATH"
fi

pip install -U -r "test/integration_tests/requirements.txt"
if [ ! -f "`which abao`" ]; then
  npm install -g git+https://github.com/flywheel-io/abao.git#better-jsonschema-ref
fi
if [ ! -f "`which newman`" ]; then
  npm install -g newman@3.0.1
fi

install_mongo() {
    curl $MONGODB_URL | tar xz -C $VIRTUAL_ENV/bin --strip-components 2
    echo "MongoDB version $MONGODB_VERSION installed"
}

MONGODB_VERSION=$(cat mongodb_version.txt)
MONGODB_URL="https://fastdl.mongodb.org/osx/mongodb-osx-x86_64-$MONGODB_VERSION.tgz"
if [ -x "$VIRTUAL_ENV/bin/mongod" ]; then
    INSTALLED_MONGODB_VERSION=$($VIRTUAL_ENV/bin/mongod --version | grep "db version" | cut -d "v" -f 3)
    echo "MongoDB version $INSTALLED_MONGODB_VERSION is installed"
    if [ "$INSTALLED_MONGODB_VERSION" != "$MONGODB_VERSION" ]; then
        echo "Upgrading MongoDB to version $MONGODB_VERSION"
        install_mongo
    fi
else
    echo "Installing MongoDB"
    install_mongo
fi
