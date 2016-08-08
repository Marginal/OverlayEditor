; NSIS installation

;--------------------------------
!include "MUI2.nsh"
!include "x64.nsh"

!define MUI_ABORTWARNING
; debug
; !define MUI_FINISHPAGE_NOAUTOCLOSE
; !define MUI_UNFINISHPAGE_NOAUTOCLOSE

SetCompressor /SOLID lzma
RequestExecutionLevel admin

; Installer manifest
Unicode true
ManifestSupportedOS all
ManifestDPIAware true
VIProductVersion "$%VERSION%.0.0"
VIAddVersionKey "FileDescription" "OverlayEditor Installer"
VIAddVersionKey "FileVersion" "$%VERSION%"
VIAddVersionKey "LegalCopyright" "2007-2016 Jonathan Harris"
VIAddVersionKey "ProductName" "OverlayEditor"

Name "OverlayEditor $%VERSION%"
Caption "OverlayEditor Installer"
OutFile "OverlayEditor_$%VER%_win32.exe"
BrandingText "http://marginal.org.uk/x-planescenery"

; !insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

; !insertmacro MUI_UNPAGE_WELCOME
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

!insertmacro MUI_LANGUAGE "English"

; based loosely on http://nsis.sourceforge.net/FileAssoc , but doesn't register an open command, and does set type to text
; see also http://msdn.microsoft.com/en-us/library/windows/desktop/cc144148%28v=vs.85%29.aspx
!macro APP_ASSOCIATE EXT PROGID DESCRIPTION ICON
  !define ID ${__LINE__}
  ; Backup the previous file type
  ReadRegStr $R0 HKCR ".${EXT}" ""
  StrCmp "$R0" "" NoBackup_${ID}		; don't backup if empty
  StrCmp "$R0" "${PROGID}" NoBackup_${ID}	; don't backup if it's registered to us
  WriteRegStr HKCR ".${EXT}" "backup" "$R0"	; backup current value  
NoBackup_${ID}:
  ; Write my file type and ProgID
  WriteRegStr HKCR ".${EXT}" "" "${PROGID}"
  WriteRegStr HKCR ".${EXT}" "Content Type" "text/plain"
  WriteRegStr HKCR ".${EXT}" "PerceivedType" "text"
 
  WriteRegStr HKCR "${PROGID}" "" `${DESCRIPTION}`
  WriteRegStr HKCR "${PROGID}\DefaultIcon" "" `${ICON}`
  !undef ID
!macroend

!macro APP_UNASSOCIATE EXT PROGID
  !define ID ${__LINE__}
  ReadRegStr $R0 HKCR ".${EXT}" ""
  StrCmp "$R0" "${PROGID}" 0 NoRestore_${ID}	; don't restore it if we don't own it
  ReadRegStr $R0 HKCR ".${EXT}" "backup"
  StrCmp "$R0" "" NoRestore_${ID}		; don't restore it if empty
  WriteRegStr HKCR ".${EXT}" "" "$R0"		; restore
  DeleteRegValue HKCR ".${EXT}" "backup"
NoRestore_${ID}:
  ; http://msdn.microsoft.com/en-us/library/windows/desktop/cc144148%28v=vs.85%29.aspx#uninstall says don't delete the file type
  DeleteRegKey HKCR `${PROGID}`
  !undef ID
!macroend


Icon "win32\installer.ico"
UninstallIcon "win32\installer.ico"

Section "Install"

  ; silently uninstall any previous version (which may be in a different location)
  Var /GLOBAL TMPFILE
  ReadRegStr $R0 HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\OverlayEditor" "UninstallString"
  StrCmp $R0 "" doneuninst
  ReadRegStr $R1 HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\OverlayEditor" "InstallLocation"
  StrCmp $R1 "" doneuninst
  GetTempFileName $TMPFILE
  CopyFiles /SILENT /FILESONLY $R0 $TMPFILE.exe
  ExecWait '"$TMPFILE.exe" /S _?=$R1'
  Delete $TMPFILE.exe
  Delete $TMPFILE
  doneuninst:

  SetOutPath "$INSTDIR"

  ; uninstall info
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\OverlayEditor" "DisplayIcon" "$INSTDIR\OverlayEditor.exe,0"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\OverlayEditor" "DisplayName" "OverlayEditor"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\OverlayEditor" "DisplayVersion" "$%VERSION%"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\OverlayEditor" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\OverlayEditor" "Publisher" "Jonathan Harris <x-plane@marginal.org.uk>"
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\OverlayEditor" "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\OverlayEditor" "NoRepair" 1
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\OverlayEditor" "UninstallString" "$INSTDIR\uninstall.exe"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\OverlayEditor" "URLInfoAbout" "mailto:Jonathan Harris <x-plane@marginal.org.uk>?subject=OverlayEditor $%VERSION%"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\OverlayEditor" "URLUpdateInfo" "http://marginal.org.uk/x-planescenery"

  WriteUninstaller "$INSTDIR\uninstall.exe"

  !insertmacro APP_ASSOCIATE "fac" "X-Plane.Fac" "X-Plane Facade"         "$INSTDIR\OverlayEditor.exe,1"
  !insertmacro APP_ASSOCIATE "for" "X-Plane.For" "X-Plane Forest"         "$INSTDIR\OverlayEditor.exe,2"
  !insertmacro APP_ASSOCIATE "lin" "X-Plane.Lin" "X-Plane Painted Line"   "$INSTDIR\OverlayEditor.exe,3"
  !insertmacro APP_ASSOCIATE "obj" "X-Plane.Obj" "X-Plane 3D Object"      "$INSTDIR\OverlayEditor.exe,4"
  !insertmacro APP_ASSOCIATE "pol" "X-Plane.Pol" "X-Plane Draped Polygon" "$INSTDIR\OverlayEditor.exe,5"
  !insertmacro APP_ASSOCIATE "str" "X-Plane.Str" "X-Plane Object String"  "$INSTDIR\OverlayEditor.exe,6"
  !insertmacro APP_ASSOCIATE "agp" "X-Plane.Agp" "X-Plane Autogen Point"  "$INSTDIR\OverlayEditor.exe,7"
  System::Call "shell32::SHChangeNotify(i,i,i,i) (0x08000000, 0x1000, 0, 0)"	; SHCNE_ASSOCCHANGED, SHCNF_FLUSH

