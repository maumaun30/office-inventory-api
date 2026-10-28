#!/bin/sh
set -e

# Apply migrations before serving. Set RUN_MIGRATIONS=0 when running several
# replicas and migrating as a separate release step instead.
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
    alembic upgrade head
fi

exec "$@"
