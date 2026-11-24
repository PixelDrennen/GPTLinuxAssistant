#!/bin/sh
set -eu

cd -- "$(dirname -- "$0")/.."
if [ -x .venv/bin/python ]; then
    exec .venv/bin/python -m assistant_app
fi
exec /usr/bin/python3 -m assistant_app
