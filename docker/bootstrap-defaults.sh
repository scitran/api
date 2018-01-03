#!/bin/bash
set -e
set -x

echo "IN BOOTSTRAP DEFAULTS"

(

# Parse input parameters...
#
# bootstrap file
bootstrap_file=${1:-'/var/scitran/code/api/bootstrap.sample.json'}


# Move to API folder for relative path assumptions later on
#
cd /var/scitran/code/api

# Export PYTHONPATH for python script later on.
#
export PYTHONPATH=.


# Bootstrap users and file types
./bin/load_drone_secret.py --insecure --secret "${SCITRAN_CORE_DRONE_SECRET}" "${SCITRAN_SITE_API_URL}" "${bootstrap_file}"


)
