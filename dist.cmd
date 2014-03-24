@echo off

for /f "usebackq tokens=1,2" %%I in (`C:\Progra~1\Python27\python.exe -c "from version import appversion; print '%%4.2f %%d'%%(appversion, round(appversion*100,0))"`) do (set VERSION=%%I&set VER=%%J)

if exist build      rd /s /q build
if exist dist.amd64 rd /s /q dist.amd64
if exist dist.x86   rd /s /q dist.x86
set OLD_PATH=%PATH%
set PATH=%OLDPATH%;\src\gdal-1.10.1\build.amd64\bin;\src\openjpeg-2.0\build.amd64\bin
"C:\Program Files\Python27\python.exe" -OO win32\setup.py -q py2exe
set PATH=%OLDPATH%;\src\gdal-1.10.1\build.x86\bin;\src\openjpeg-2.0\build.x86\bin
"C:\Program Files (x86)\Python27\python.exe" -OO win32\setup.py -q py2exe
if exist dist.x86\w9xpopen.exe del dist.x86\w9xpopen.exe
set PATH=%OLD_PATH%
"C:\Program Files (x86)\NSIS\makensis.exe" /nocd /v2 win32\OverlayEditor.nsi
