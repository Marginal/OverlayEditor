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

Name "OverlayEditor $%VERSION%"
Caption "OverlayEditor $%VERSION% Installer"
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
  Delete "$INSTDIR\OverlayEditor.html"
  Delete "$INSTDIR\python27.dll"
  Delete "$INSTDIR\*.pyd"		; 64bit unbundled
  Delete "$INSTDIR\libiomp5md.dll"	; 64bit unbundled
  Delete "$INSTDIR\wx*.dll"		; 64bit unbundled
  Delete "$INSTDIR\uninstall.exe"
  RMDir /r "$INSTDIR\Microsoft.VC90.CRT"
  RMDir /r "$INSTDIR\Resources"
  RMDir /r "$INSTDIR\win32"
  RMDir "$INSTDIR"

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
