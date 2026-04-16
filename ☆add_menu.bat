@chcp 936 >nul
@echo off

title 添加APK右键菜单
echo ====

set "appname=APK文件信息解析工具"
set "installname=apk_helper.exe"
set "installpath=%~dp0"
set batpath="""%~f0"""
set "menuname=使用 APK Helper 打开"

:chkadm
pushd "%~dp0"
reg query "HKU\S-1-5-19" >nul 2>nul || ( 
  for /f "tokens=1-4 delims=.[]" %%1 in ( 'ver' ) do (
    if %%4 geq 22000 (
      setlocal EnableDelayedExpansion
      powershell "start cmd.exe -arg '/c \"!batpath:'=''!\"' -verb runas" && exit /b 0 || exit /b 2
    ) else (
      start "" mshta vbscript:createobject^("shell.application"^).shellexecute^("cmd.exe","/C pushd ""%~dp0"" && ""%~f0""","","runas",1^)^(window.close^) && exit /b 0 || exit /b 2
    )
  )
  exit /b 100
)
setlocal EnableDelayedExpansion

:confirm
if not exist "!installpath!!installname!" (
  echo 未找到 "!installname!" 文件！无法继续添加右键菜单！ >&2
  goto err_out
)

:add_menu
:: 赋予权限，否则默认是只有管理员权限才能修改，注意路径最后的 \ 符号
icacls "!installpath!\" /grant "Users:(OI)(CI)(F)" /T /C /Q
icacls "!installpath!\" /grant "Administrators:(OI)(CI)(F)" /T /C /Q
icacls "!installpath!\" /grant "SYSTEM:(OI)(CI)(F)" /T /C /Q

reg add "HKCR\SystemFileAssociations\.apk\shell\APKHelper" /ve /t REG_SZ /d "%menuname%" /f 2>nul
reg add "HKCR\SystemFileAssociations\.apk\shell\APKHelper" /v "Icon" /t REG_SZ /d "!installpath!!installname!" /f 2>nul
reg add "HKCR\SystemFileAssociations\.apk\shell\APKHelper\command" /ve /t REG_SZ /d "\"!installpath!!installname!\" \"%%1\"" /f 2>nul

reg delete "HKCR\SystemFileAssociations\.apk\APKHelperEx" /f 2>nul

echo OoooK
echo ☆☆☆☆完成
endlocal
exit /b 0

:err_out
endlocal
exit /b 1

