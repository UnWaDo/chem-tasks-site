#!/bin/sh
# Обновление сайта после загрузки новой версии кода (запускать от пользователя chem в /srv/chem/app)
set -e
cd /srv/chem/app
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart chem
