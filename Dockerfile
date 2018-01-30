FROM python:2.7-alpine3.7 as build

RUN apk add --no-cache build-base curl

WORKDIR /src/nginx-unit

RUN curl -L https://github.com/nginx/unit/archive/0.4.tar.gz | tar xz --strip-components 1
RUN ./configure --prefix=/usr/local --modules=lib --state=/var/local/unit --pid=/var/unit.pid --log=/var/log/unit.log \
 && ./configure python \
 && make install


FROM python:2.7-alpine3.7 as dist

RUN apk add --no-cache git

COPY --from=build /usr/local/sbin/unitd /usr/local/sbin/unitd
COPY --from=build /usr/local/lib/python.unit.so /usr/local/lib/python.unit.so

EXPOSE 80 8080
VOLUME /data/db
VOLUME /data/persistent

WORKDIR /src/core
ENV SCITRAN_PERSISTENT_DATA_PATH=/data/persistent

COPY nginx-unit.json /var/local/unit/conf.json
COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

COPY . .
RUN pip install -e .

ARG VCS_BRANCH=NULL
ARG VCS_COMMIT=NULL
RUN ./bin/build_info.sh $VCS_BRANCH $VCS_COMMIT | tee /version.json

ENTRYPOINT ["./bin/entrypoint.sh"]
CMD ["unitd", "--control", "*:8080", "--no-daemon", "--log", "/dev/stdout"]


FROM dist as dev

EXPOSE 27017

RUN apk add --no-cache mongodb

RUN pip install -r tests/requirements.txt

CMD ["./bin/dev+mongo.sh"]
