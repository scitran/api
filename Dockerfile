#
# Image used for hosting scitran core with uwsgi.
#
# Example usage is in README.md
#

FROM ubuntu:14.04


# Install pre-requisites
RUN apt-get update \
	&& apt-get install -y \
		build-essential \
		ca-certificates curl \
		libatlas3-base \
		numactl \
		python-dev \
		python-pip \
		libffi-dev \
		libssl-dev \
		libpcre3 \
		libpcre3-dev \
		git \
	&& rm -rf /var/lib/apt/lists/* \
	&& pip install -U pip


# Install gosu for docker-friendly stepdown from root
RUN gpg --keyserver ha.pool.sks-keyservers.net --recv-keys B42F6819007F00F88E364FD4036A9C25BF357DD4
RUN curl -o /usr/local/bin/gosu -SL "https://github.com/tianon/gosu/releases/download/1.6/gosu-$(dpkg --print-architecture)" \
	&& curl -o /usr/local/bin/gosu.asc -SL "https://github.com/tianon/gosu/releases/download/1.6/gosu-$(dpkg --print-architecture).asc" \
	&& gpg --verify /usr/local/bin/gosu.asc \
	&& rm /usr/local/bin/gosu.asc \
	&& chmod +x /usr/local/bin/gosu


# Setup environment
WORKDIR /var/scitran

RUN mkdir -p \
      /var/scitran/config \
      /var/scitran/data \
      /var/scitran/code/api \
      /var/scitran/logs \
      /var/scitran/keys

# Declaring a volume makes the intent to map externally explicit. This enables
# the contents to survive/persist across container versions, and easy access
# to the contents outside the container.
#
# Declaring the VOLUME in the Dockerfile guarantees the contents are empty
# for any new container that doesn't specify a volume map via 'docker run -v '
# or similar option.
#
VOLUME /var/scitran/keys
VOLUME /var/scitran/data
VOLUME /var/scitran/logs


# Install pip modules
#
# Split this out for better cache re-use.
#
COPY requirements.txt docker/requirements-docker.txt docs/requirements-docs.txt /var/scitran/code/api/

RUN pip install --upgrade pip wheel setuptools \
  && pip install -r /var/scitran/code/api/requirements-docker.txt \
  && pip install -r /var/scitran/code/api/requirements.txt \
  && pip install -r /var/scitran/code/api/requirements-docs.txt


# Copy full repo
#
COPY . /var/scitran/code/api/



COPY docker/uwsgi-entrypoint.sh /var/scitran/
COPY docker/uwsgi-config.ini /var/scitran/config/
COPY docker/newrelic.ini /var/scitran/config/



# Inject build information into image so the source of the container can be
# determined from within it.
ARG BRANCH_LABEL=NULL
ARG COMMIT_HASH=0
COPY docker/inject_build_info.sh /
RUN /inject_build_info.sh ${BRANCH_LABEL} ${COMMIT_HASH} \
  && rm /inject_build_info.sh


ENTRYPOINT ["/var/scitran/uwsgi-entrypoint.sh"]
CMD ["uwsgi", "--ini", "/var/scitran/config/uwsgi-config.ini", "--http", "0.0.0.0:8080", "--http-keepalive", "--so-keepalive", "--add-header", "Connection: Keep-Alive" ]
