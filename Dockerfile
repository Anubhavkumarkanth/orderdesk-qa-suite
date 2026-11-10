# Live-demo image: the app and its own MySQL 8 in one container, so the free host needs no outside database.
# The data sits on the container's disk; the app re-seeds it on every restart.
FROM mysql:8.4

RUN microdnf install -y python3.12 python3.12-pip && microdnf clean all
WORKDIR /srv
COPY requirements.txt .
# The test tools are not needed to serve the app.
RUN grep -vE '^(pytest|playwright)' requirements.txt > runtime.txt \
 && python3.12 -m pip install --no-cache-dir -r runtime.txt
COPY app app
COPY scripts/start_demo.sh .

# Build the data directory now, so a cold start only starts MySQL instead of initialising it.
# The orderdesk account has no password: MySQL listens on 127.0.0.1 only, so nothing outside the container can reach it.
RUN mkdir /srv/mysql && chown mysql:mysql /srv/mysql \
 && printf "%s\n" "CREATE DATABASE orderdesk;" "CREATE USER 'orderdesk'@'%' IDENTIFIED BY '';" \
    "GRANT ALL ON orderdesk.* TO 'orderdesk'@'%';" > /tmp/init.sql \
 && mysqld --no-defaults --initialize-insecure --user=mysql --datadir=/srv/mysql --init-file=/tmp/init.sql \
 && rm /tmp/init.sql
USER mysql
ENV DATABASE_URL=mysql://orderdesk@127.0.0.1:3306/orderdesk
ENTRYPOINT []
CMD ["bash", "start_demo.sh"]
