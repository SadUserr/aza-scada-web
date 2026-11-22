@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "DJANGO_DEBUG=1"
title AZA SCADA - Emulador de Nodo Optico (Jetson / Camara)
cd /d "%~dp0"

set "ACCION=%~1"
set "MODO_UNICO=%~2"
set "PY=.venv\Scripts\python.exe"

if not exist "%PY%" goto :err_venv

:check_tokens
if exist ".demo_token.txt" goto :menu_loop
echo [AVISO] Sincronizando credenciales de estacion...
"%PY%" manage.py preparar_demo --con-datos --guardar-tokens
if errorlevel 1 goto :err_prep

:menu_loop
set "TOKEN_DEMO="
set "TOKEN_REVOCAR="
if exist ".demo_token.txt" set /p TOKEN_DEMO=<".demo_token.txt"
if exist ".demo_token_revocar.txt" set /p TOKEN_REVOCAR=<".demo_token_revocar.txt"

if not "%ACCION%"=="" goto :dispatch

echo.
echo ============================================================================
echo   EMULADOR ESTACION OPTICA APP-AZA (NODO JETSON -^> SERVIDOR SCADA)
echo   Servidor destino: http://127.0.0.1:8000  ^|  Receta TF-6 mm (12.0 - 13.0 deg)
echo ============================================================================
echo   [1] Enviar 5 rafagas APROBADAS en vivo   (angulo ~12.5 deg - operacion normal)
echo   [2] Enviar 3 RECHAZOS + ALARMA CRITICA   (angulo ~14.2 deg - fuera de banda)
echo   [3] Probar CREDENCIAL SECUNDARIA         (usa "Camara Auxiliar - Linea 2")
echo   [4] Probar envio a LOTE CERRADO          (LT-DEMO-00 -^> rechazo 409)
echo   [5] Operacion continua de linea          (25 rafagas cada 4 seg)
echo   [6] Salir
echo ----------------------------------------------------------------------------
set "ACCION=1"
set /p "ACCION=Selecciona escenario [1-6] (ENTER = 1): "

:dispatch
if "%ACCION%"=="1" goto :esc_aprobadas
if "%ACCION%"=="2" goto :esc_rechazos
if "%ACCION%"=="3" goto :esc_revocado
if "%ACCION%"=="4" goto :esc_sinreceta
if "%ACCION%"=="5" goto :esc_continua
if "%ACCION%"=="6" goto :fin
goto :esc_aprobadas

:esc_aprobadas
echo.
echo ^>^> Enviando 5 rafagas APROBADAS al lote LT-DEMO-01 (cada 2.5 s)...
"%PY%" simulador.py --token "%TOKEN_DEMO%" --lote LT-DEMO-01 --n 5 --cada 2.5 --centro 12.5
goto :post_run

:esc_rechazos
echo.
echo ^>^> Enviando 3 rafagas FUERA DE TOLERANCIA (~14.2 deg) al lote LT-DEMO-01...
echo    En ~5 s la consola del Operador mostrara RECHAZADO + Alarma Critica.
"%PY%" simulador.py --token "%TOKEN_DEMO%" --lote LT-DEMO-01 --n 3 --cada 2.5 --centro 14.2
goto :post_run

:esc_revocado
echo.
echo ^>^> Enviando lectura con credencial "Camara Auxiliar - Linea 2"...
echo    (Si fue revocada en Administracion -^> Tokens, respondera 401 No autorizado)
"%PY%" simulador.py --token "%TOKEN_REVOCAR%" --lote LT-DEMO-01 --n 2 --cada 2 --centro 12.5
goto :post_run

:esc_sinreceta
echo.
echo ^>^> Probando envio al lote cerrado LT-DEMO-00 (debe bloquearse con 409)...
"%PY%" simulador.py --token "%TOKEN_DEMO%" --lote LT-DEMO-00 --n 2 --cada 2 --centro 16.5
goto :post_run

:esc_continua
echo.
echo ^>^> Operacion continua de linea (25 rafagas cada 4 s, Ctrl+C para detener)...
"%PY%" simulador.py --token "%TOKEN_DEMO%" --lote LT-DEMO-01 --n 25 --cada 4 --centro 12.65
goto :post_run

:post_run
if /i "%MODO_UNICO%"=="--once" goto :fin
set "ACCION="
goto :menu_loop

:err_venv
echo [ERROR] Primero inicia el sistema con iniciar_aza.bat para preparar .venv.
pause
exit /b 1

:err_prep
echo [ERROR] No se pudieron sincronizar las credenciales de estacion.
pause
exit /b 1

:fin
endlocal
