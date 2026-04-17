@chcp 936 >nul
@echo off

title 获取目录修改权限
echo ====

set "appname=APK文件信息解析工具"
set "installname=apk_helper.exe"
set "installpath=%~dp0"
set batpath="""%~f0"""

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

:file_perm
:: 赋予权限，否则默认是只有管理员权限才能修改，注意路径最后的 \ 符号
icacls "!installpath!\" /grant "Users:(OI)(CI)(F)" /T /C /Q
icacls "!installpath!\" /grant "Administrators:(OI)(CI)(F)" /T /C /Q
icacls "!installpath!\" /grant "SYSTEM:(OI)(CI)(F)" /T /C /Q

echo OoooK
echo ☆☆☆☆完成
endlocal
exit /b 0

:err_out
endlocal
exit /b 1

