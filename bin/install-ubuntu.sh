#!/usr/bin/env bash
set -e

unset CDPATH
cd "$( dirname "${BASH_SOURCE[0]}" )/.."

SCITRAN_USER="scitran-core"

sudo apt-get update
sudo apt-get install -y \
    build-essential \
    ca-certificates \
    curl \
    libatlas3-base \
    numactl \
    python-dev \
    libffi-dev \
    libssl-dev \
    libpcre3 \
    libpcre3-dev \
    git

sudo useradd -d /var/scitran -m -r "$SCITRAN_USER"

./bin/install-python-requirements.sh
