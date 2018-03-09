FROM python:2.7-alpine3.7 as build

RUN apk --no-cache add build-base curl

WORKDIR /src/nginx-unit

RUN curl -L https://github.com/nginx/unit/archive/0.4.tar.gz | tar xz --strip-components 1
RUN ./configure --prefix=/usr/local --modules=lib --state=/var/local/unit --pid=/var/unit.pid --log=/var/log/unit.log \
 && ./configure python \
 && make install


FROM python:2.7-alpine3.7 as dist

RUN apk --no-cache add git

COPY --from=build /usr/local/sbin/unitd /usr/local/sbin/unitd
COPY --from=build /usr/local/lib/python.unit.so /usr/local/lib/python.unit.so

EXPOSE 80 8088
VOLUME /data/db /data/persistent

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

CMD ["unitd", "--control", "*:8088", "--no-daemon", "--log", "/dev/stdout"]


FROM dist as dev

EXPOSE 27017

RUN apk --no-cache add mongodb nginx
RUN mkdir /run/nginx

COPY nginx.conf /etc/nginx/nginx.conf

RUN pip install -r tests/requirements.txt

CMD ["./bin/dev+mongo.sh"]
