#!/usr/bin/env bash
# One-step local setup for macOS / Linux.
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
echo "==> Creating virtual environment (venv)"
$PY -m venv venv
source venv/bin/activate
echo "==> Installing dependencies"
pip install --upgrade pip >/dev/null
pip install -r requirements.txt
if [ ! -f .env ]; then
  echo "==> Creating .env with a fresh secret key"
  python -c "import re; from django.core.management.utils import get_random_secret_key as g; s=open('.env.example').read(); open('.env','w').write(re.sub(r'(?m)^DJANGO_SECRET_KEY=.*$', lambda m: 'DJANGO_SECRET_KEY=' + chr(39) + g() + chr(39), s))"
fi
echo "==> Preparing database"
python manage.py migrate
python manage.py seed_demo --reset
echo
echo "Done. Start the server with:"
echo "  source venv/bin/activate && python manage.py runserver"
echo "then open http://127.0.0.1:8000/"
