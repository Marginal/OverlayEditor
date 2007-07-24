@echo off
@setlocal

for /f "usebackq tokens=1,2,3" %%I in (`c:\Progra~1\Python24\python.exe -c "from version import appversion; print '%%4.2f %%d'%%(appversion, round(appversion*100,0))"`) do (set VERSION=%%I&set VER=%%J)
set RELEASE=1
set RPM=%TMP%\overlayeditor

@if exist OverlayEditor_%VER%_src.zip del OverlayEditor_%VER%_src.zip
@if exist overlayeditor-%VERSION%-%RELEASE%.i386.rpm del overlayeditor-%VERSION%-%RELEASE%.i386.rpm
@if exist overlayeditor_%VERSION%-%RELEASE%_i386.deb del overlayeditor_%VERSION%-%RELEASE%_i386.deb
@if exist OverlayEditor_%VER%_mac.zip del OverlayEditor_%VER%_mac.zip
@if exist OverlayEditor_%VER%_win32.exe del OverlayEditor_%VER%_win32.exe

if exist OverlayEditor.app rd /s /q OverlayEditor.app
if exist "%RPM%" rd /s /q "%RPM%"
REM >nul: 2>&1
if exist dist rd /s /q dist >nul: 2>&1
REM del /s /q *.bak >nul: 2>&1
del /s /q *.pyc >nul: 2>&1

@set PY=OverlayEditor.py draw.py files.py DSFLib.py MessageBox.py version.py
@set DATA=OverlayEditor.html
@set RSRC=Resources/add.png Resources/background.png Resources/delete.png Resources/goto.png Resources/help.png Resources/import.png Resources/new.png Resources/open.png Resources/prefs.png Resources/reload.png Resources/save.png Resources/undo.png Resources/default.fac Resources/default.for Resources/default.obj Resources/windsock.obj Resources/windsock.png Resources/exc.png Resources/fac.png Resources/obj.png Resources/airport0_000.png Resources/Sea01.png Resources/OverlayEditor.png Resources/screenshot.jpg Resources/800library.txt
@set PREV=Resources/previews

@REM source
REM zip -r OverlayEditor_%VER%_src.zip dist.cmd %PY% %DATA% %RSRC% %PREV% linux MacOS win32 |findstr -vc:"adding:"

