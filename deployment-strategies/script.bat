@echo off
:loop
curl my-app.st-kpfu-minnullin.ingress.sre-ab.ru
timeout /t 1 /nobreak >nul
goto loop