@echo off
@setlocal

for /f "usebackq tokens=1,2" %%I in (`c:\Progra~1\Python24\python.exe -c "from files import appversion; print '%%4.2f %%d'%%(appversion, appversion*100)"`) do (set VERSION=%%I&set VER=%%J)

@if exist OverlayEditor_%VER%_src.zip del OverlayEditor_%VER%_src.zip
@if exist OverlayEditor_%VER%_linux.tar.gz del OverlayEditor_%VER%_linux.tar.gz
@if exist OverlayEditor_%VER%_mac.zip del OverlayEditor_%VER%_mac.zip
@if exist OverlayEditor_%VER%_win32.exe del OverlayEditor_%VER%_win32.exe

rd  /s /q OverlayEditor.app
REM >nul: 2>&1
del /s /q dist  >nul: 2>&1
del /s /q *.bak >nul: 2>&1
del /s /q *.pyc >nul: 2>&1

@set PY=OverlayEditor.py draw.py files.py DSFLib.py
@set DATA=OverlayEditor.html
@set RSRC=Resources/add.png Resources/background.png Resources/delete.png Resources/goto.png Resources/help.png Resources/import.png Resources/new.png Resources/open.png Resources/OverlayEditor.png Resources/prefs.png Resources/reload.png Resources/save.png Resources/undo.png Resources/default.obj Resources/Sea01.png Resources/screenshot.png

@REM source
zip -r OverlayEditor_%VER%_src.zip dist.cmd %PY% %DATA% %RSRC% linux MacOS win32 |findstr -vc:"adding:"

@REM linux
tar -zcf OverlayEditor_%VER%_linux.tar.gz %PY% %DATA% %RSRC% linux win32/DSFTool.exe

@REM mac
mkdir OverlayEditor.app\Contents
for %%I in (%DATA%) do (copy %%I OverlayEditor.app\Contents\ |findstr -v "file(s) copied")
xcopy /q /e MacOS OverlayEditor.app\Contents\MacOS\|findstr -v "file(s) copied"
for %%I in (%PY%) do (copy %%I OverlayEditor.app\Contents\MacOS\ |findstr -v "file(s) copied")
mkdir OverlayEditor.app\Contents\Resources
for %%I in (%RSRC%) do (copy Resources\%%~nxI OverlayEditor.app\Contents\Resources\ |findstr -v "file(s) copied")
del  OverlayEditor.app\Contents\MacOS\OverlayEditor.html
move OverlayEditor.app\Contents\MacOS\Info.plist OverlayEditor.app\Contents\
move OverlayEditor.app\Contents\MacOS\OverlayEditor.icns OverlayEditor.app\Contents\Resources\
move /y OverlayEditor.app\Contents\MacOS\*.png OverlayEditor.app\Contents\Resources\ |findstr -vc:".png"
zip -j OverlayEditor_%VER%_mac.zip MacOS/OverlayEditor.html |findstr -vc:"adding:"
zip -r OverlayEditor_%VER%_mac.zip OverlayEditor.app |findstr -vc:"adding:"

@REM win32
win32\setup.py -q py2exe
REM @set cwd="%CD%"
REM cd dist
REM zip -r ..\OverlayEditor_%VER%_win32.zip * |findstr -vc:"adding:"
"C:\Program Files\NSIS\makensis.exe" /nocd /v2 win32\OverlayEditor.nsi
REM @cd %cwd%
rd  /s /q build

:end
