#!/usr/bin/env sh

mongod &
MONGOD_PID=$!

if [ "$(stat -c %U:%G $SCITRAN_PERSISTENT_DATA_PATH)" != "nobody:nobody" ]; then
    chown nobody:nobody -R $SCITRAN_PERSISTENT_DATA_PATH
fi

exec unitd --control "*:8080" --no-daemon --log /dev/stdout
