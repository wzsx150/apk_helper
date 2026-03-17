@chcp 65001 >nul
@echo off

title 取消APK右键菜单
setlocal enabledelayedexpansion

set "appname=APK文件信息解析工具"
set "installname=apk_helper.exe"
set "installpath=%~dp0"

:chkadm
pushd "%~dp0"
reg query "HKU\S-1-5-19" >nul 2>nul || ( start "" mshta vbscript:createobject^("shell.application"^).shellexecute^("cmd.exe","/C pushd ""%~dp0"" && ""%~f0""","","runas",1^)^(window.close^) & exit )

:remove_menu
echo.
reg delete "HKCR\.apk\shell\APKHelper" /f 2>nul

echo ☆☆☆☆完成

:out
endlocal
echo.
exit 0

