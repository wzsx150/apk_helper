<#
.SYNOPSIS
    安装 APK Helper Win11新版右键菜单

.DESCRIPTION
    此脚本安装 Sparse Package 并注册 Win11 新版右键菜单扩展。
    按照微软官方建议，证书安装到 LocalMachine\TrustedPeople 存储区（需要管理员权限）。
    如果无管理员权限，则安装到 CurrentUser\TrustedPeople 作为备选方案。

.NOTES
    适用于 Windows 11（build >= 22000）
    推荐以管理员权限运行，以便将证书安装到正确的存储区。
#>

using namespace System.Security.Cryptography.X509Certificates

param(
    # MSIX包文件路径（相对于脚本目录）
    [string]$PackagePath = "ApkHelperContextMenu.msix",
    # 证书文件路径（相对于脚本目录）
    [string]$PfxPath = "ApkHelperContextMenu.pfx",
    # 证书密码
    [string]$PfxPassword = "apkhelper123",
    # apk_helper.exe 的安装路径，未指定则使用脚本目录的上一级目录的上一级目录
    [string]$InstallPath = "",
    # 输出文件路径参数，用于 Python 捕获输出
    [string]$OutputFile = ""
)

$ErrorActionPreference = "Stop"

# 同时输出到控制台和文件的函数
function Write-Output-Content {
    param([string]$Message, [string]$Color = "White")

    Write-Host $Message -ForegroundColor $Color

    if ($OutputFile -ne "") {
        Add-Content -LiteralPath $OutputFile -Value $Message -Encoding UTF8
    }
}

# 初始化输出文件：创建目录并清空文件内容
if ($OutputFile -ne "") {
    $dir = Split-Path -Parent $OutputFile
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    Set-Content -LiteralPath $OutputFile -Value "" -Encoding UTF8 -NoNewline
}

# 输出标题
Write-Output-Content "安装 APK Helper Context Menu" "Cyan"

# 检查 Windows 版本（需要 Windows 11 build >= 22000）
$buildNumber = [System.Environment]::OSVersion.Version.Build
Write-Output-Content "当前系统版本: build $buildNumber" "Yellow"
if ($buildNumber -lt 22000) {
    Write-Output-Content "错误: 此脚本仅适用于 Windows 11 (build >= 22000)" "Red"
    exit 1
}

# 获取脚本目录，拼接文件完整路径
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pfxFullPath = Join-Path $scriptDir $PfxPath
$msixFullPath = Join-Path $scriptDir $PackagePath

# 确定 apk_helper.exe 的安装路径
if ($InstallPath -eq "") {
    # 未指定时，使用脚本目录的上两级目录
    $parentDir = (Get-Item $scriptDir).Parent
    if ($null -eq $parentDir) {
        Write-Output-Content "错误: 无法解析脚本目录的上级目录: $scriptDir" "Red"
        exit 1
    }
    $grandParentDir = $parentDir.Parent
    if ($null -eq $grandParentDir) {
        Write-Output-Content "错误: 无法解析脚本目录的上两级目录: $scriptDir" "Red"
        exit 1
    }
    $InstallPath = $grandParentDir.FullName
}

# 检查证书文件是否存在
if (-not (Test-Path $pfxFullPath)) {
    Write-Output-Content "错误: 找不到证书文件: $pfxFullPath" "Red"
    exit 1
}

# 检查MSIX包文件是否存在
if (-not (Test-Path $msixFullPath)) {
    Write-Output-Content "错误: 找不到MSIX包: $msixFullPath" "Red"
    exit 1
}

# 步骤1: 卸载已存在的包（仅当前用户）
Write-Output-Content "步骤1: 检查并卸载已存在的包..." "Green"
try {
    $existingPackage = Get-AppxPackage -Name "ApkHelperContextMenu" -ErrorAction SilentlyContinue
    if ($existingPackage) {
        Write-Output-Content "  发现已安装的包，正在卸载..." "Yellow"
        Remove-AppxPackage -Package $existingPackage.PackageFullName -ErrorAction SilentlyContinue
        Write-Output-Content "  已卸载旧版本" "Green"
    } else {
        Write-Output-Content "  未发现已安装的包" "Green"
    }
} catch {
    Write-Output-Content "  检查已存在的包时出错: $($_.Exception.Message)" "Yellow"
}

