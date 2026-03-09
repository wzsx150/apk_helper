@chcp 936 >nul
@echo off

title 关联APK
setlocal enabledelayedexpansion

set "appname=APK文件信息解析工具"
set "installname=apk_helper.exe"
set "installpath=%~dp0"

:chkadm
pushd "%~dp0"
reg query "HKU\S-1-5-19" >nul 2>nul || ( start "" mshta vbscript:createobject^("shell.application"^).shellexecute^("cmd.exe","/C pushd ""%~dp0"" && ""%~f0""","","runas",1^)^(window.close^) & exit )

:confirm
if not exist "%installpath%%installname%" (
  echo.
  echo 未找到 "%installname%" 文件！无法继续关联APK文件！ >&2
  goto err_out
)

:install
reg add "HKCR\ApkFile.apkhelper" /ve /t REG_SZ /d "安卓应用安装包" /f 2>nul
reg add "HKCR\ApkFile.apkhelper\DefaultIcon" /ve /t REG_SZ /d "%installpath%%installname%" /f 2>nul
reg add "HKCR\ApkFile.apkhelper\shell\open\command" /ve /t REG_SZ /d "\"%installpath%%installname%\" \"%%1\"" /f 2>nul

reg add "HKCR\Applications\apk_helper.exe\shell\open\command" /ve /t REG_SZ /d "\"%installpath%%installname%\" \"%%1\"" /f 2>nul
reg add "HKCR\Applications\apk_helper.exe\shell\open" /v "FriendlyAppName" /t REG_SZ /d "%appname%" /f 2>nul
reg add "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.apk\OpenWithList" /v "b" /t REG_SZ /d "%installname%" /f 2>nul
reg add "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.apk\OpenWithProgids" /v "ApkFile.apkhelper" /t REG_NONE /d "" /f 2>nul
reg add "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.apk\UserChoice" /v "Progid" /t REG_SZ /d "Applications\%installname%" /f 2>nul

:: 刷新图标，重建图标缓存
ie4uinit.exe -ClearIconCache 2>nul
ie4uinit.exe -Show 2>nul

echo ☆☆☆☆完成
endlocal
exit 0

:err_out
endlocal
REM echo.
REM echo 按任意键退出
REM pause > nul
exit 1

