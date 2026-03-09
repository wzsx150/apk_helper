@chcp 936 >nul
@echo off

title 取消关联APK
setlocal enabledelayedexpansion

set "appname=APK文件信息解析工具"
set "installname=apk_helper.exe"
set "installpath=%~dp0"

:chkadm
pushd "%~dp0"
reg query "HKU\S-1-5-19" >nul 2>nul || ( start "" mshta vbscript:createobject^("shell.application"^).shellexecute^("cmd.exe","/C pushd ""%~dp0"" && ""%~f0""","","runas",1^)^(window.close^) & exit )

:clean
echo.
reg delete "HKCR\ApkFile.apkhelper" /f 2>nul
reg delete "HKCR\Applications\apk_helper.exe" /f 2>nul
reg delete "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.apk\OpenWithProgids" /v "ApkFile.apkhelper" /f 2>nul

:: 刷新图标，重建图标缓存
ie4uinit.exe -ClearIconCache 2>nul
ie4uinit.exe -Show 2>nul

echo ☆☆☆☆完成

:out
endlocal
echo.
exit 0

