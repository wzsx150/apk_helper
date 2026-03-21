@chcp 936 >nul
@echo off

title 取消APK右键菜单
echo ====

:chkadm
pushd "%~dp0"
reg query "HKU\S-1-5-19" >nul 2>nul || ( 
  start "" mshta vbscript:createobject^("shell.application"^).shellexecute^("cmd.exe","/C pushd ""%~dp0"" && ""%~f0""","","runas",1^)^(window.close^) && exit /b 0 || exit /b 2
)

setlocal enabledelayedexpansion
set "appname=APK文件信息解析工具"
set "installname=apk_helper.exe"
set "installpath=%~dp0"

:remove_menu
reg delete "HKCR\SystemFileAssociations\.apk\shell\APKHelper" /f 2>nul

echo OoooK
echo ☆☆☆☆完成

:out
endlocal
exit /b 0

