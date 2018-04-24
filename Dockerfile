FROM ubuntu:14.04 as base
ENV TERM=xterm
RUN set -eux \
    && apt-get -yqq update \
    && apt-get -yqq install \
        build-essential \
        ca-certificates \
        curl \
        git \
        libatlas3-base \
        libffi-dev \
        libpcre3 \
        libpcre3-dev \
        libssl-dev \
        numactl \
        python-dev \
        python-pip \
    && rm -rf /var/lib/apt/lists/* \
    && pip install -qq --upgrade pip setuptools wheel \
    && export GNUPGHOME="$(mktemp -d)" \
    && KEYSERVERS="\
        ha.pool.sks-keyservers.net \
        hkp://keyserver.ubuntu.com:80 \
        hkp://p80.pool.sks-keyservers.net:80 \
        keyserver.ubuntu.com \
        pgp.mit.edu" \
    && for server in $(shuf -e $KEYSERVERS); do \
           gpg --keyserver "$server" --recv-keys B42F6819007F00F88E364FD4036A9C25BF357DD4 && break || true; \
       done \
    && curl -LSso /usr/local/bin/gosu "https://github.com/tianon/gosu/releases/download/1.6/gosu-$(dpkg --print-architecture)" \
    && curl -LSso /tmp/gosu.asc "https://github.com/tianon/gosu/releases/download/1.6/gosu-$(dpkg --print-architecture).asc" \
    && gpg --batch --verify /tmp/gosu.asc /usr/local/bin/gosu \
    && chmod +x /usr/local/bin/gosu \
    && rm -rf "$GNUPGHOME" /tmp/gosu.asc \
    && mkdir -p \
        /var/scitran/code/api \
        /var/scitran/config \
        /var/scitran/data \
        /var/scitran/keys \
        /var/scitran/logs

VOLUME ["/var/scitran/keys", "/var/scitran/data", "/var/scitran/logs"]
WORKDIR /var/scitran/code/api

COPY docker/uwsgi-entrypoint.sh /var/scitran/
COPY docker/uwsgi-config.ini    /var/scitran/config/
ENTRYPOINT ["/var/scitran/uwsgi-entrypoint.sh"]
CMD ["uwsgi", "--ini=/var/scitran/config/uwsgi-config.ini", "--http=[::]:9000", \
              "--http-keepalive", "--so-keepalive", "--add-header", "Connection: Keep-Alive"]


FROM base as dist
COPY requirements.txt /var/scitran/code/api/requirements.txt
RUN set -eux \
    && pip install -qq --requirement /var/scitran/code/api/requirements.txt

COPY . /var/scitran/code/api/
RUN set -eux \
    && pip install -qq --no-deps --editable /var/scitran/code/api

ARG VCS_BRANCH=NULL
ARG VCS_COMMIT=NULL
RUN set -eux \
    && /var/scitran/code/api/bin/build_info.sh $VCS_BRANCH $VCS_COMMIT > /var/scitran/version.json \
    && cat /var/scitran/version.json


FROM base as testing
ENV MONGO_MAJOR=3.2 \
    MONGO_VERSION=3.2.9
RUN set -eux \
    && apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv EA312927 \
    && echo "deb http://repo.mongodb.org/apt/ubuntu trusty/mongodb-org/$MONGO_MAJOR multiverse" > /etc/apt/sources.list.d/mongodb-org-$MONGO_MAJOR.list \
    && apt-get -yqq update \
    && apt-get -yqq install \
        mongodb-org=$MONGO_VERSION \
        mongodb-org-server=$MONGO_VERSION \
        mongodb-org-shell=$MONGO_VERSION \
        mongodb-org-mongos=$MONGO_VERSION \
        mongodb-org-tools=$MONGO_VERSION \
    && rm -rf /var/lib/apt/lists/* /var/lib/mongodb \
    && mkdir -p /data/db

COPY --from=dist /usr/local /usr/local

COPY tests/requirements.txt /var/scitran/code/api/tests/requirements.txt
RUN set -eux \
    && pip install -qq --requirement /var/scitran/code/api/tests/requirements.txt

COPY --from=dist /var/scitran /var/scitran
