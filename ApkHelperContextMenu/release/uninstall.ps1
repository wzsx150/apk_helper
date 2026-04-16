<#
.SYNOPSIS
    卸载 APK Helper Win11新版右键菜单

.DESCRIPTION
    此脚本仅针对当前用户卸载 Sparse Package 并移除 Win11 新版右键菜单扩展。

.NOTES
    适用于 Windows 11（build >= 22000），仅当前用户卸载，无需管理员权限
#>

param(
    # MSIX包名称
    [string]$PackageName = "ApkHelperContextMenu",
    # 输出文件路径参数，用于 Python 捕获输出
    [string]$OutputFile = ""
)

$ErrorActionPreference = "Stop"

function Write-Output-Content {
    param([string]$Message, [string]$Color = "White")

    Write-Host $Message -ForegroundColor $Color

    if ($OutputFile -ne "") {
        Add-Content -LiteralPath $OutputFile -Value $Message -Encoding UTF8
    }
}

if ($OutputFile -ne "") {
    $dir = Split-Path -Parent $OutputFile
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    Set-Content -LiteralPath $OutputFile -Value "" -Encoding UTF8 -NoNewline
}

Write-Output-Content "卸载 APK Helper Context Menu" "Cyan"

# 检查 Windows 版本（需要 Windows 11 build >= 22000）
$buildNumber = [System.Environment]::OSVersion.Version.Build
Write-Output-Content "当前系统版本: build $buildNumber" "Yellow"
if ($buildNumber -lt 22000) {
    Write-Output-Content "错误: 此脚本仅适用于 Windows 11 (build >= 22000)" "Red"
    exit 1
}

Write-Output-Content "步骤1: 删除注册表项..." "Green"
try {
    & reg delete "HKCR\SystemFileAssociations\.apk\shell\APKHelper" /f 2>$null | Out-Null
    Write-Output-Content "  传统右键菜单注册表项已删除" "Green"
} catch {}
try {
    & reg delete "HKCR\SystemFileAssociations\.apk\APKHelperEx" /f 2>$null | Out-Null
    Write-Output-Content "  注册表项已删除" "Green"
} catch {}

Write-Output-Content "步骤2: 卸载MSIX包..." "Green"
try {
    $packages = Get-AppxPackage -Name $PackageName -ErrorAction SilentlyContinue

    if ($packages) {
        foreach ($package in $packages) {
            Write-Output-Content "  正在移除包: $($package.PackageFullName)" "Yellow"
            Remove-AppxPackage -Package $package.PackageFullName -ErrorAction Stop
            Write-Output-Content "  已移除包" "Green"
        }
    } else {
        Write-Output-Content "  未找到已安装的包" "Yellow"
    }
} catch {
    Write-Output-Content "  卸载失败: $($_.Exception.Message)" "Red"
    exit 1
}

Write-Output-Content "卸载完成!" "Green"
