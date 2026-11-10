#!/bin/bash
# Starts MySQL and the app together inside the live-demo container (see Dockerfile).
trap 'exit 0' TERM INT

# Small buffers keep MySQL near 200 MB, so it fits beside the app in a 512 MB free instance.
mysqld --no-defaults --datadir=/srv/mysql --socket=/tmp/mysql.sock --bind-address=127.0.0.1 --mysqlx=OFF \
  --disable-log-bin --performance-schema=OFF --innodb-buffer-pool-size=32M --innodb-log-buffer-size=4M \
  --table-open-cache=64 --table-definition-cache=400 --max-connections=10 --key-buffer-size=1M &
mysql_pid=$!
until mysqladmin --no-defaults -h127.0.0.1 -uorderdesk --silent ping; do
  kill -0 "$mysql_pid" 2>/dev/null || exit 1
  sleep 1
done

python3.12 -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-10000}" &
wait -n  # if either process dies, stop the container so the host restarts both
