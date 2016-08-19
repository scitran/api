FROM ubuntu:14.04

# Install pre-requisites
RUN apt-get update \
	&& apt-get install -y \
		build-essential \
		python \
		python-dev \
		python-pip \
		libffi-dev \
		libssl-dev \
		libpcre3 \
		libpcre3-dev \
		git \
		uwsgi \
		uwsgi-plugin-python \
	&& rm -rf /var/lib/apt/lists/* \
	&& pip install -U pip

# Setup environment
WORKDIR /srv/bids-core

# Copy repo context
ADD . /srv/bids-core

# Declaring a volume makes the intent to map externally explicit. This enables
# the contents to survive/persist across container versions, and easy access
# to the contents outside the container.
#
# Declaring the VOLUME in the Dockerfile guarantees the contents are empty
# for any new container that doesn't specify a volume map via 'docker run -v '
# or similar option.
#
VOLUME /srv/bids-core/keys
VOLUME /srv/bids-core/data
VOLUME /srv/bids-core/logs

# Install pip modules
RUN pip install --upgrade pip wheel setuptools \
  && pip install -r /srv/bids-core/requirements.txt

# COPY uwsgi config
COPY uwsgi-config.ini /srv/bids-core/config/

EXPOSE 8112

CMD ["uwsgi", "/srv/bids-core/config/uwsgi-config.ini", "--socket", "[::]:8112", "--plugins", "python"]