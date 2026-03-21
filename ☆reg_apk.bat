@chcp 936 >nul
@echo off

title 注册关联APK
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

:confirm
if not exist "%installpath%%installname%" (
  echo 未找到 "%installname%" 文件！无法继续关联APK文件！ >&2
  goto err_out
)

:install
:: 赋予权限，否则默认是只有管理员权限才能修改，注意路径最后的 \ 符号
icacls "%installpath%\" /grant "Users:(OI)(CI)(F)" /T /C /Q
icacls "%installpath%\" /grant "Administrators:(OI)(CI)(F)" /T /C /Q
icacls "%installpath%\" /grant "SYSTEM:(OI)(CI)(F)" /T /C /Q

:: 如果存在UserChoice，则删除
reg query "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.apk\UserChoice" /v "Progid" 2>nul 1>nul || goto main_ins
:rm_userchoice
if not exist "%installpath%MinSudo.exe" (
  echo 未找到 "MinSudo.exe" 文件！无法继续关联APK文件！ >&2
  goto err_out
)

for /f "tokens=2 delims=:" %%a in ('WHOAMI /USER /FO LIST') do set "sid=%%a"
set "sid=!sid: =!"

echo 当前用户SID: !sid!
:: 会使用其他进程执行，命令行执行输出正常，exe调用可能接收不到输出
MinSudo.exe --NoLogo -S reg delete "HKEY_USERS\!sid!\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.apk\UserChoice" /f

:main_ins
reg add "HKCR\ApkFile.apkhelper" /ve /t REG_SZ /d "安卓应用安装包" /f 2>nul
reg add "HKCR\ApkFile.apkhelper\DefaultIcon" /ve /t REG_SZ /d "%installpath%%installname%" /f 2>nul
reg add "HKCR\ApkFile.apkhelper\shell\open\command" /ve /t REG_SZ /d "\"!installpath!!installname!\" \"%%1\"" /f 2>nul
reg add "HKCR\.apk" /ve /t REG_SZ /d "ApkFile.apkhelper" /f 2>nul

reg add "HKCR\Applications\apk_helper.exe\shell\open\command" /ve /t REG_SZ /d "\"!installpath!!installname!\" \"%%1\"" /f 2>nul
reg add "HKCR\Applications\apk_helper.exe\shell\open" /v "FriendlyAppName" /t REG_SZ /d "%appname%" /f 2>nul
reg add "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.apk\OpenWithList" /v "MRUList" /t REG_SZ /d "a" /f 2>nul
reg add "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.apk\OpenWithList" /v "a" /t REG_SZ /d "%installname%" /f 2>nul
reg delete "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.apk\OpenWithProgids" /f 2>nul
reg add "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.apk\OpenWithProgids" /v "ApkFile.apkhelper" /t REG_NONE /d "" /f 2>nul
reg add "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.apk\UserChoice" /v "Progid" /t REG_SZ /d "ApkFile.apkhelper" /f 2>nul

echo OoooK

:: 让32位程序能正常调用64位系统命令
set "PATH=%PATH%;%windir%\sysnative"

:: 刷新图标，重建图标缓存，Win11可能无效
ie4uinit.exe -ClearIconCache
ie4uinit.exe -Show

echo ☆☆☆☆完成
endlocal
exit /b 0

:err_out
endlocal
exit /b 1