# 步骤2: 安装证书
# 微软官方推荐：MSIX侧载证书应安装到 LocalMachine\TrustedPeople 存储区
Write-Output-Content "步骤2: 安装证书..." "Green"
try {
    $securePassword = ConvertTo-SecureString -String $PfxPassword -Force -AsPlainText
    $cert = New-Object X509Certificate2($pfxFullPath, $securePassword)

    # 检测是否以管理员权限运行
    $isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

    if ($isAdmin) {
        # 管理员权限：安装到 LocalMachine\TrustedPeople（微软官方推荐）
        Write-Output-Content "  检测到管理员权限" "Green"
        $store = New-Object X509Store("TrustedPeople", [StoreLocation]::LocalMachine)
        try {
            $store.Open([OpenFlags]::ReadWrite)

            # 检查是否已存在相同指纹的证书
            $existingCert = $store.Certificates | Where-Object { $_.Thumbprint -eq $cert.Thumbprint } | Select-Object -First 1
            if ($existingCert) {
                Write-Output-Content "  证书已存在，跳过安装" "Green"
            } else {
                $store.Add($cert)
                Write-Output-Content "  证书已安装到本地计算机的受信任的人" "Green"
            }
        } finally {
            if ($null -ne $store) {
                $store.Close()
            }
        }
    } else {
        # 非管理员权限：安装到 CurrentUser\TrustedPeople（备选方案）
        Write-Output-Content "  提示: 未以管理员权限运行，证书将安装到当前用户存储区" "Yellow"
        Write-Output-Content "  推荐以管理员权限运行，以便所有用户都能使用此右键菜单" "Yellow"
        $store = New-Object X509Store("TrustedPeople", [StoreLocation]::CurrentUser)
        try {
            $store.Open([OpenFlags]::ReadWrite)

            # 检查是否已存在相同指纹的证书
            $existingCert = $store.Certificates | Where-Object { $_.Thumbprint -eq $cert.Thumbprint } | Select-Object -First 1
            if ($existingCert) {
                Write-Output-Content "  证书已存在，跳过安装" "Green"
            } else {
                $store.Add($cert)
                Write-Output-Content "  证书已安装到当前用户的受信任的人" "Green"
            }
        } finally {
            if ($null -ne $store) {
                $store.Close()
            }
        }
    }
} catch {
    Write-Output-Content "  证书安装失败: $($_.Exception.Message)" "Red"
    Write-Output-Content "  尝试继续安装..." "Yellow"
}

# 步骤3: 安装MSIX包
Write-Output-Content "步骤3: 安装Sparse Package..." "Green"
try {
    Add-AppxPackage -Path $msixFullPath -ForceUpdateFromAnyVersion -ErrorAction Stop
    Write-Output-Content "  Sparse Package安装成功" "Green"
} catch {
    $errorMsg = $_.Exception.Message
    if ($errorMsg -match "0x800B0109" -or $errorMsg -match "信任") {
        Write-Output-Content "  错误: 证书不受信任" "Red"
    } elseif ($errorMsg -match "0x80073D02") {
        Write-Output-Content "  错误: 包正在使用中，请重启资源管理器后重试" "Red"
    } else {
        Write-Output-Content "  安装失败: $errorMsg" "Red"
    }
    exit 1
}

# 步骤4: 添加注册表项，注册右键菜单
Write-Output-Content "步骤4: 注册右键菜单..." "Green"
$exePath = Join-Path $InstallPath "apk_helper.exe"

# 检查 apk_helper.exe 是否存在
if (-not (Test-Path -LiteralPath $exePath)) {
    Write-Output-Content "  错误: 找不到 apk_helper.exe: $exePath" "Red"
    exit 1
}

try {
    # 设置 exe 路径（供 Sparse Package 的 verb handler 读取）
    & reg add "HKCR\SystemFileAssociations\.apk\APKHelperEx" /ve /t REG_SZ /d "使用 APK Helper 打开" /f 2>$null | Out-Null
    & reg add "HKCR\SystemFileAssociations\.apk\APKHelperEx" /v "ApkHelper.exepath" /t REG_SZ /d "$exePath" /f 2>$null | Out-Null
    Write-Output-Content "  注册表项已写入" "Green"
} catch {}

# 删除传统右键菜单
try {
    & reg delete "HKCR\SystemFileAssociations\.apk\shell\APKHelper" /f 2>$null | Out-Null
    Write-Output-Content "  传统右键菜单注册表项已删除" "Green"
} catch {}

# 安装完成
Write-Output-Content "安装完成!" "Green"
