#!/usr/bin/env bash
set -e

unset CDPATH
cd "$( dirname "${BASH_SOURCE[0]}" )/.."

USAGE="
    Run a development instance of scitran-core\n
    Also starts mongo, on port 9001 by default\n
\n
    Usage:\n
    \n
    -C, --config-file <shell-script>: Source a shell script to set environemnt variables\n
    -I, --no-install: Do not attempt install the application first\n
    -R, --reload <interval>: Enable live reload, specifying interval in seconds\n
    -T, --no-testdata: do not bootstrap testdata\n
    -U, --no-user: do not bootstrap users and groups\n
"

CONFIG_FILE=""
BOOTSTRAP_USERS=1
BOOTSTRAP_TESTDATA=1
AUTO_RELOAD=0
INSTALL_APP=1

while [[ "$#" -gt 0 ]]; do
  key="$1"

  case $key in
      -C|--config-file)
      CONFIG_FILE="$1"
      shift
      ;;
      --help)
      echo -e $USAGE >&2
      exit 1
      ;;
      -I|--no-install)
      INSTALL_APP=0
      ;;
      -R|--reload)
      AUTO_RELOAD=1
      AUTO_RELOAD_INTERVAL=$1
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
      echo -e $USAGE >&2
      exit 1
      ;;
  esac
  shift
done

set -a

VIRTUALENV_PATH=${VIRTUALENV_PATH:-"$( pwd )/virtualenv"}
MONGODB_DATA_DIR="$VIRTUALENV_PATH/mongo_data"
MONGODB_LOG_FILE="$VIRTUALENV_PATH/mongodb.log"
MONGOD_EXECUTABLE="$VIRTUALENV_PATH/bin/mongod"

SCITRAN_RUNTIME_HOST=${SCITRAN_RUNTIME_HOST:-"127.0.0.1"}
SCITRAN_RUNTIME_PORT=${SCITRAN_RUNTIME_PORT:-"8080"}
SCITRAN_RUNTIME_UWSGI_INI=${SCITRAN_RUNTIME_UWSGI_INI:-""}
SCITRAN_RUNTIME_BOOTSTRAP=${SCITRAN_RUNTIME_BOOTSTRAP:-"./bootstrap.json"}

SCITRAN_CORE_DRONE_SECRET=${SCITRAN_CORE_DRONE_SECRET:-$(  openssl rand -base64 32 )}

SCITRAN_PERSISTENT_PATH="$VIRTUALENV_PATH/scitran-persistent"
SCITRAN_PERSISTENT_DATA_PATH="$SCITRAN_PERSISTENT_PATH/data"
SCITRAN_PERSISTENT_DB_PATH=${SCITRAN_PERSISTENT_DB_PATH:-"$SCITRAN_PERSISTENT_PATH/db"}
SCITRAN_PERSISTENT_DB_PORT=${SCITRAN_PERSISTENT_DB_PORT:-"9001"}
SCITRAN_PERSISTENT_DB_URI=${SCITRAN_PERSISTENT_DB_URI:-"mongodb://localhost:$SCITRAN_PERSISTENT_DB_PORT/scitran"}

SCITRAN_SITE_API_URL="http://$SCITRAN_RUNTIME_HOST:$SCITRAN_RUNTIME_PORT/api"

if [ $INSTALL_APP -eq 1 ]; then
  ./bin/install-dev-osx.sh
fi

clean_up () {
  kill $MONGOD_PID || true
  kill $UWSGI_PID || true
  deactivate || true
}
trap clean_up EXIT

. "$VIRTUALENV_PATH/bin/activate"

ulimit -n 1024
mkdir -p "$SCITRAN_PERSISTENT_DB_PATH"
"$MONGOD_EXECUTABLE" --port $SCITRAN_PERSISTENT_DB_PORT --logpath "$MONGODB_LOG_FILE" --dbpath "$SCITRAN_PERSISTENT_DB_PATH" --smallfiles &
MONGOD_PID=$!

sleep 2

# Always drop integration-tests db on startup
echo -e "use integration-tests \n db.dropDatabase()" | mongo "$SCITRAN_PERSISTENT_DB_URI"

if [ "$SCITRAN_RUNTIME_UWSGI_INI" == "" ]; then
  "$VIRTUALENV_PATH/bin/uwsgi" \
    --http "$SCITRAN_RUNTIME_HOST:$SCITRAN_RUNTIME_PORT" \
    --master --http-keepalive \
    --so-keepalive --add-header "Connection: Keep-Alive" \
    --processes 1 --threads 1 \
    --enable-threads \
    --wsgi-file "bin/api.wsgi" \
    -H "$VIRTUALENV_PATH" \
    --die-on-term \
    --py-autoreload $AUTO_RELOAD \
    --env "SCITRAN_CORE_DRONE_SECRET=$SCITRAN_CORE_DRONE_SECRET" \
    --env "SCITRAN_PERSISTENT_DB_URI=$SCITRAN_PERSISTENT_DB_URI" \
    --env "SCITRAN_PERSISTENT_PATH=$SCITRAN_PERSISTENT_PATH" \
    --env "SCITRAN_PERSISTENT_DATA_PATH=$SCITRAN_PERSISTENT_DATA_PATH" &
    UWSGI_PID=$!
else
  "$VIRTUALENV_PATH/bin/uwsgi" --ini "$SCITRAN_RUNTIME_UWSGI_INI" &
  UWSGI_PID=$!
fi

until $(curl --output /dev/null --silent --head --fail "$SCITRAN_SITE_API_URL"); do
    printf '.'
    sleep 1
done

# Bootstrap users
if [ $BOOTSTRAP_USERS -eq 1 ]; then
    if [ -f "$SCITRAN_PERSISTENT_DB_PATH/.bootstrapped" ]; then
        echo "Users previously bootstrapped. Remove $SCITRAN_PERSISTENT_DB_PATH to re-bootstrap."
    else
        echo "Bootstrapping users"
        SCITRAN_PERSISTENT_DB_URI="$SCITRAN_PERSISTENT_DB_URI" \
          bin/bootstrap.py "$SCITRAN_RUNTIME_BOOTSTRAP"
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
        pip install -U git+https://github.com/scitran/reaper.git
        echo "Bootstrapping testdata"
        UPLOAD_URI="$SCITRAN_SITE_API_URL?secret=$SCITRAN_CORE_DRONE_SECRET"
        folder_sniper --yes --insecure "$SCITRAN_PERSISTENT_PATH/testdata" $UPLOAD_URI
        echo "Bootstrapped testdata"
        touch "$SCITRAN_PERSISTENT_DATA_PATH/.bootstrapped"
    fi
else
    echo "NOT bootstrapping testdata"
fi

wait
