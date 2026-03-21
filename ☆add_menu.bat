@chcp 936 >nul
@echo off

title 添加APK右键菜单
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
set "menuname=使用 APK Helper 打开"

:confirm
if not exist "%installpath%%installname%" (
  echo 未找到 "%installname%" 文件！无法继续添加右键菜单！ >&2
  goto err_out
)

:add_menu
icacls "%installpath%\" /grant "Users:(OI)(CI)(F)" /T /C /Q
icacls "%installpath%\" /grant "Administrators:(OI)(CI)(F)" /T /C /Q
icacls "%installpath%\" /grant "SYSTEM:(OI)(CI)(F)" /T /C /Q

reg add "HKCR\SystemFileAssociations\.apk\shell\APKHelper" /ve /t REG_SZ /d "%menuname%" /f 2>nul
reg add "HKCR\SystemFileAssociations\.apk\shell\APKHelper" /v "Icon" /t REG_SZ /d "%installpath%%installname%" /f 2>nul
reg add "HKCR\SystemFileAssociations\.apk\shell\APKHelper\command" /ve /t REG_SZ /d "\"!installpath!!installname!\" \"%%1\"" /f 2>nul

echo OoooK
echo ☆☆☆☆完成
endlocal
exit /b 0

:err_out
endlocal
exit /b 1

