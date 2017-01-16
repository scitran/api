#!/bin/bash

# FDM-831 workaround
# https://github.com/docker/compose/issues/2454
# remove after docker 1.10.0 becomes minim supported version.
#
# If /etc/hosts has lines starting with tab, it is corrupted,
# exit to allow docker to restart.
grep -P "^\t" /etc/hosts
if [ "$?" == 0 ] ; then
	echo "Host mapping in /etc/hosts is buggy, fail contain start."
	exit 1
fi


set -e
set -x

export PYTHONPATH=/var/scitran/code/api

export SCITRAN_PERSISTENT_PATH=/var/scitran/data
export SCITRAN_PERSISTENT_DATA_PATH=/var/scitran/data

# Get the RunAs user from the owner of the mapped folder.
# This is a compromise to get permissions to work well with
# host mapped volumes with docker-machine on OSX and production
# without the vbox driver layer.
RUNAS_USER=$(ls -ld "${SCITRAN_PERSISTENT_DATA_PATH}" | awk '{print $3}')


if [ "${1:0:1}" = '-' ]; then
	set -- uwsgi "$@"
fi

# run $PRE_RUNAS_CMD as root if provided. Useful for things like JIT pip insalls.
if [ ! -z "${PRE_RUNAS_CMD}" ]; then
	${PRE_RUNAS_CMD}
fi

if [ "$1" = 'uwsgi' ]; then

	python /var/scitran/code/api/docker/build-info-load.py
	exec gosu ${RUNAS_USER} "$@"
fi

gosu ${RUNAS_USER} "$@"

result=$?
echo "Exit code was $result"
