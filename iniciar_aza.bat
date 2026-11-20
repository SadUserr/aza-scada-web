@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
title AZA SCADA - Servidor Web de Planta
cd /d "%~dp0"

set "MODO=%~1"
set "NOSERVER=%~2"

echo ============================================================================
echo   ACEROS AZA S.A. - SISTEMA SCADA DE TRAZABILIDAD DEL TREFILADO
echo ============================================================================
echo.

:check_venv
if not exist ".venv\Scripts\python.exe" goto :create_venv
".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
if errorlevel 1 goto :recreate_venv
goto :check_deps

:recreate_venv
echo [1/4] Entorno virtual de otro equipo detectado. Recreando .venv...
rmdir /s /q ".venv"

:create_venv
echo [1/4] Creando entorno virtual Python (.venv)...
python -m venv .venv >nul 2>&1
if not errorlevel 1 goto :check_deps
py -3 -m venv .venv
if errorlevel 1 goto :err_python

:check_deps
set "PY=.venv\Scripts\python.exe"
echo [1/4] Verificando entorno Python y paquetes instalados...
"%PY%" -c "import django" >nul 2>&1
if not errorlevel 1 goto :migrate

:install_deps
echo       Instalando dependencias de requirements.txt (solo la primera vez)...
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 goto :err_pip

:migrate
echo [2/4] Aplicando migraciones de base de datos...
"%PY%" manage.py migrate --noinput
if errorlevel 1 goto :err_migrate

if not "%MODO%"=="" goto :dispatch

:menu
echo.
echo ----------------------------------------------------------------------------
echo   MODO DE INICIO (presiona ENTER para la opcion recomendada [1]):
echo ----------------------------------------------------------------------------
echo   [1] ENTORNO LISTO PARA PRESENTACION (Recomendado)
echo       - Perfiles habilitados: operador1, supervisor1, admin
echo       - Contrasena activa:    Clave#AZA2026
echo       - Historial de 40 inspecciones + lote LT-DEMO-01 abierto
echo       - Sincroniza credenciales locales con simular_captura.bat
echo.
echo   [2] REINICIAR BASE DE DATOS LIMPIA DE CERO
echo       - Respalda db.sqlite3 y recarga las 40 inspecciones iniciales
echo       - Ideal antes de una reunion para limpiar pruebas previas
echo.
echo   [3] MODO PRIMER INGRESO ESTRICTO (cambio obligatorio de clave)
echo       - Igual que [1], pero 'admin' solicita nueva clave al primer ingreso
echo.
echo   [4] SOLO ENCENDER SERVIDOR
echo       - Mantiene usuarios, credenciales y registros actuales sin cambios
echo ----------------------------------------------------------------------------
set "MODO=1"
set /p "MODO=Selecciona opcion [1/2/3/4] (ENTER = 1): "

:dispatch
if "%MODO%"=="1" goto :modo_demo
if /i "%MODO%"=="demo" goto :modo_demo
if "%MODO%"=="2" goto :modo_limpio
if /i "%MODO%"=="limpio" goto :modo_limpio
if "%MODO%"=="3" goto :modo_estricto
if /i "%MODO%"=="estricto" goto :modo_estricto
if "%MODO%"=="4" goto :modo_rapido
if /i "%MODO%"=="rapido" goto :modo_rapido
goto :modo_demo

:modo_demo
echo.
echo [3/4] Preparando estaciones, lote activo y credenciales...
"%PY%" manage.py preparar_demo --con-datos --guardar-tokens
if errorlevel 1 goto :err_prep
goto :resumen_demo

:modo_limpio
echo.
echo [3/4] Reiniciando base local limpia con historial operativo...
if not "%DB_NAME%"=="" goto :prep_limpio
if exist "db.sqlite3" copy /y "db.sqlite3" "db.sqlite3.bak" >nul
if exist "db.sqlite3" del /f /q "db.sqlite3"
"%PY%" manage.py migrate --noinput
if errorlevel 1 goto :err_migrate

:prep_limpio
"%PY%" manage.py preparar_demo --con-datos --guardar-tokens
if errorlevel 1 goto :err_prep
goto :resumen_demo

:modo_estricto
echo.
echo [3/4] Preparando modo de primer ingreso con cambio obligatorio de clave...
"%PY%" manage.py preparar_demo --con-datos --guardar-tokens --forzar-cambio-admin --clave "Cambia#Esto2026"
if errorlevel 1 goto :err_prep
echo.
echo ============================================================================
echo   CREDENCIALES ACTIVAS (CAMBIO OBLIGATORIO EN PRIMER INGRESO ADMIN)
echo ----------------------------------------------------------------------------
echo   URL Navegador :  http://127.0.0.1:8000
echo   Contrasena    :  Cambia#Esto2026
echo   Perfiles      :  admin (exigira nueva clave al entrar), operador1, supervisor1
echo   Emulador Linea:  Abre simular_captura.bat en paralelo para enviar lecturas
echo ============================================================================
goto :arrancar

:modo_rapido
echo.
echo [3/4] Iniciando sin modificar cuentas ni tokens actuales...
echo.
echo ============================================================================
echo   SERVIDOR LISTO EN: http://127.0.0.1:8000
echo ============================================================================
goto :arrancar

:resumen_demo
echo.
echo ============================================================================
echo   SISTEMA SCADA LISTO (ACEROS AZA - PLANTA RENCA)
echo ----------------------------------------------------------------------------
echo   URL Navegador :  http://127.0.0.1:8000
echo   Contrasena    :  Clave#AZA2026
echo   Usuarios      :  operador1    (Monitoreo en linea + alarmas en vivo)
echo                    supervisor1  (Indicadores SPC, tendencias y exportar CSV)
echo                    admin        (Usuarios, recetas, lotes y credenciales)
echo   Emulador Linea:  Doble clic en simular_captura.bat
echo ============================================================================

:arrancar
if /i "%NOSERVER%"=="--no-server" goto :fin
echo.
echo [4/4] Abriendo navegador y encendiendo servidor web (Ctrl+C para detener)...
echo       IMPORTANTE: Deja esta ventana abierta mientras usas el navegador.
echo.
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:8000"
"%PY%" manage.py runserver 127.0.0.1:8000
goto :fin

:err_python
echo [ERROR] No se encontro Python 3 instalado en el sistema. Instala Python 3.11+.
pause
exit /b 1

:err_pip
echo [ERROR] Fallo la instalacion de requirements.txt. Revisa tu conexion a internet.
pause
exit /b 1

:err_migrate
echo [ERROR] Fallo la ejecucion de migraciones (manage.py migrate).
pause
exit /b 1

:err_prep
echo [ERROR] Fallo la preparacion inicial (asegurate de que DJANGO_DEBUG no sea 0).
pause
exit /b 1

:fin
endlocal
