#!/usr/bin/env bash

set -e

unset CDPATH
cd "$( dirname "${BASH_SOURCE[0]}" )/.."

if [ $(echo $BASH_VERSION | cut -c 1) -ge 4 ]; then
    echo() { builtin echo -e "\e[1;7mSCITRAN\e[0;7m $@\e[27m"; }
fi

USAGE="
    Run a development instance of scitran/core\n
    Starts mongod on port 9001, by default\n
\n
    Usage:\n
    \n
    -c, --config-file <file>: Source the specified config file to set environemnt variables\n
    -I, --no-install: Do not attempt install the application first\n
    -r, --reload <interval>: Enable live reload, specifying interval in seconds\n
    -T, --no-testdata: Do not bootstrap testdata\n
    -U, --no-user: Do not bootstrap users and groups\n
"

CONFIG_FILE=""
BOOTSTRAP_USERS=1
BOOTSTRAP_TESTDATA=1
AUTO_RELOAD_INTERVAL=0
INSTALL_APP=1

while [ "$#" -gt 0 ]; do
    key="$1"
    case $key in
        -c|--config-file)
        CONFIG_FILE="$2"
        shift
        ;;
        --help)
        echo $USAGE >&2
        exit 1
        ;;
        -I|--no-install)
        INSTALL_APP=0
        ;;
        -r|--reload)
        AUTO_RELOAD_INTERVAL=$2
        shift
        ;;
        -T|--no-testdata)
        BOOTSTRAP_TESTDATA=0
        ;;
        -U|--no-users)
        BOOTSTRAP_USERS=0
        ;;
        *)
        echo "Invalid option: $key" >&2
        echo $USAGE >&2
        exit 1
        ;;
    esac
    shift
done


set -o allexport

if [ "$CONFIG_FILE" != "" ]; then
    EXISTING_ENV=$(env | grep "SCITRAN_" | cat)
    source "$CONFIG_FILE"
    eval "$EXISTING_ENV"
fi

SCITRAN_RUNTIME_PATH=${SCITRAN_RUNTIME_PATH:-"./runtime"}
SCITRAN_RUNTIME_HOST=${SCITRAN_RUNTIME_HOST:-"127.0.0.1"}
SCITRAN_RUNTIME_PORT=${SCITRAN_RUNTIME_PORT:-"8080"}
SCITRAN_RUNTIME_UWSGI_INI=${SCITRAN_RUNTIME_UWSGI_INI:-""}
SCITRAN_RUNTIME_BOOTSTRAP=${SCITRAN_RUNTIME_BOOTSTRAP:-"./bootstrap.json"}
SCITRAN_RUNTIME_SSL_PEM=${SCITRAN_RUNTIME_SSL_PEM:-""}
SCITRAN_RUNTIME_COVERAGE=${SCITRAN_RUNTIME_COVERAGE:-"false"}

SCITRAN_CORE_DRONE_SECRET=${SCITRAN_CORE_DRONE_SECRET:-$( openssl rand -base64 32 )}

SCITRAN_PERSISTENT_PATH=${SCITRAN_PERSISTENT_PATH:-"./persistent"}
SCITRAN_PERSISTENT_DATA_PATH="$SCITRAN_PERSISTENT_PATH/data"
SCITRAN_PERSISTENT_DB_PATH=${SCITRAN_PERSISTENT_DB_PATH:-"$SCITRAN_PERSISTENT_PATH/db"}
SCITRAN_PERSISTENT_DB_PORT=${SCITRAN_PERSISTENT_DB_PORT:-"9001"}
SCITRAN_PERSISTENT_DB_URI=${SCITRAN_PERSISTENT_DB_URI:-"mongodb://localhost:$SCITRAN_PERSISTENT_DB_PORT/scitran"}

if [ "$SCITRAN_RUNTIME_SSL_PEM" == "" ]; then
  SCITRAN_SITE_API_URL="http://$SCITRAN_RUNTIME_HOST:$SCITRAN_RUNTIME_PORT"
  UWSGI_SOCKET_ARG="--http"
  UWSGI_SOCKET_VALUE="$SCITRAN_RUNTIME_HOST:$SCITRAN_RUNTIME_PORT"
