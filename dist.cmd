@echo off

for /f "usebackq tokens=1,2" %%I in (`C:\Progra~1\Python27\python.exe -c "from version import appversion; print '%%4.2f %%d'%%(appversion, round(appversion*100,0))"`) do (set VERSION=%%I&set VER=%%J)

if exist dist  rd /s /q dist
if exist build rd /s /q build
"C:\Program Files\Python27\python.exe" -OO win32\setup.py -q py2exe
"C:\Program Files\NSIS\makensis.exe" /nocd /v2 win32\OverlayEditor.nsi
REM rd  /s /q build
