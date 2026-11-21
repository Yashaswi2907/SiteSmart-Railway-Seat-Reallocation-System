@echo off
REM One-step local setup for Windows.
cd /d "%~dp0"
echo ==^> Creating virtual environment (venv)
python -m venv venv || goto :error
call venv\Scripts\activate.bat
echo ==^> Installing dependencies
python -m pip install --upgrade pip >nul
pip install -r requirements.txt || goto :error
if not exist .env (
  echo ==^> Creating .env with a fresh secret key
  python -c "import re; from django.core.management.utils import get_random_secret_key as g; s=open('.env.example').read(); open('.env','w').write(re.sub(r'(?m)^DJANGO_SECRET_KEY=.*$', lambda m: 'DJANGO_SECRET_KEY=' + chr(39) + g() + chr(39), s))" || goto :error
)
echo ==^> Preparing database
python manage.py migrate || goto :error
python manage.py seed_demo --reset || goto :error
echo.
echo Done. Start the server with:
echo   venv\Scripts\activate ^&^& python manage.py runserver
echo then open http://127.0.0.1:8000/
goto :eof
:error
echo Setup failed. See the messages above.
exit /b 1