@REM linux
REM tar -zcf OverlayEditor_%VER%_linux.tar.gz %PY% %DATA% %RSRC% linux win32/DSFTool.exe
set RPMRT=%TMP%\overlayeditor\root
mkdir "%RPM%\BUILD"
mkdir "%RPM%\SOURCES"
mkdir "%RPM%\RPMS\i386"
mkdir "%RPMRT%\usr\local\bin"
mkdir "%RPMRT%\usr\local\lib\overlayeditor\Resources"
mkdir "%RPMRT%\usr\local\lib\overlayeditor\Resources\previews"
mkdir "%RPMRT%\usr\local\lib\overlayeditor\linux"
mkdir "%RPMRT%\usr\local\lib\overlayeditor\win32"
copy linux\overlayeditor.desktop "%RPMRT%\usr\local\lib\overlayeditor" |findstr -v "file(s) copied"
copy linux\OverlayEditor.xpm "%RPM%\SOURCES" |findstr -v "file(s) copied"
echo BuildRoot: /tmp/overlayeditor/root > "%RPM%\overlayeditor.spec"
echo Version: %VERSION% >> "%RPM%\overlayeditor.spec"
echo Release: %RELEASE% >> "%RPM%\overlayeditor.spec"
type linux\overlayeditor.spec    >> "%RPM%\overlayeditor.spec"
copy linux\overlayeditor "%RPMRT%\usr\local\bin" |findstr -v "file(s) copied"
for %%I in (%DATA%) do (copy %%I "%RPMRT%\usr\local\lib\overlayeditor" |findstr -v "file(s) copied")
for %%I in (%PY%) do (copy %%I "%RPMRT%\usr\local\lib\overlayeditor" |findstr -v "file(s) copied")
for %%I in (%RSRC%) do (copy Resources\%%~nxI "%RPMRT%\usr\local\lib\overlayeditor\Resources\" |findstr -v "file(s) copied")
for %%I in (%PREV%\*.jpg) do (copy Resources\previews\%%~nxI "%RPMRT%\usr\local\lib\overlayeditor\Resources\previews\" |findstr -v "file(s) copied")
for %%I in (linux\DSFTool) do (copy %%I "%RPMRT%\usr\local\lib\overlayeditor\linux" |findstr -v "file(s) copied")
for %%I in (win32\DSFTool.exe) do (copy %%I "%RPMRT%\usr\local\lib\overlayeditor\win32" |findstr -v "file(s) copied")
"C:\Program Files\cygwin\lib\rpm\rpmb.exe" --quiet -bb --target i386-pc-linux --define '_topdir /tmp/overlayeditor' /tmp/overlayeditor/overlayeditor.spec
move "%RPM%\RPMS\i386\overlayeditor-%VERSION%-%RELEASE%.cygwin.i386.rpm" overlayeditor-%VERSION%-%RELEASE%.i386.rpm
REM Debian/Ubuntu
mkdir "%RPMRT%\DEBIAN"
mkdir "%RPMRT%\usr\share\applications"
mkdir "%RPMRT%\usr\share\icons\hicolor\48x48\apps"
copy linux\overlayeditor.desktop "%RPMRT%\usr\share\applications" |findstr -v "file(s) copied"
copy Resources\OverlayEditor.png "%RPMRT%\usr\share\icons\hicolor\48x48\apps\overlayeditor.png" |findstr -v "file(s) copied"
echo Version: %VERSION%-%RELEASE% > "%RPMRT%\DEBIAN\control"
type linux\control >> "%RPMRT%\DEBIAN\control"
copy linux\postinst "%RPMRT%\DEBIAN" |findstr -v "file(s) copied"
REM copy linux\postrm   "%RPMRT%\DEBIAN" |findstr -v "file(s) copied"
chmod -R 755 "%RPMRT%"
for /r "%RPMRT%" %%I in (*) do chmod 644 "%%I"
chmod -R 755 "%RPMRT%\DEBIAN\postinst"
REM chmod -R 755 "%RPMRT%\DEBIAN\postrm"
chmod -R 755 "%RPMRT%\usr\local\bin\overlayeditor"
chmod -R 755 "%RPMRT%\usr\local\lib\overlayeditor\linux"
chmod -R 755 "%RPMRT%\usr\local\lib\overlayeditor\win32"
chown -R root:root "%RPMRT%"
dpkg-deb -b /tmp/overlayeditor/root .
chown -R %USERNAME% "%RPMRT%"

@REM mac
mkdir OverlayEditor.app\Contents
for %%I in (%DATA%) do (copy %%I OverlayEditor.app\Contents\ |findstr -v "file(s) copied")
xcopy /q /e MacOS OverlayEditor.app\Contents\MacOS\|findstr -v "file(s) copied"
for /r OverlayEditor.app %%I in (CVS) do rd /s /q "%%I" >nul: 2>&1
for /r OverlayEditor.app %%I in (.cvs*) do del /q "%%I" >nul:
for /r OverlayEditor.app %%I in (*.bak) do del /q "%%I" >nul:
for /r OverlayEditor.app %%I in (*.pspimage) do del /q "%%I" >nul:
for %%I in (%PY%) do (copy %%I OverlayEditor.app\Contents\MacOS\ |findstr -v "file(s) copied")
mkdir OverlayEditor.app\Contents\Resources
for %%I in (%RSRC%) do (copy Resources\%%~nxI OverlayEditor.app\Contents\Resources\ |findstr -v "file(s) copied")
mkdir OverlayEditor.app\Contents\Resources\previews
for %%I in (%PREV%\*.jpg) do (copy Resources\previews\%%~nxI OverlayEditor.app\Contents\Resources\previews |findstr -v "file(s) copied")
del  OverlayEditor.app\Contents\MacOS\OverlayEditor.html
sed s/appversion/%VERSION%/ <OverlayEditor.app\Contents\MacOS\Info.plist >OverlayEditor.app\Contents\Info.plist
del OverlayEditor.app\Contents\MacOS\Info.plist
move OverlayEditor.app\Contents\MacOS\OverlayEditor.icns OverlayEditor.app\Contents\Resources\
move OverlayEditor.app\Contents\MacOS\screenshot.jpg OverlayEditor.app\Contents\Resources\
move /y OverlayEditor.app\Contents\MacOS\*.png OverlayEditor.app\Contents\Resources\ |findstr -vc:".png"
zip -j OverlayEditor_%VER%_mac.zip MacOS/OverlayEditor.html |findstr -vc:"adding:"
zip -r OverlayEditor_%VER%_mac.zip OverlayEditor.app |findstr -vc:"adding:"

@REM win32
"C:\Program Files\Python24\python.exe" -OO win32\setup.py -q py2exe
REM @set cwd="%CD%"
REM cd dist
REM zip -r ..\OverlayEditor_%VER%_win32.zip * |findstr -vc:"adding:"
"C:\Program Files\NSIS\makensis.exe" /nocd /v2 win32\OverlayEditor.nsi
REM @cd %cwd%
rd  /s /q build

:end
