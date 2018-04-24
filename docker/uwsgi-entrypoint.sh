#!/usr/bin/env sh

set -eu

# /etc/hosts is corrupted if it has lines starting with tab.
# Exit to allow docker to restart.
if grep -P "^\t" /etc/hosts; then
    echo "Host mapping in /etc/hosts is buggy, fail contain start."
    exit 1
fi

export SCITRAN_PERSISTENT_PATH=/var/scitran/data
export SCITRAN_PERSISTENT_DATA_PATH=/var/scitran/data

# Set RUNAS_USER based on the owner of the persistent data path.
RUNAS_USER=$(stat -c '%U' $SCITRAN_PERSISTENT_DATA_PATH)

# Run $PRE_RUNAS_CMD as root if provided. Useful for things like JIT pip installs.
[ -n "${PRE_RUNAS_CMD:-}" ] && eval $PRE_RUNAS_CMD

# Use exec to keep PID and use gosu to step-down from root.
exec gosu $RUNAS_USER "$@"
