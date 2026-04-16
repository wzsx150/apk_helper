@chcp 936 >nul
@echo off

title 取消APK右键菜单
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

:remove_menu
reg delete "HKCR\SystemFileAssociations\.apk\shell\APKHelper" /f 2>nul

echo OoooK
echo ☆☆☆☆完成
endlocal
exit /b 0

