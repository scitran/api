#!/usr/bin/env sh

set -e

# If running unitd and started as root, update file ownership
if [ "$1" == "unitd" -a "$(id -u)" == "0" ]; then
    chown nobody:nobody -R $SCITRAN_PERSISTENT_DATA_PATH
fi

exec "$@"
