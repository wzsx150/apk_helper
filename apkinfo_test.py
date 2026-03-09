#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
使用apk-info库测试APK解析功能
测试核心功能：基本信息、权限信息、签名信息、图标路径、签名方案检测
"""

import os
import sys
import time
import zipfile
import struct
import re

# 打印当前Python版本和路径
print(f"Python版本: {sys.version}")
print(f"Python路径: {sys.executable}")
print(f"当前目录: {os.getcwd()}")

# 记录开始时间
start_time = time.time()

try:
    import apk_info
    try:
        version = apk_info.__version__
        print(f"\n=== apk-info库导入成功，版本: {version} ===")
    except AttributeError:
        print("\n=== apk-info库导入成功 ===")
except ImportError as e:
    print(f"\n=== 错误: apk-info库未安装 ===")
    print(f"错误信息: {e}")
    print("请运行: pip install apk-info")
    sys.exit(1)

# 检查命令行参数
if len(sys.argv) < 2:
    print("用法: python apkinfo_test.py <apk文件路径> [--no-files]")
    print("示例: python apkinfo_test.py example.apk")
    print("      python apkinfo_test.py example.apk --no-files  (跳过文件列表)")
    sys.exit(1)

apk_path = sys.argv[1]
skip_files = '--no-files' in sys.argv

if not os.path.exists(apk_path):
    print(f"错误: APK文件不存在 - {apk_path}")
    sys.exit(1)

print(f"\n=== 开始解析APK: {apk_path} ===")
print(f"文件大小: {os.path.getsize(apk_path) / 1024 / 1024:.2f} MB")
if skip_files:
    print("注意: 已跳过文件列表获取")


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


def get_all_icons(apk_path, apk):
    """
    获取APK中所有分辨率的图标文件路径
    
    方法：
    1. 从AndroidManifest.xml获取图标资源引用
    2. 使用apk-info的get_resource_value获取默认资源路径
    3. 直接解析resources.arsc获取资源ID对应的所有配置文件路径
    """
    import re
    import os
    
    icons = []
    
    # 1. 获取图标资源引用
    icon_refs = apk.get_all_attribute_values('application', 'icon')
    
    if not icon_refs:
        return icons
    
    # 2. 解析resources.arsc获取所有配置
    try:
        with zipfile.ZipFile(apk_path, 'r') as zf:
            if 'resources.arsc' not in zf.namelist():
                # 没有resources.arsc，使用简单方法
                return get_icons_simple(apk_path, apk, icon_refs)
            
            arsc_data = zf.read('resources.arsc')
            
            # 解析resources.arsc
            arsc_parser = ARSCParser(arsc_data)
            
            # 获取manifest中的资源ID
            manifest = apk.get_android_manifest_xml()
            icon_id_matches = re.findall(r'android:icon="@([0-9a-fA-F]+)"', manifest)
            
            for icon_id_str in icon_id_matches:
                icon_id = int(icon_id_str, 16)
                
                # 获取所有配置的资源文件
                results = arsc_parser.get_resource_value(icon_id)
                
                for r in results:
                    # 检查文件是否存在
                    if r['path'] in zf.namelist():
                        data = zf.read(r['path'])
                        icons.append({
                            'path': r['path'],
                            'config': r['density'],
                            'size': len(data),
                            'type': 'standard'
                        })
    
    except Exception as e:
        # 解析失败，使用简单方法
        return get_icons_simple(apk_path, apk, icon_refs)
    
    return icons


class ARSCParser:
    """解析resources.arsc文件"""
    
    RES_TABLE_TYPE = 0x0002
    RES_STRING_POOL_TYPE = 0x0001
    RES_TABLE_PACKAGE_TYPE = 0x0200
    RES_TABLE_TYPE_TYPE = 0x0201
    TYPE_STRING = 0x03
    
    def __init__(self, arsc_data):
        self.arsc_data = arsc_data
        self.global_strings = []
        self.packages = {}
        self._parse()
    
    def _parse(self):
        """解析resources.arsc"""
        pos = 0
        
        # 文件头
        chunk_type = struct.unpack('<H', self.arsc_data[pos:pos+2])[0]
        if chunk_type != self.RES_TABLE_TYPE:
            raise ValueError("不是有效的resources.arsc文件")
        
        header_size = struct.unpack('<H', self.arsc_data[pos+2:pos+4])[0]
        pos = header_size
        
        while pos < len(self.arsc_data):
            if pos + 8 > len(self.arsc_data):
                break
            
            chunk_type = struct.unpack('<H', self.arsc_data[pos:pos+2])[0]
            chunk_size = struct.unpack('<I', self.arsc_data[pos+4:pos+8])[0]
            
            if chunk_type == self.RES_STRING_POOL_TYPE:
                self.global_strings = self._parse_string_pool(self.arsc_data[pos:pos+chunk_size])
                
            elif chunk_type == self.RES_TABLE_PACKAGE_TYPE:
                pkg_info = self._parse_package(self.arsc_data[pos:pos+chunk_size])
                self.packages[pkg_info['id']] = pkg_info
            
            pos += chunk_size
    
    def _parse_string_pool(self, data):
        """解析字符串池"""
        strings = []
        
        if len(data) < 28:
            return strings
        
        string_count = struct.unpack('<I', data[8:12])[0]
        flags = struct.unpack('<I', data[16:20])[0]
        strings_start = struct.unpack('<I', data[20:24])[0]
        
        offsets_start = 28
        is_utf8 = (flags & 0x100) != 0
        
        for i in range(string_count):
            offset_pos = offsets_start + i * 4
            if offset_pos + 4 > len(data):
                break
            
            offset = struct.unpack('<I', data[offset_pos:offset_pos+4])[0]
            string_start = strings_start + offset
            
            if string_start >= len(data):
                strings.append('')
                continue
            
            if is_utf8:
                if string_start >= len(data):
                    strings.append('')
                    continue
                
                char_count = data[string_start]
                if char_count & 0x80:
                    if string_start + 1 >= len(data):
                        strings.append('')
                        continue
                    char_count = ((char_count & 0x7F) << 8) | data[string_start + 1]
                    string_start += 1
                
                if string_start + 1 >= len(data):
                    strings.append('')
                    continue
                
                byte_count = data[string_start + 1]
                if byte_count & 0x80:
                    if string_start + 2 >= len(data):
                        strings.append('')
                        continue
                    byte_count = ((byte_count & 0x7F) << 8) | data[string_start + 2]
                    string_start += 1
                
                string_start += 2
                string_end = string_start + byte_count
                if string_end > len(data):
                    string_end = len(data)
                try:
                    s = data[string_start:string_end].decode('utf-8')
                except:
                    s = ''
            else:
                if string_start + 2 > len(data):
                    strings.append('')
                    continue
                
                char_count = struct.unpack('<H', data[string_start:string_start+2])[0]
                string_start += 2
                string_end = string_start + char_count * 2
                if string_end > len(data):
                    string_end = len(data)
                try:
                    s = data[string_start:string_end].decode('utf-16-le')
                except:
                    s = ''
            
            strings.append(s)
        
        return strings
    
    def _parse_package(self, data):
        """解析包信息"""
        package_id = struct.unpack('<I', data[8:12])[0]
        
        header_size = struct.unpack('<H', data[2:4])[0]
        pos = header_size
        
        types = {}
        
        while pos < len(data):
            if pos + 8 > len(data):
                break
            
            chunk_type = struct.unpack('<H', data[pos:pos+2])[0]
            chunk_size = struct.unpack('<I', data[pos+4:pos+8])[0]
            
            if chunk_type == self.RES_TABLE_TYPE_TYPE:
                type_info = self._parse_type(data[pos:pos+chunk_size])
                type_id = type_info['type_id']
                if type_id not in types:
                    types[type_id] = []
                types[type_id].append(type_info)
            
            pos += chunk_size
        
        return {
            'id': package_id,
            'types': types
        }
    
    def _parse_type(self, data):
        """解析类型信息"""
        type_id = data[8]
        entry_count = struct.unpack('<I', data[12:16])[0]
        entries_start = struct.unpack('<I', data[16:20])[0]
        config_size = struct.unpack('<I', data[20:24])[0]
        
        # 解析配置信息
        config_start = 20
        config = self._parse_config(data, config_start, config_size)
        
        # 解析entries
        offsets_start = config_start + config_size
        entries = {}
        
        for entry_id in range(entry_count):
            entry_offset_pos = offsets_start + entry_id * 4
            if entry_offset_pos + 4 > len(data):
                break
            
            entry_offset = struct.unpack('<I', data[entry_offset_pos:entry_offset_pos+4])[0]
            
            if entry_offset == 0xFFFFFFFF:  # NO_ENTRY
                continue
            
            entry_pos = entries_start + entry_offset
            
            if entry_pos + 8 > len(data):
                continue
            
            entry_size = struct.unpack('<H', data[entry_pos:entry_pos+2])[0]
            entry_flags = struct.unpack('<H', data[entry_pos+2:entry_pos+4])[0]
            key_index = struct.unpack('<I', data[entry_pos+4:entry_pos+8])[0]
            
            # 解析Res_value
            value_pos = entry_pos + 8
            value_type = 0
            value_data = 0
            
            if value_pos + 8 <= len(data):
                value_type = data[value_pos + 3]  # dataType在偏移3
                value_data = struct.unpack('<I', data[value_pos+4:value_pos+8])[0]
            
            entries[entry_id] = {
                'value_type': value_type,
                'value_data': value_data
            }
        
        return {
            'type_id': type_id,
            'config': config,
            'entries': entries
        }
    
    def _parse_config(self, data, offset, size):
        """
        解析ResTable_config结构
        
        struct ResTable_config {
            uint32_t size;           // 4 bytes
            union {
                struct {
                    uint16_t mcc;    // 2 bytes
                    uint16_t mnc;    // 2 bytes
                };
                uint32_t imsi;
            };
            union {
                struct {
                    uint8_t language[2];  // 2 bytes
                    uint8_t country[2];   // 2 bytes
                };
                uint32_t locale;
            };
            union {
                struct {
                    uint8_t orientation;  // 1 byte
                    uint8_t touchscreen;  // 1 byte
                    uint16_t density;     // 2 bytes
                };
                uint32_t screenType;
            };
            // ... 更多字段
        };
        """
        config = {}
        
        if offset + 4 > len(data):
            return config
        
        if size >= 8:
            # imsi: mcc, mnc
            mcc = struct.unpack('<H', data[offset+4:offset+6])[0]
            mnc = struct.unpack('<H', data[offset+6:offset+8])[0]
            if mcc != 0:
                config['mcc'] = mcc
            if mnc != 0:
                config['mnc'] = mnc
        
        if size >= 12:
            # locale: language[2], country[2]
            lang_bytes = data[offset+8:offset+10]
            country_bytes = data[offset+10:offset+12]
            
            # language是两个ASCII字符
            lang = ''
            if lang_bytes[0] != 0:
                lang = lang_bytes[0:1].decode('ascii', errors='ignore')
                if lang_bytes[1] != 0:
                    lang += lang_bytes[1:2].decode('ascii', errors='ignore')
            
            # country是两个ASCII字符
            country = ''
            if country_bytes[0] != 0:
                country = country_bytes[0:1].decode('ascii', errors='ignore')
                if country_bytes[1] != 0:
                    country += country_bytes[1:2].decode('ascii', errors='ignore')
            
            if lang:
                config['language'] = lang
            if country:
                config['country'] = country
            if lang or country:
                config['locale'] = lang + ('-' + country if country else '')
        
        if size >= 16:
            # screenType: orientation, touchscreen, density
            screen_type = struct.unpack('<I', data[offset+12:offset+16])[0]
            orientation = screen_type & 0xFF
            touchscreen = (screen_type >> 8) & 0xFF
            density = (screen_type >> 16) & 0xFFFF
            
            if orientation != 0:
                orientation_map = {0: 'any', 1: 'port', 2: 'land', 3: 'square'}
                config['orientation'] = orientation_map.get(orientation, f'ori{orientation}')
            
            if density != 0:
                density_map = {
                    0: 'default', 120: 'ldpi', 160: 'mdpi', 240: 'hdpi',
                    320: 'xhdpi', 480: 'xxhdpi', 640: 'xxxhdpi',
                    65534: 'anydpi', 65535: 'nodpi'
                }
                config['density'] = density_map.get(density, f'dpi{density}')
                config['density_value'] = density
        
        return config
    
    def get_resource_value(self, res_id):
        """获取资源ID对应的所有配置文件路径"""
        package_id = (res_id >> 24) & 0xFF
        type_id = (res_id >> 16) & 0xFF
        entry_id = res_id & 0xFFFF
        
        if package_id not in self.packages:
            return []
        
        pkg = self.packages[package_id]
        
        if type_id not in pkg['types']:
            return []
        
        results = []
        for type_info in pkg['types'][type_id]:
            if entry_id not in type_info['entries']:
                continue
            
            entry = type_info['entries'][entry_id]
            config = type_info['config']
            
            # 获取density
            density_name = config.get('density', 'default')
            
            # 获取locale
            locale = config.get('locale', '')
            
            if entry['value_type'] == self.TYPE_STRING:
                if entry['value_data'] < len(self.global_strings):
                    file_path = self.global_strings[entry['value_data']]
                    results.append({
                        'path': file_path,
                        'density': density_name,
                        'locale': locale
                    })
        
        return results


def get_icons_simple(apk_path, apk, icon_refs):
    """简单方法获取图标"""
    import os
    import re
    
    icons = []
    
    with zipfile.ZipFile(apk_path, 'r') as zf:
        files = zf.namelist()
        
        for icon_ref in icon_refs:
            if not icon_ref.startswith('@'):
                continue
            
            default_path = apk.get_resource_value(icon_ref)
            if not default_path:
                continue
            
            # 检查资源路径格式
            if default_path.startswith('res/'):
                res_name = os.path.basename(default_path)
                if '.' in res_name:
                    res_name = res_name.rsplit('.', 1)[0]
                
                res_type_match = re.search(r'res/([^-/]+)', default_path)
                res_type = res_type_match.group(1) if res_type_match else 'mipmap'
                
                pattern = rf'res/{res_type}-[^/]+/{res_name}\.[^.]+$'
                matching_files = [f for f in files if re.match(pattern, f)]
                
                for icon_path in sorted(matching_files):
                    try:
                        data = zf.read(icon_path)
                        config_match = re.search(rf'{res_type}-([^-/]+)', icon_path)
                        config = config_match.group(1) if config_match else 'default'
                        
                        icons.append({
                            'path': icon_path,
                            'config': config,
                            'size': len(data),
                            'type': 'standard'
                        })
                    except:
                        pass
            
            elif default_path in files:
                try:
                    data = zf.read(default_path)
                    icons.append({
                        'path': default_path,
                        'config': 'default',
                        'size': len(data),
                        'type': 'standard'
                    })
                except:
                    pass
    
    return icons


def main():
    global apk_path, skip_files, start_time
    
    start_time = time.time()
    
    try:
        parse_start = time.time()
        
        # 使用apk-info解析APK
        apk = apk_info.APK(apk_path)
        
        parse_end = time.time()
        print(f"解析耗时: {parse_end - parse_start:.2f}秒")
        
        # 1. 基本信息
        print("\n=== 基本信息 ===")
        try:
            package_name = apk.get_package_name()
            print(f"包名: {package_name}")
        except Exception as e:
            print(f"获取包名失败: {e}")
        
        try:
            version_name = apk.get_version_name()
            print(f"版本名称: {version_name}")
        except Exception as e:
            print(f"获取版本名称失败: {e}")
        
        try:
            version_code = apk.get_version_code()
            print(f"版本号: {version_code}")
        except Exception as e:
            print(f"获取版本号失败: {e}")
        
        try:
            app_label = apk.get_application_label()
            if app_label:
                print(f"应用名称: {app_label}")
        except Exception as e:
            print(f"获取应用名称失败: {e}")
        
        # 2. 权限信息
        print("\n=== 权限信息 ===")
        try:
            permissions = apk.get_permissions()
            print(f"权限数量: {len(permissions)}")
            perm_list = list(permissions)
            for perm in perm_list[:10]:
                print(f"- {perm}")
            if len(perm_list) > 10:
                print(f"... 还有 {len(perm_list) - 10} 个权限")
        except Exception as e:
            print(f"获取权限信息失败: {e}")
        
        # 3. 签名信息
        print("\n=== 签名信息 ===")
        try:
            signatures = apk.get_signatures()
            
            sig_schemes = {'V1': False, 'V2': False, 'V3': False, 'V3.1': False, 'V4': False}
            for sig in signatures:
                sig_type = type(sig).__name__
                if sig_type == 'V1':
                    sig_schemes['V1'] = True
                elif sig_type == 'V2':
                    sig_schemes['V2'] = True
                elif sig_type == 'V3':
                    sig_schemes['V3'] = True
            
            print("签名方案检测:")
            for scheme, signed in sig_schemes.items():
                if signed:
                    print(f"{scheme}签名: 已签名")
            
            print(f"\n证书信息:")
            cert_info = None
            for sig in signatures:
                if hasattr(sig, 'certificates') and sig.certificates:
                    cert_info = sig.certificates[0]
                    break
            
            if cert_info:
                print(f"  序列号: {cert_info.serial_number}")
                print(f"  主题: {cert_info.subject}")
                print(f"  颁发者: {cert_info.issuer}")
                print(f"  有效期开始: {cert_info.valid_from}")
                print(f"  有效期结束: {cert_info.valid_until}")
                print(f"  签名算法: {cert_info.signature_type}")
                print(f"  MD5指纹: {cert_info.md5_fingerprint}")
                print(f"  SHA1指纹: {cert_info.sha1_fingerprint}")
                print(f"  SHA256指纹: {cert_info.sha256_fingerprint}")
            else:
                print("  未找到证书信息")
                
        except Exception as e:
            print(f"获取签名信息失败: {e}")
            import traceback
            traceback.print_exc()
        
        # 4. 图标路径（所有分辨率）
        print("\n=== 图标路径（所有分辨率） ===")
        try:
            icons = get_all_icons(apk_path, apk)
            if icons:
                print(f"图标数量: {len(icons)}")
                for icon in icons:
                    print(f"- [{icon['config']}] {icon['path']} ({icon['size']} bytes)")
            else:
                print("未找到图标")
        except Exception as e:
            print(f"获取图标路径失败: {e}")
        
        # 5. 其他信息
        print("\n=== 其他信息 ===")
        try:
            main_activity = apk.get_main_activity()
            print(f"主活动: {main_activity}")
        except Exception as e:
            print(f"获取主活动失败: {e}")
        
        try:
            activities = apk.get_activities()
            print(f"活动数量: {len(activities)}")
        except Exception as e:
            print(f"获取活动数量失败: {e}")
        
        try:
            services = apk.get_services()
            print(f"服务数量: {len(services)}")
        except Exception as e:
            print(f"获取服务数量失败: {e}")
        
        try:
            receivers = apk.get_receivers()
            print(f"广播接收器数量: {len(receivers)}")
        except Exception as e:
            print(f"获取广播接收器数量失败: {e}")
        
        try:
            providers = apk.get_providers()
            print(f"内容提供者数量: {len(providers)}")
        except Exception as e:
            print(f"获取内容提供者数量失败: {e}")
        
        try:
            min_sdk = apk.get_min_sdk_version()
            target_sdk = apk.get_target_sdk_version()
            max_sdk = apk.get_max_sdk_version()
            print(f"最小SDK版本: {min_sdk}")
            print(f"目标SDK版本: {target_sdk}")
            if max_sdk:
                print(f"最大SDK版本: {max_sdk}")
        except Exception as e:
            print(f"获取SDK版本失败: {e}")
        
        # 6. 文件列表（可选）
        if not skip_files:
            print("\n=== APK文件列表（前20个） ===")
            try:
                files = apk.namelist()
                print(f"文件总数: {len(files)}")
                for file_name in files[:20]:
                    print(f"- {file_name}")
                if len(files) > 20:
                    print(f"... 还有 {len(files) - 20} 个文件")
            except Exception as e:
                print(f"获取文件列表失败: {e}")
        
    except Exception as e:
        print(f"解析APK失败: {e}")
        import traceback
        traceback.print_exc()
    
    end_time = time.time()
    
    print(f"\n=== 性能统计 ===")
    print(f"总耗时: {end_time - start_time:.2f}秒")
    print("\n=== 测试完成 ===")


if __name__ == '__main__':
    main()
