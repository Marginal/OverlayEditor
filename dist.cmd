@echo off

for /f "usebackq tokens=1,2" %%I in (`C:\Progra~1\Python27\python.exe -c "from version import appversion; print '%%4.2f %%d'%%(appversion, round(appversion*100,0))"`) do (set VERSION=%%I&set VER=%%J)

if exist build      rd /s /q build
if exist dist.amd64 rd /s /q dist.amd64
if exist dist.x86   rd /s /q dist.x86
"C:\Program Files\Python27\python.exe" -OO win32\setup.py -q py2exe
"C:\Program Files (x86)\Python27\python.exe" -OO win32\setup.py -q py2exe
if exist dist.x86\w9xpopen.exe del dist.x86\w9xpopen.exe
"C:\Program Files (x86)\NSIS\makensis.exe" /nocd /v2 win32\OverlayEditor.nsi
