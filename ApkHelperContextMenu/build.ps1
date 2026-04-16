<#
.SYNOPSIS
    APK Helper 右键菜单构建脚本
#>

param(
    [string]$Configuration = "Release",       # 编译配置
    [string]$Platform = "x64",                # 目标平台
    [string]$PfxPassword = "apkhelper123",    # PFX证书密码
    [string]$IcoPath = "1.ico",               # 图标文件路径，相对于脚本目录
    # 输出路径配置（相对于脚本目录）
    [string]$OutputDir = "release",           # 输出目录
    [string]$PfxFileName = "ApkHelperContextMenu.pfx",    # PFX证书文件名
    [string]$MsixFileName = "ApkHelperContextMenu.msix",  # MSIX输出文件名
    [string]$SparsePackageDir = "SparsePackage",          # SparsePackage源目录
    [string]$ProjectFile = "src\ApkHelperContextMenu.vcxproj",  # 项目文件路径
    # Windows SDK工具路径 - 需要安装Windows 10/11 SDK
    # 下载地址: https://developer.microsoft.com/en-us/windows/downloads/windows-sdk/
    # 安装后makeappx.exe和signtool.exe通常位于: C:\Program Files (x86)\Windows Kits\10\bin\<版本号>\x64\
    [string]$MakeAppxPath = "D:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\makeappx.exe",
    [string]$SignToolPath = "D:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\signtool.exe",
    # Visual Studio安装路径 - 需要安装Visual Studio 2019/2022（含C++桌面开发工作负载）
    # 下载地址: https://visualstudio.microsoft.com/downloads/
    # 如果指定的路径不存在，则自动通过vswhere查找
    [string]$VsPath = "d:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# 构建完整路径
$OutputDir = Join-Path $ScriptDir $OutputDir
$pfxPath = Join-Path $OutputDir $PfxFileName
$msixPath = Join-Path $OutputDir $MsixFileName
$SparsePackageDir = Join-Path $ScriptDir $SparsePackageDir
$ProjectFile = Join-Path $ScriptDir $ProjectFile

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "APK Helper 右键菜单构建脚本" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

if (-not (Test-Path $pfxPath)) {
    Write-Host "错误: 未找到证书文件: $pfxPath" -ForegroundColor Red
    Write-Host "请先运行 create_certificate.ps1 创建证书" -ForegroundColor Yellow
    exit 1
}
Write-Host "证书文件: $pfxPath" -ForegroundColor Green

# 步骤1: 从ICO生成PNG图标
Write-Host ""
Write-Host "步骤1: 从ICO生成PNG图标..." -ForegroundColor Green
Add-Type -AssemblyName System.Drawing

# 拼接图标文件完整路径
$IcoPath = Join-Path $ScriptDir $IcoPath

if (-not (Test-Path $IcoPath)) {
    Write-Host "警告: 未找到ICO文件: $IcoPath" -ForegroundColor Yellow
} else {
    $assetsDir = Join-Path $SparsePackageDir "Assets"
    if (-not (Test-Path $assetsDir)) {
        New-Item -ItemType Directory -Path $assetsDir -Force | Out-Null
    }

    $icon = [System.Drawing.Icon]::new($IcoPath)
    Write-Host "  ICO文件已加载" -ForegroundColor Yellow
    
    $sizes = @(256, 128, 64, 48, 32, 16)
    $bestIcon = $null
    $bestSize = 0
    
    foreach ($size in $sizes) {
        try {
            $testIcon = [System.Drawing.Icon]::new($IcoPath, $size, $size)
            if ($testIcon.Width -gt $bestSize) {
                if ($bestIcon -ne $null) { $bestIcon.Dispose() }
                $bestIcon = $testIcon
                $bestSize = $testIcon.Width
            } else {
                $testIcon.Dispose()
            }
        } catch {}
    }
    
    if ($bestIcon -eq $null) {
        $bestIcon = $icon
        $bestSize = $icon.Width
    }
    
    Write-Host "  使用图标尺寸: $bestSize x $bestSize" -ForegroundColor Yellow

    $pngSizes = @{
        "StoreLogo.png" = 50
        "Square44x44Logo.png" = 44
        "Square150x150Logo.png" = 150
    }

    foreach ($item in $pngSizes.GetEnumerator()) {
        $outputPath = Join-Path $assetsDir $item.Key
        $targetSize = $item.Value
        
        $bmp = New-Object System.Drawing.Bitmap($targetSize, $targetSize, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        
        $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
        $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        
        $g.Clear([System.Drawing.Color]::Transparent)
        $rect = New-Object System.Drawing.Rectangle(0, 0, $targetSize, $targetSize)
        $g.DrawIcon($bestIcon, $rect)
        
        $bmp.Save($outputPath, [System.Drawing.Imaging.ImageFormat]::Png)
        
        Write-Host "  已生成: $($item.Key) ($targetSize x $targetSize)" -ForegroundColor Green
        
        $g.Dispose()
        $bmp.Dispose()
    }
    
    if ($bestIcon -ne $icon) { $bestIcon.Dispose() }
    $icon.Dispose()
    Write-Host "图标生成完成!" -ForegroundColor Green
}

# 步骤2: 编译DLL
Write-Host ""
Write-Host "步骤2: 编译DLL..." -ForegroundColor Green

# 检查MSBuild路径
$msbuildFound = $false
$MsbuildPath = ""

# 如果用户指定了VS安装路径，先检查是否存在
if (-not [string]::IsNullOrEmpty($VsPath)) {
    # 用户指定的是VS安装目录，需要拼接MSBuild路径
    if (Test-Path $VsPath) {
        $testPath = Join-Path $VsPath "MSBuild\Current\Bin\MSBuild.exe"
        if (Test-Path $testPath) {
            $MsbuildPath = $testPath
            $msbuildFound = $true
        } else {
            $testPath = Join-Path $VsPath "MSBuild\Current\Bin\amd64\MSBuild.exe"
            if (Test-Path $testPath) {
                $MsbuildPath = $testPath
                $msbuildFound = $true
            }
        }
    }
}

# 如果用户指定的路径不存在，使用vswhere自动查找
if (-not $msbuildFound) {
    $vsWhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vsWhere) {
        $autoVsPath = & $vsWhere -latest -products * -property installationPath 2>$null
        if ($autoVsPath) {
            $testPath = Join-Path $autoVsPath "MSBuild\Current\Bin\MSBuild.exe"
            if (Test-Path $testPath) {
                $MsbuildPath = $testPath
                $msbuildFound = $true
            } else {
                $testPath = Join-Path $autoVsPath "MSBuild\Current\Bin\amd64\MSBuild.exe"
                if (Test-Path $testPath) {
                    $MsbuildPath = $testPath
                    $msbuildFound = $true
                }
            }
        }
    }
}

# 检查MSBuild.exe是否存在
if (-not $msbuildFound) {
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "错误: 未找到MSBuild.exe!" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "请安装Visual Studio 2019/2022（含C++桌面开发工作负载）:" -ForegroundColor Cyan
    Write-Host "  下载地址: https://visualstudio.microsoft.com/downloads/" -ForegroundColor White
    Write-Host "  安装时请勾选\"使用C++的桌面开发\"工作负载" -ForegroundColor White
    Write-Host ""
    Write-Host "安装后MSBuild.exe通常位于:" -ForegroundColor White
    Write-Host "  <VS安装目录>\MSBuild\Current\Bin\MSBuild.exe" -ForegroundColor White
    Write-Host "  例如: C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe" -ForegroundColor White
    Write-Host ""
    Write-Host "也可以通过 -VsPath 参数指定VS安装目录。" -ForegroundColor Cyan
    exit 1
}

Write-Host "  MSBuild: $MsbuildPath" -ForegroundColor Yellow

& $MsbuildPath $ProjectFile /p:Configuration=$Configuration /p:Platform=$Platform /m /v:m
if ($LASTEXITCODE -ne 0) {
    Write-Host "DLL编译失败!" -ForegroundColor Red
    exit 1
}
Write-Host "DLL编译完成!" -ForegroundColor Green

# 步骤3: 准备打包文件
Write-Host ""
Write-Host "步骤3: 准备打包文件..." -ForegroundColor Green

$dllOutputPath = Join-Path $ScriptDir "src\build\$Configuration\ApkHelperContextMenu.dll"
$dllDestPath = Join-Path $SparsePackageDir "ApkHelperContextMenu.dll"

Copy-Item -Path $dllOutputPath -Destination $dllDestPath -Force
Write-Host "  DLL已复制到SparsePackage目录" -ForegroundColor Yellow

$oldMsix = Join-Path $SparsePackageDir "ApkHelperContextMenu.msix"
$oldPfx = Join-Path $SparsePackageDir "ApkHelperContextMenu.pfx"
if (Test-Path $oldMsix) { Remove-Item $oldMsix -Force }
if (Test-Path $oldPfx) { Remove-Item $oldPfx -Force }

$tempPackageDir = Join-Path $ScriptDir "temp_package"
if (Test-Path $tempPackageDir) { Remove-Item $tempPackageDir -Recurse -Force }
New-Item -ItemType Directory -Path $tempPackageDir -Force | Out-Null

Copy-Item -Path (Join-Path $SparsePackageDir "AppxManifest.xml") -Destination $tempPackageDir -Force
Copy-Item -Path (Join-Path $SparsePackageDir "ApkHelperContextMenu.dll") -Destination $tempPackageDir -Force

$assetsDir = Join-Path $SparsePackageDir "Assets"
if (Test-Path $assetsDir) {
    $tempAssetsDir = Join-Path $tempPackageDir "Assets"
    New-Item -ItemType Directory -Path $tempAssetsDir -Force | Out-Null
    Copy-Item -Path "$assetsDir\*.png" -Destination $tempAssetsDir -Force
}

# 步骤4: 打包MSIX
Write-Host ""
Write-Host "步骤4: 打包MSIX..." -ForegroundColor Green

# 检查makeappx.exe是否存在
if (-not (Test-Path $MakeAppxPath)) {
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "错误: 未找到makeappx.exe!" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "期望路径: $MakeAppxPath" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "请安装Windows 10/11 SDK:" -ForegroundColor Cyan
    Write-Host "  下载地址: https://developer.microsoft.com/en-us/windows/downloads/windows-sdk/" -ForegroundColor White
    Write-Host "  安装后makeappx.exe通常位于:" -ForegroundColor White
    Write-Host "  C:\Program Files (x86)\Windows Kits\10\bin\<SdkVersion>\x64\makeappx.exe" -ForegroundColor White
    Write-Host ""
    Write-Host "也可以通过 -MakeAppxPath 参数指定路径。" -ForegroundColor Cyan
    exit 1
}

Write-Host "  makeappx: $MakeAppxPath" -ForegroundColor Yellow

& $MakeAppxPath pack /d $tempPackageDir /p $msixPath /o
if ($LASTEXITCODE -ne 0) {
    Write-Host "MSIX打包失败!" -ForegroundColor Red
    Remove-Item $tempPackageDir -Recurse -Force
    exit 1
}

Remove-Item $tempPackageDir -Recurse -Force
Write-Host "MSIX打包完成!" -ForegroundColor Green

# 步骤5: 签名MSIX
Write-Host ""
Write-Host "步骤5: 签名MSIX..." -ForegroundColor Green

# 检查signtool.exe是否存在
if (-not (Test-Path $SignToolPath)) {
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "错误: 未找到signtool.exe!" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "期望路径: $SignToolPath" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "请安装Windows 10/11 SDK:" -ForegroundColor Cyan
    Write-Host "  下载地址: https://developer.microsoft.com/en-us/windows/downloads/windows-sdk/" -ForegroundColor White
    Write-Host "  安装后signtool.exe通常位于:" -ForegroundColor White
    Write-Host "  C:\Program Files (x86)\Windows Kits\10\bin\<SdkVersion>\x64\signtool.exe" -ForegroundColor White
    Write-Host ""
    Write-Host "也可以通过 -SignToolPath 参数指定路径。" -ForegroundColor Cyan
    exit 1
}

Write-Host "  signtool: $SignToolPath" -ForegroundColor Yellow

& $SignToolPath sign /a /fd SHA256 /f $pfxPath /p $PfxPassword $msixPath
if ($LASTEXITCODE -ne 0) {
    Write-Host "MSIX签名失败!" -ForegroundColor Red
    exit 1
}
Write-Host "MSIX签名完成!" -ForegroundColor Green

# 步骤6: 清理中间文件
Write-Host ""
Write-Host "步骤6: 清理中间文件..." -ForegroundColor Green

# 只清理编译输出目录中的obj中间文件目录
$buildDir = Join-Path $ScriptDir "src\build\$Configuration"
$objDir = Join-Path $buildDir "obj"
if (Test-Path $objDir) {
    Remove-Item $objDir -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "  已清理obj中间文件目录" -ForegroundColor Yellow
}

Write-Host "中间文件清理完成!" -ForegroundColor Green

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "构建完成!" -ForegroundColor Green
Write-Host ""
Write-Host "输出文件:" -ForegroundColor Cyan
Write-Host "  MSIX: $msixPath" -ForegroundColor White
Write-Host "  证书: $pfxPath" -ForegroundColor White
Write-Host ""
Write-Host "发布目录: $OutputDir" -ForegroundColor White
Write-Host "========================================" -ForegroundColor Green
