#!/usr/bin/env bash

set -e

unset CDPATH
cd "$( dirname "${BASH_SOURCE[0]}" )/.."

echo() { builtin echo -e "\033[1;34m\033[47mSCITRAN\033[0;0m\033[47m $@\033[0;0m"; }


set -o allexport

if [ "$#" -eq 1 ]; then
    EXISTING_ENV=$(env | grep "SCITRAN_" | cat)
    source "$1"
    eval "$EXISTING_ENV"
fi
if [ "$#" -gt 1 ]; then
    echo "Usage: $0 [config file]"
    exit 1
fi


# Minimal default config values
SCITRAN_RUNTIME_HOST=${SCITRAN_RUNTIME_HOST:-"127.0.0.1"}
SCITRAN_RUNTIME_PORT=${SCITRAN_RUNTIME_PORT:-"8080"}
SCITRAN_RUNTIME_PATH=${SCITRAN_RUNTIME_PATH:-"./runtime"}
SCITRAN_RUNTIME_SSL_PEM=${SCITRAN_RUNTIME_SSL_PEM:-""}
SCITRAN_RUNTIME_BOOTSTRAP=${SCITRAN_RUNTIME_BOOTSTRAP:-"bootstrap.json"}
SCITRAN_PERSISTENT_PATH=${SCITRAN_PERSISTENT_PATH:-"./persistent"}
SCITRAN_PERSISTENT_DATA_PATH=${SCITRAN_PERSISTENT_DATA_PATH:-"$SCITRAN_PERSISTENT_PATH/data"}
SCITRAN_PERSISTENT_DB_PATH=${SCITRAN_PERSISTENT_DB_PATH:-"$SCITRAN_PERSISTENT_PATH/db"}
SCITRAN_PERSISTENT_DB_PORT=${SCITRAN_PERSISTENT_DB_PORT:-"9001"}
SCITRAN_PERSISTENT_DB_URI=${SCITRAN_PERSISTENT_DB_URI:-"mongodb://localhost:$SCITRAN_PERSISTENT_DB_PORT/scitran"}

set +o allexport


if [ -f "$SCITRAN_PERSISTENT_DB_PATH/mongod.lock" ]; then
    BOOTSTRAP_USERS=0
else
    echo "Creating database location at $SCITRAN_PERSISTENT_DB_PATH"
    mkdir -p $SCITRAN_PERSISTENT_DB_PATH
    if ! [ -f "$SCITRAN_RUNTIME_BOOTSTRAP" ]; then
        echo "Aborting. Please create $SCITRAN_RUNTIME_BOOTSTRAP from bootstrap.json.sample."
        exit 1
    fi
    BOOTSTRAP_USERS=1
fi


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

if [ -d "$SCITRAN_RUNTIME_PATH" ]; then
    echo "Virtualenv exists at $SCITRAN_RUNTIME_PATH"
else
    echo "Creating 'scitran' Virtualenv at $SCITRAN_RUNTIME_PATH"
    virtualenv -p `brew --prefix`/bin/python --prompt="(scitran)" $SCITRAN_RUNTIME_PATH
    echo "Created 'scitran' Virtualenv at $SCITRAN_RUNTIME_PATH"
fi


echo "Activating Virtualenv"
source $SCITRAN_RUNTIME_PATH/bin/activate

echo "Installing Python requirements"
bin/install.sh


# Install and launch MongoDB
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

mongod --dbpath $SCITRAN_PERSISTENT_DB_PATH --smallfiles --port $SCITRAN_PERSISTENT_DB_PORT &
MONGOD_PID=$!


# Set python path so scripts can work
export PYTHONPATH=.

# Boostrap users
if [ $BOOTSTRAP_USERS -eq 1 ]; then
    echo "Bootstrapping users"
    bin/bootstrap.py users "$SCITRAN_RUNTIME_BOOTSTRAP"
else
    echo "Database exists at $SCITRAN_PERSISTENT_PATH/db. Not bootstrapping users."
fi

TESTDATA_URL="https://github.com/scitran/testdata/archive/master.tar.gz"
TESTDATA_VERSION=$(curl -sLI $TESTDATA_URL | grep ETag | tail -n 1 | cut -f 2 -d '"')
if [ ! -d "$SCITRAN_PERSISTENT_PATH/testdata" ]; then
    echo "Downloading testdata to $SCITRAN_PERSISTENT_PATH/testdata"
    mkdir "$SCITRAN_PERSISTENT_PATH/testdata"
    curl -L $TESTDATA_URL | tar xz -C "$SCITRAN_PERSISTENT_PATH/testdata" --strip-components 1
else
    if [ "$TESTDATA_VERSION" != "$(cat $SCITRAN_PERSISTENT_PATH/.testdata_version)" ]; then
        echo "Testdata out of date; downloading"
        curl -L $TESTDATA_URL | tar xz -C "$SCITRAN_PERSISTENT_PATH/testdata" --strip-components 1
    else
        echo "Testdata up to date"
    fi
fi
builtin echo "$TESTDATA_VERSION" > "$SCITRAN_PERSISTENT_PATH/.testdata_version"

if [ -f "$SCITRAN_PERSISTENT_DATA_PATH/.bootstrapped" ]; then
    echo "Persistence store exists at $SCITRAN_PERSISTENT_PATH/data. Not bootstrapping data. Remove to re-bootstrap."
else
    echo "Bootstrapping testdata"
    bin/bootstrap.py data --copy $SCITRAN_PERSISTENT_PATH/testdata
    echo "Bootstrapped testdata"
    touch "$SCITRAN_PERSISTENT_DATA_PATH/.bootstrapped"
fi


# Serve API with PasteScript
TEMP_INI_FILE=$(mktemp -t scitran_api)
cat << EOF > $TEMP_INI_FILE
[server:main]
use = egg:Paste#http
host = $SCITRAN_RUNTIME_HOST
port = $SCITRAN_RUNTIME_PORT
ssl_pem=$SCITRAN_RUNTIME_SSL_PEM

[app:main]
paste.app_factory = api.api:app_factory
EOF

paster serve --reload $TEMP_INI_FILE &
PASTER_PID=$!


# Shutdown mongod and paster on SIGINT and SIGTERM
trap "{ echo 'Exit signal trapped'; kill $MONGOD_PID $PASTER_PID; wait; }" EXIT
wait

# Clean up and exit out of the python virtualenv
rm -f $TEMP_INI_FILE
deactivate
