#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate --noinput

if [ -n "${ADMIN_USER:-}" ] && [ -n "${ADMIN_INITIAL_PASSWORD:-}" ]; then
  python manage.py init_aza
fi
