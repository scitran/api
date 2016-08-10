FROM python:2.7

ENV MONGO_PATH='mongodb://mongo:27017/scitran'
ENV BASE_URL='http://scitran-core:8080/api'

VOLUME /usr/src/tests
WORKDIR /usr/src/tests

COPY requirements-integration-test.txt requirements.txt
RUN pip install -r requirements.txt

# Install node and abao: https://github.com/cybertk/abao

RUN apt-get -y install npm && npm install -g abao

ENTRYPOINT ["py.test"]