else
  SCITRAN_SITE_API_URL="https://$SCITRAN_RUNTIME_HOST:$SCITRAN_RUNTIME_PORT"
  UWSGI_SOCKET_ARG="--https" UWSGI_SOCKET_VALUE="$SCITRAN_RUNTIME_HOST:$SCITRAN_RUNTIME_PORT,$SCITRAN_RUNTIME_SSL_PEM,$SCITRAN_RUNTIME_SSL_PEM"
fi

set +o allexport


if [ $INSTALL_APP -eq 1 ]; then
    ./bin/install-dev-osx.sh
fi


clean_up () {
    kill $MONGOD_PID || true
    kill $UWSGI_PID || true
    deactivate || true
    wait 2> /dev/null
}
trap clean_up EXIT


source "$SCITRAN_RUNTIME_PATH/bin/activate"


# Launch MongoDB
ulimit -n 1024
mkdir -p "$SCITRAN_PERSISTENT_DB_PATH"
mongod \
    --port $SCITRAN_PERSISTENT_DB_PORT \
    --dbpath "$SCITRAN_PERSISTENT_DB_PATH" \
    --smallfiles \
    &
MONGOD_PID=$!


# Launch uWSGI
if [ "$SCITRAN_RUNTIME_UWSGI_INI" == "" ]; then
    uwsgi \
        "$UWSGI_SOCKET_ARG" "$UWSGI_SOCKET_VALUE" \
        --master --die-on-term \
        --home "$SCITRAN_RUNTIME_PATH" \
        --wsgi-file "bin/api.wsgi" \
        --py-autoreload $AUTO_RELOAD_INTERVAL \
        --logformat '%(addr) - %(user) [%(ltime)] "%(method) %(uri) %(proto)" %(status) %(size) "%(referer)" "%(uagent)" request_id=%(request_id)' &
    UWSGI_PID=$!
else
    uwsgi --ini "$SCITRAN_RUNTIME_UWSGI_INI" &
    UWSGI_PID=$!
fi


echo "Waiting for API to become available"
until $(curl --output /dev/null --silent --head --fail --insecure "$SCITRAN_SITE_API_URL/api"); do
    sleep 1
done


# Bootstrap users
if [ $BOOTSTRAP_USERS -eq 1 ]; then
    if [ -f "$SCITRAN_PERSISTENT_DB_PATH/.bootstrapped" ]; then
        echo "Users previously bootstrapped. Remove $SCITRAN_PERSISTENT_DB_PATH to re-bootstrap."
    else
        echo "Bootstrapping users"
        PYTHONPATH=. bin/load_users_drone_secret.py \
          --insecure --secret "$SCITRAN_CORE_DRONE_SECRET" \
          "$SCITRAN_SITE_API_URL" \
          "$SCITRAN_RUNTIME_BOOTSTRAP"

        echo "Bootstrapped users"
        touch "$SCITRAN_PERSISTENT_DB_PATH/.bootstrapped"
    fi
else
    echo "NOT bootstrapping users"
fi


# Boostrap test data
TESTDATA_REPO="https://github.com/scitran/testdata.git"
if [ $BOOTSTRAP_TESTDATA -eq 1 ]; then
    if [ -f "$SCITRAN_PERSISTENT_DATA_PATH/.bootstrapped" ]; then
        echo "Data previously bootstrapped. Remove $SCITRAN_PERSISTENT_DATA_PATH to re-bootstrap."
    else
        if [ ! -d "$SCITRAN_PERSISTENT_PATH/testdata" ]; then
            echo "Cloning testdata to $SCITRAN_PERSISTENT_PATH/testdata"
            git clone --single-branch $TESTDATA_REPO $SCITRAN_PERSISTENT_PATH/testdata
        else
            echo "Updating testdata in $SCITRAN_PERSISTENT_PATH/testdata"
            git -C $SCITRAN_PERSISTENT_PATH/testdata pull
        fi
        echo "Ensuring reaper is up to date with master branch"
        pip install --upgrade --upgrade-strategy only-if-needed git+https://github.com/scitran/reaper.git
        echo "Bootstrapping testdata"
        folder_sniper --yes --insecure --secret "$SCITRAN_CORE_DRONE_SECRET" "$SCITRAN_PERSISTENT_PATH/testdata" $SCITRAN_SITE_API_URL
        echo "Bootstrapped testdata"
        touch "$SCITRAN_PERSISTENT_DATA_PATH/.bootstrapped"
    fi
else
    echo "NOT bootstrapping testdata"
fi

wait
