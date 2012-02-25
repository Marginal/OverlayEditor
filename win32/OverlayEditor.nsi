; NSIS installation

;--------------------------------
!include "MUI.nsh"

!define MUI_ABORTWARNING

SetCompressor /SOLID lzma
RequestExecutionLevel admin

Name "OverlayEditor $%VERSION%"
Caption "OverlayEditor $%VERSION% Installer"
OutFile "OverlayEditor_$%VER%_win32.exe"
InstallDir "$PROGRAMFILES\OverlayEditor"
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
  SetOutPath "$INSTDIR"
  File /r dist\*

  Delete "$INSTDIR\OverlayEditor.exe.log"
  SetShellVarContext current
  Delete "$SMPROGRAMS\OverlayEditor.lnk"; old versions used current user
  SetShellVarContext all
  CreateShortCut "$SMPROGRAMS\OverlayEditor.lnk" "$INSTDIR\OverlayEditor.exe"

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


Section "Uninstall"
  SetShellVarContext current
  Delete "$SMPROGRAMS\OverlayEditor.lnk"; old versions used current user
  SetShellVarContext all
  Delete "$SMPROGRAMS\OverlayEditor.lnk"
  Delete "$INSTDIR\MSVCR71.dll"
  Delete "$INSTDIR\OverlayEditor.exe"
  Delete "$INSTDIR\OverlayEditor.exe.log"
  Delete "$INSTDIR\OverlayEditor.html"
  Delete "$INSTDIR\uninstall.exe"
  RMDir /r "$INSTDIR\Resources"
  RMDir /r "$INSTDIR\win32"
  RMDir "$INSTDIR"

  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\OverlayEditor"
SectionEnd