SectionEnd

Section "" SEC32
  File /r dist.x86\*
  CreateShortCut "$SMPROGRAMS\OverlayEditor.lnk" "$INSTDIR\OverlayEditor.exe"
SectionEnd

Section "" SEC64
  File /r dist.amd64\*
  CreateShortCut "$SMPROGRAMS\OverlayEditor.lnk" "$INSTDIR\OverlayEditor.exe"
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  Delete "$SMPROGRAMS\OverlayEditor.lnk"; old versions used current user
  SetShellVarContext all
  Delete "$SMPROGRAMS\OverlayEditor.lnk"
  Delete "$INSTDIR\MSVCP71.dll"		; Old Python 2.5 runtime
  Delete "$INSTDIR\MSVCR71.dll"		; Old Python 2.5 runtime
  Delete "$INSTDIR\msvcr90.dll"
  Delete "$INSTDIR\OverlayEditor.exe"
  Delete "$INSTDIR\OverlayEditor.exe.log"
  Delete "$INSTDIR\OverlayEditor.html"	; Old location
  Delete "$INSTDIR\python27.dll"
  Delete "$INSTDIR\*.pyd"
  Delete "$INSTDIR\gdal*.dll"
  Delete "$INSTDIR\libiomp5md.dll"
  Delete "$INSTDIR\openjp2.dll"
  Delete "$INSTDIR\wx*.dll"
  Delete "$INSTDIR\uninstall.exe"
  RMDir /r "$INSTDIR\Microsoft.VC90.CRT"
  Delete "$INSTDIR\Resources\OverlayEditor.html"
  Delete "$INSTDIR\Resources\cacert.pem"
  Delete "$INSTDIR\Resources\*.png"
  Delete "$INSTDIR\Resources\*.vs"
  Delete "$INSTDIR\Resources\*.fs"
  Delete "$INSTDIR\Resources\*.obj"
  Delete "$INSTDIR\Resources\previews\*.jpg"
  RMDir  "$INSTDIR\Resources\previews"
  RMDir  "$INSTDIR\Resources"
  Delete "$INSTDIR\Resources\*.obj"
  Delete "$INSTDIR\win32\DSFTool.exe"
  RMDir  "$INSTDIR\win32"
  RMDir  "$INSTDIR"

  !insertmacro APP_UNASSOCIATE "fac" "X-Plane.Fac"
  !insertmacro APP_UNASSOCIATE "for" "X-Plane.For"
  !insertmacro APP_UNASSOCIATE "lin" "X-Plane.Lin"
  !insertmacro APP_UNASSOCIATE "obj" "X-Plane.Obj"
  !insertmacro APP_UNASSOCIATE "pol" "X-Plane.Pol"
  !insertmacro APP_UNASSOCIATE "str" "X-Plane.Str"
  !insertmacro APP_UNASSOCIATE "agp" "X-Plane.Agp"
  System::Call "shell32::SHChangeNotify(i,i,i,i) (0x08000000, 0x1000, 0, 0)"	; SHCNE_ASSOCCHANGED, SHCNF_FLUSH

  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\OverlayEditor"

SectionEnd

Function .onInit
  ${If} ${RunningX64}
    StrCpy $INSTDIR "$PROGRAMFILES64\OverlayEditor"
    SectionSetFlags ${SEC32} ${SECTION_OFF}
    SectionSetFlags ${SEC64} ${SF_SELECTED}
  ${Else}
    StrCpy $INSTDIR "$PROGRAMFILES32\OverlayEditor"
    SectionSetFlags ${SEC32} ${SF_SELECTED}
    SectionSetFlags ${SEC64} ${SECTION_OFF}
  ${EndIf}
FunctionEnd
