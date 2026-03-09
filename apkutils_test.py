#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
使用apkutils库测试APK解析功能（优化版）
测试核心功能：基本信息、权限信息、签名信息、图标路径、签名方案检测
支持命令行参数控制是否获取文件列表
"""

import os
import sys
import time
import re
import zipfile
import struct

# 打印当前Python版本和路径
print(f"Python版本: {sys.version}")
print(f"Python路径: {sys.executable}")
print(f"当前目录: {os.getcwd()}")

# 记录开始时间
start_time = time.time()

try:
    import apkutils
    try:
        version = apkutils.__version__
        print(f"\n=== apkutils库导入成功，版本: {version} ===")
    except AttributeError:
        print("\n=== apkutils库导入成功 ===")
except ImportError as e:
    print(f"\n=== 错误: apkutils库未安装 ===")
    print(f"错误信息: {e}")
    print("请运行: pip install apkutils")
    sys.exit(1)

# 检查命令行参数
if len(sys.argv) < 2:
    print("用法: python apkutils_test.py <apk文件路径> [--no-files] [--no-resource]")
    print("示例: python apkutils_test.py example.apk")
    print("      python apkutils_test.py example.apk --no-files  (跳过文件列表)")
    print("      python apkutils_test.py example.apk --no-resource  (跳过资源解析)")
    sys.exit(1)

apk_path = sys.argv[1]
skip_files = '--no-files' in sys.argv
skip_resource = '--no-resource' in sys.argv

if not os.path.exists(apk_path):
    print(f"错误: APK文件不存在 - {apk_path}")
    sys.exit(1)

print(f"\n=== 开始解析APK: {apk_path} ===")
print(f"文件大小: {os.path.getsize(apk_path) / 1024 / 1024:.2f} MB")
if skip_files:
    print("注意: 已跳过文件列表获取")
if skip_resource:
    print("注意: 已跳过资源解析")


def check_signature_scheme(apk_path):
    """
    检测APK签名方案（V1/V2/V3/V3.1/V4）
    """
    result = {
        'v1': False,
        'v2': False,
        'v3': False,
        'v31': False,
        'v4': False
    }
    
    try:
        with zipfile.ZipFile(apk_path, 'r') as zf:
            meta_inf_files = [f for f in zf.namelist() if f.startswith('META-INF/')]
            has_manifest = any('MANIFEST.MF' in f.upper() for f in meta_inf_files)
            has_sig_file = any(f.endswith('.RSA') or f.endswith('.DSA') or f.endswith('.EC') for f in meta_inf_files)
            result['v1'] = has_manifest and has_sig_file
    except:
        pass
    
    try:
        with open(apk_path, 'rb') as f:
            f.seek(-22, 2)
            end_dir_data = f.read(22)
            
            if end_dir_data[:4] == b'\x50\x4b\x05\x06':
                central_dir_offset = struct.unpack('<I', end_dir_data[16:20])[0]
                
                if central_dir_offset > 32:
                    f.seek(central_dir_offset - 16)
                    magic = f.read(16)
                    
                    if magic == b'APK Sig Block 42':
                        f.seek(central_dir_offset - 16 - 8)
                        block_size = struct.unpack('<Q', f.read(8))[0]
                        f.seek(central_dir_offset - 16 - 8 - block_size)
                        block_data = f.read(block_size)
                        
                        v2_id = struct.pack('<I', 0x7109871a)
                        v3_id = struct.pack('<I', 0xf05368c0)
                        v31_id = struct.pack('<I', 0x1b93ad61)
                        v4_id = struct.pack('<I', 0x8f9d0f6a)
                        
                        result['v2'] = v2_id in block_data
                        result['v3'] = v3_id in block_data
                        result['v31'] = v31_id in block_data
                        result['v4'] = v4_id in block_data
    except:
        pass
    
    return result


try:
    parse_start = time.time()
    apk = apkutils.APK.from_file(apk_path)
    parse_end = time.time()
    print(f"解析耗时: {parse_end - parse_start:.2f}秒")
    
    manifest_str = apk.get_manifest()
    
    # 解析资源（可选）
    arsc = None
    if not skip_resource:
        try:
            apk.parse_resource()
            arsc = apk.get_arsc()
        except Exception as e:
            print(f"解析资源失败: {e}")
    
    # 获取包名
    package_name = None
    package_match = re.search(r'package="([^"]+)"', manifest_str)
    if package_match:
        package_name = package_match.group(1)
    
    # 1. 基本信息
    print("\n=== 基本信息 ===")
    try:
        if package_name:
            print(f"包名: {package_name}")
        
        version_name_match = re.search(r'android:versionName="([^"]+)"', manifest_str)
        if version_name_match:
            print(f"版本名称: {version_name_match.group(1)}")
        
        version_code_match = re.search(r'android:versionCode="([^"]+)"', manifest_str)
        if version_code_match:
            print(f"版本号: {version_code_match.group(1)}")
    except Exception as e:
        print(f"从manifest提取基本信息失败: {e}")
    
    try:
        app_name = apk.app_name
        if app_name:
            print(f"应用名称: {app_name}")
    except Exception as e:
        print(f"获取应用名称失败: {e}")
    
    # 2. 权限信息
    print("\n=== 权限信息 ===")
    try:
        permissions = re.findall(r'<uses-permission android:name="([^"]+)"', manifest_str)
        print(f"权限数量: {len(permissions)}")
        for perm in permissions[:10]:
            print(f"- {perm}")
        if len(permissions) > 10:
            print(f"... 还有 {len(permissions) - 10} 个权限")
    except Exception as e:
        print(f"获取权限信息失败: {e}")
    
    # 3. 签名信息
    print("\n=== 签名信息 ===")
    try:
        certs = apk.get_certs()
        print(f"证书数量: {len(certs)}")
        for i, cert in enumerate(certs):
            print(f"证书 {i+1}:")
            if isinstance(cert, tuple):
                print(f"  证书主题: {cert[0] if len(cert) > 0 else 'N/A'}")
                print(f"  证书哈希(MD5): {cert[1] if len(cert) > 1 else 'N/A'}")
            else:
                print(f"  证书: {cert}")
        
        print("\n签名方案检测:")
        sig_result = check_signature_scheme(apk_path)
        
        print(f"V1签名: {'已签名' if sig_result['v1'] else '未签名'}")
        print(f"V2签名: {'已签名' if sig_result['v2'] else '未签名'}")
        print(f"V3签名: {'已签名' if sig_result['v3'] else '未签名'}")
        if sig_result['v31']:
            print(f"V3.1签名: {'已签名' if sig_result['v31'] else '未签名'}")
        if sig_result['v4']:
            print(f"V4签名: {'已签名' if sig_result['v4'] else '未签名'}")
    except Exception as e:
        print(f"获取签名信息失败: {e}")
    
    # 4. 图标路径
    print("\n=== 图标路径 ===")
    try:
        icons = apk.get_app_icons()
        if icons:
            print(f"图标数量: {len(icons)}")
            if isinstance(icons, list):
                for icon_path in icons:
                    print(f"- {icon_path}")
            elif isinstance(icons, dict):
                for icon_path, icon_data in icons.items():
                    print(f"- {icon_path} (大小: {len(icon_data)} bytes)")
        else:
            print("未找到图标")
    except Exception as e:
        print(f"获取图标路径失败: {e}")
    
    # 5. 其他信息
    print("\n=== 其他信息 ===")
    try:
        main_activities = apk.get_manifest_main_activities()
        print(f"主活动: {main_activities}")
    except Exception as e:
        print(f"获取主活动失败: {e}")
    
    try:
        application = apk.get_manifest_application()
        if application:
            print(f"Application类: {application}")
    except Exception as e:
        print(f"获取Application信息失败: {e}")
    
    try:
        min_sdk = apk.min_sdk_version
        target_sdk = apk.target_sdk_version
        max_sdk = apk.max_sdk_version
        print(f"最小SDK版本: {min_sdk}")
        print(f"目标SDK版本: {target_sdk}")
        print(f"最大SDK版本: {max_sdk}")
    except Exception as e:
        print(f"获取SDK版本失败: {e}")
    
    # 6. 文件列表（可选）
    if not skip_files:
        print("\n=== APK文件列表（前20个） ===")
        try:
            subfiles = apk.get_subfiles()
            print(f"文件总数: {len(subfiles)}")
            
            count = 0
            for file_info in subfiles:
                if count >= 20:
                    break
                if isinstance(file_info, dict):
                    file_name = file_info.get('name', 'N/A')
                    file_size = file_info.get('size', 0)
                    print(f"- {file_name} ({file_size} bytes)")
                    count += 1
                else:
                    print(f"- {file_info}")
                    count += 1
            
            if len(subfiles) > 20:
                print(f"... 还有 {len(subfiles) - 20} 个文件")
        except Exception as e:
            print(f"获取文件列表失败: {e}")
    
    try:
        apk.close()
        print("\nAPK资源已关闭")
    except Exception as e:
        print(f"关闭APK资源失败: {e}")
    
except Exception as e:
    print(f"解析APK失败: {e}")
    import traceback
    traceback.print_exc()

end_time = time.time()

print(f"\n=== 性能统计 ===")
print(f"总耗时: {end_time - start_time:.2f}秒")
print("\n=== 测试完成 ===")
