@chcp 936 >nul
@echo off

title 取消关联APK
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

:clean
reg delete "HKCR\ApkFile.apkhelper" /f 2>nul
reg delete "HKCR\Applications\apk_helper.exe" /f 2>nul
rem reg delete "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.apk\OpenWithList" /f 2>nul
reg delete "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.apk\OpenWithProgids" /v "ApkFile.apkhelper" /f 2>nul

reg query "HKCR\.apk" /ve  2>nul | findstr "ApkFile.apkhelper" 2>nul 1>nul && (
  reg add "HKCR\.apk" /ve /t REG_SZ /d "" /f 2>nul
)

reg query "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.apk\UserChoice" /v "Progid" 2>nul | findstr "ApkFile.apkhelper" 2>nul 1>nul || goto ook
:rm_userchoice
if not exist "%installpath%MinSudo.exe" (
  echo 未找到 "MinSudo.exe" 文件！无法继续取消关联APK文件！ >&2
  goto err_out
)

for /f "tokens=2 delims=:" %%a in ('WHOAMI /USER /FO LIST') do set "sid=%%a"
set "sid=!sid: =!"

echo 当前用户SID: !sid!
:: 会使用其他进程执行，命令行执行输出正常，exe调用可能接收不到输出
MinSudo.exe --NoLogo -S reg delete "HKEY_USERS\!sid!\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.apk\UserChoice" /f

:ook
echo OoooK

:: 让32位程序能正常调用64位系统命令
set "PATH=%PATH%;%windir%\sysnative"

:: 刷新图标，重建图标缓存，Win11可能无效
ie4uinit.exe -ClearIconCache
ie4uinit.exe -Show

echo ☆☆☆☆完成

:out
endlocal
exit /b 0

:err_out
endlocal
exit /b 1
