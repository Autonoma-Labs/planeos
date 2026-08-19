#!/bin/bash
# Single-container entrypoint for ephemeral preview environments.
#
# A preview runs one container per app, so there are no separate migrator,
# worker or beat containers the way docker-compose.yml has. This applies the
# migrations first and then runs the celery worker alongside the API server.
set -e

python manage.py wait_for_db
python manage.py migrate

MACHINE_SIGNATURE=$(echo "${HOSTNAME}-${AUTONOMA_PREVIEWKIT_PR:-base}" | sha256sum | awk '{print $1}')
export MACHINE_SIGNATURE

python manage.py register_instance "$MACHINE_SIGNATURE"
python manage.py configure_instance

# Object storage is optional in a preview; only create the bucket when one is wired up.
if [ -n "${AWS_S3_ENDPOINT_URL}" ]; then
	python manage.py create_bucket || echo "create_bucket failed; file uploads will not work in this preview"
fi

# Ordering between apps and services is not guaranteed, so a cold cache is not fatal.
python manage.py clear_cache || echo "clear_cache skipped: cache not reachable yet"
python manage.py collectstatic --noinput

# The solo pool keeps the worker to a single process, which matters when the
# API server and the worker share one preview container's memory limit.
celery -A plane worker -l info --pool="${CELERY_POOL:-solo}" &

exec gunicorn -w "${GUNICORN_WORKERS:-1}" -k uvicorn.workers.UvicornWorker plane.asgi:application \
	--bind 0.0.0.0:"${PORT:-8000}" --max-requests 1200 --max-requests-jitter 1000 --access-logfile -
