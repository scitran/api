

## Examples
Following the examples below will server up scitran/core with uwsgi on port 8080
with auto-reload enabled. This will not utilize HTTPS, thus is meant only for
development.

The below examples do not account for complexities of docker volumes, and
preserving their contents across container instances.


```
# Build Example:
   docker build -t scitran-core .

# Run Example:
   # First start mongodb
   docker run --name some-mongo -d mongo

   # Then startup scitran-core, attaching to linked mongo.
   docker run \
     --name scitran-core \
     -e "SCITRAN_PERSISTENT_DB_URI=mongodb://some-mongo:27017/scitran" \
     -e "SCITRAN_CORE_INSECURE=true" \
     -e "SCITRAN_CORE_DRONE_SECRET=change-me" \
     -e "SCITRAN_SITE_API_URL=http://localhost:8080/api" \
     -v $(pwd)/persistent/data:/var/scitran/data \
     -v $(pwd):/var/scitran/code/api \
     --link some-mongo \
     -p 0.0.0.0:8080:8080 \
     scitran-core \
       uwsgi \
         --ini /var/scitran/config/uwsgi-config.ini \
         --http 0.0.0.0:8080 \
         --http-keepalive \
         --python-autoreload 1


# Bootstrap Account Example:
   docker run \
     -e "SCITRAN_SITE_API_URL=http://scitran-core:8080/api" \
     -e "SCITRAN_CORE_DRONE_SECRET=change-me" \
     --link scitran-core \
     --rm \
     -v /dev/bali.prod/docker/uwsgi/bootstrap-dev.json:/accounts.json \
     scitran-core \
       /var/scitran/code/api/docker/bootstrap-defaults.sh \
       /accounts.json


# Bootstrap Data Example:
   docker run \
     -e "SCITRAN_SITE_API_URL=http://scitran-core:8080/api" \
     -e "SCITRAN_CORE_DRONE_SECRET=change-me" \
     -e "PRE_RUNAS_CMD=/var/scitran/code/api/docker/bootstrap-data.sh" \
     --link scitran-core \
     --volumes-from scitran-core \
     --rm \
     scitran-core \
       echo "Data bootstrap complete."
```
