; NSIS installer for the PyAEDT MCP desktop manager.

!ifndef PRODUCT_VERSION
  !define PRODUCT_VERSION "0.1.0"
!endif

!define PRODUCT_NAME "PyAEDT MCP"
!define PRODUCT_PUBLISHER "Synopsys, Inc."
!define PRODUCT_EXECUTABLE "PyAEDT_MCP.exe"
!define PRODUCT_UNINSTALL_KEY "PyAEDTMCP"
!define PRODUCT_ICON "..\assets\pyaedt_mcp_icon.ico"

; Let the installer run per-user (no admin rights needed) or per-machine, like the
; Ansys Python Manager installer.
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_UNINSTALL_KEY}"
!define MULTIUSER_INSTALLMODE_DEFAULT_REGISTRY_KEY "${UNINSTKEY}"
!define MULTIUSER_INSTALLMODE_DEFAULT_REGISTRY_VALUENAME "CurrentUser"
!define MULTIUSER_INSTALLMODE_INSTDIR "ANSYS Inc\${PRODUCT_NAME}"
!define MULTIUSER_INSTALLMODE_COMMANDLINE
!define MULTIUSER_EXECUTIONLEVEL Highest
!define MULTIUSER_MUI

!include "MultiUser.nsh"
!include "MUI2.nsh"

Unicode True
Name "${PRODUCT_NAME}"
OutFile "..\..\dist\PyAEDT-MCP-Installer-windows.exe"
BrandingText "${PRODUCT_PUBLISHER}"
Icon "${PRODUCT_ICON}"

!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\${PRODUCT_EXECUTABLE}"
!define MUI_FINISHPAGE_RUN_TEXT "Launch ${PRODUCT_NAME}"
!define MUI_FINISHPAGE_SHOWREADME
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Create a desktop shortcut"
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED
!define MUI_FINISHPAGE_SHOWREADME_FUNCTION "CreateDesktopShortcut"

!insertmacro MULTIUSER_PAGE_INSTALLMODE
!insertmacro MUI_PAGE_LICENSE "..\..\LICENSE"
!define MUI_PAGE_CUSTOMFUNCTION_PRE oneclickpre
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Function .onInit
  !insertmacro MULTIUSER_INIT
FunctionEnd

Function un.onInit
  !insertmacro MULTIUSER_UNINIT
FunctionEnd

Function CreateDesktopShortcut
  CreateShortCut "$DESKTOP\${PRODUCT_NAME}.lnk" "$INSTDIR\${PRODUCT_EXECUTABLE}"
FunctionEnd

; Hide the wizard window during file copy for a one-click installer feel.
InstProgressFlags smooth
Function oneclickpre
  !insertmacro MUI_HEADER_TEXT "Installing ${PRODUCT_NAME}" "Please wait while the installation completes."
  HideWindow
FunctionEnd

Section "${PRODUCT_NAME}" SEC01
  SetOutPath "$INSTDIR"
  File "..\..\dist\${PRODUCT_EXECUTABLE}"

  CreateDirectory "$SMPROGRAMS\${PRODUCT_NAME}"
  CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\${PRODUCT_NAME}.lnk" "$INSTDIR\${PRODUCT_EXECUTABLE}"
  CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\Uninstall.lnk" "$INSTDIR\uninstall.exe"

  WriteUninstaller "$INSTDIR\uninstall.exe"
  WriteRegStr SHCTX "${UNINSTKEY}" "DisplayName" "${PRODUCT_NAME}"
  WriteRegStr SHCTX "${UNINSTKEY}" "DisplayVersion" "${PRODUCT_VERSION}"
  WriteRegStr SHCTX "${UNINSTKEY}" "Publisher" "${PRODUCT_PUBLISHER}"
  WriteRegStr SHCTX "${UNINSTKEY}" "DisplayIcon" "$INSTDIR\${PRODUCT_EXECUTABLE}"
  WriteRegStr SHCTX "${UNINSTKEY}" "UninstallString" "$\"$INSTDIR\uninstall.exe$\""
  WriteRegDWORD SHCTX "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD SHCTX "${UNINSTKEY}" "NoRepair" 1
  WriteRegStr SHCTX "${UNINSTKEY}" "MultiUser.InstallMode" "$MultiUser.InstallMode"
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\${PRODUCT_NAME}.lnk"
  Delete "$SMPROGRAMS\${PRODUCT_NAME}\${PRODUCT_NAME}.lnk"
  Delete "$SMPROGRAMS\${PRODUCT_NAME}\Uninstall.lnk"
  RMDir "$SMPROGRAMS\${PRODUCT_NAME}"
  Delete "$INSTDIR\${PRODUCT_EXECUTABLE}"
  Delete "$INSTDIR\uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey SHCTX "${UNINSTKEY}"
SectionEnd
