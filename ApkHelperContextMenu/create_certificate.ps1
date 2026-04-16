<#
.SYNOPSIS
    创建用于签名MSIX包的自签名证书

.DESCRIPTION
    此脚本创建一个自签名证书，用于对Sparse Package进行签名。
    证书将导出为PFX文件，同时安装到当前用户的受信任根证书存储区。

.NOTES
    不需要管理员权限，普通用户权限即可运行
    添加证书到受信任的根证书颁发机构时会弹出Windows安全警告对话框，需要用户确认
#>

param(
    [string]$PublisherName = "CN=ApkHelperPublisher",        # 发布者名称（证书主题）
    [string]$FriendlyName = "ApkHelperContextMenu Certificate",  # 证书友好名称
    [string]$OutputPath = "release",                          # 输出目录，相对于脚本目录
    [string]$PfxFileName = "ApkHelperContextMenu.pfx",        # PFX文件名
    [string]$PfxPassword = "apkhelper123",                    # PFX证书密码
    # 证书有效期设置
    [int]$NotBeforeYear = 2020,    # 有效期起始年份
    [int]$NotAfterYear = 2050      # 有效期结束年份
)

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "创建自签名证书" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$fullOutputPath = Join-Path $scriptDir $OutputPath
$pfxPath = Join-Path $fullOutputPath $PfxFileName

Write-Host "发布者名称: $PublisherName" -ForegroundColor Yellow
Write-Host "证书友好名称: $FriendlyName" -ForegroundColor Yellow
Write-Host "输出路径: $pfxPath" -ForegroundColor Yellow

if (-not (Test-Path $fullOutputPath)) {
    New-Item -ItemType Directory -Path $fullOutputPath -Force | Out-Null
}

$existingCert = Get-ChildItem -Path "Cert:\CurrentUser\My" | Where-Object { $_.Subject -eq $PublisherName }
if ($existingCert) {
    Write-Host "发现已存在的证书，正在删除..." -ForegroundColor Yellow
    Remove-Item -Path "Cert:\CurrentUser\My\$($existingCert.Thumbprint)" -Force
}

Write-Host "正在创建新证书..." -ForegroundColor Green

# 设置证书有效期：从指定起始年份到结束年份
$notBefore = Get-Date -Year $NotBeforeYear -Month 1 -Day 1
$notAfter = Get-Date -Year $NotAfterYear -Month 1 -Day 1

$cert = New-SelfSignedCertificate `
    -Type Custom `
    -Subject $PublisherName `
    -KeyUsage DigitalSignature `
    -FriendlyName $FriendlyName `
    -NotBefore $notBefore `
    -NotAfter $notAfter `
    -CertStoreLocation "Cert:\CurrentUser\My" `
    -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3", "2.5.29.19={text}")

Write-Host "证书创建成功，指纹: $($cert.Thumbprint)" -ForegroundColor Green
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "证书基本信息:" -ForegroundColor Cyan
Write-Host "  主题(Subject):    $($cert.Subject)" -ForegroundColor White
Write-Host "  颁发者(Issuer):   $($cert.Issuer)" -ForegroundColor White
Write-Host "  指纹(Thumbprint): $($cert.Thumbprint)" -ForegroundColor White
Write-Host "  友好名称:         $($cert.FriendlyName)" -ForegroundColor White
Write-Host "  有效期起始:       $($cert.NotBefore.ToString('yyyy-MM-dd HH:mm:ss'))" -ForegroundColor White
Write-Host "  有效期结束:       $($cert.NotAfter.ToString('yyyy-MM-dd HH:mm:ss'))" -ForegroundColor White
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

Write-Host "正在导出PFX文件..." -ForegroundColor Green
$securePassword = ConvertTo-SecureString -String $PfxPassword -Force -AsPlainText
Export-PfxCertificate -Cert "Cert:\CurrentUser\My\$($cert.Thumbprint)" -FilePath $pfxPath -Password $securePassword
Write-Host "PFX文件已导出到: $pfxPath" -ForegroundColor Green

Write-Host "正在将证书添加到受信任的人存储区..." -ForegroundColor Green
$sourceStore = New-Object System.Security.Cryptography.X509Certificates.X509Store("My", "CurrentUser")
try {
    $sourceStore.Open("ReadOnly")
    $sourceCert = $sourceStore.Certificates | Where-Object { $_.Thumbprint -eq $cert.Thumbprint }
    # 将证书添加到 TrustedPeople（与 install.ps1 一致，MSIX侧载只需此存储区）
    $destStore = New-Object System.Security.Cryptography.X509Certificates.X509Store("TrustedPeople", "CurrentUser")
    try {
        $destStore.Open("ReadWrite")
        $destStore.Add($sourceCert)
        Write-Host "证书已添加到受信任的人存储区" -ForegroundColor Green
    } finally {
        if ($null -ne $destStore) {
            $destStore.Close()
        }
    }
} finally {
    if ($null -ne $sourceStore) {
        $sourceStore.Close()
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "证书创建完成!" -ForegroundColor Green
Write-Host "PFX文件: $pfxPath" -ForegroundColor Green
Write-Host "PFX密码: $PfxPassword" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
