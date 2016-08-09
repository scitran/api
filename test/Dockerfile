FROM python:2.7

ENV MONGO_PATH='mongodb://mongo:27017/scitran'
ENV BASE_URL='http://scitran-core:8080/api'

VOLUME /usr/src/tests
WORKDIR /usr/src/tests

COPY requirements-integration-test.txt requirements.txt
RUN pip install -r requirements.txt

# Install node and abao: https://github.com/cybertk/abao
# Using our fork of abao to expand jsonschema refs
RUN apt-get update && apt-get -y install nodejs npm && ln -s /usr/bin/nodejs /usr/bin/node && npm install -g git+https://github.com/flywheel-io/abao.git#add-jsonschema-deref

ENTRYPOINT ["py.test"]
