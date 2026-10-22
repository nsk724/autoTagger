FROM postgres:16-alpine
# gosu only drops root, and this image starts as postgres; it also ships an old Go stdlib (CVEs)
RUN rm /usr/local/bin/gosu
COPY services/postgres/migrations/ /docker-entrypoint-initdb.d/
# a new named volume inherits the image dir's postgres ownership, so no root step is needed
USER postgres
