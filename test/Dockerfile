FROM python:2.7

ENV MONGO_PATH='mongodb://mongo:27017/scitran'
ENV BASE_URL='http://scitran-core:8080/api'

VOLUME /usr/src/tests
WORKDIR /usr/src/tests

COPY integration_tests/requirements-integration-test.txt requirements.txt
RUN pip install -r requirements.txt

# Install node for testing tools
# We need node >= 4.0 for newman so install from node-source repo
# Need to install apt support for https to access these urls
RUN apt-get update && apt-get install -y apt-transport-https
RUN curl --silent https://deb.nodesource.com/gpgkey/nodesource.gpg.key | apt-key add -
RUN echo "deb https://deb.nodesource.com/node_5.x trusty main" | tee /etc/apt/sources.list.d/nodesource.list
RUN echo "deb-src https://deb.nodesource.com/node_5.x trusty main" |  tee -a /etc/apt/sources.list.d/nodesource.list
RUN apt-get update && apt-get -y install nodejs

# Install newman for running postman collection tests from CLI
RUN npm install -g /usr/src/tests

ENTRYPOINT ["py.test"]
