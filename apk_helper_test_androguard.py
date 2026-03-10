#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import ctypes

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)  # Windows API 定义
def attach_to_parent_console():
    """GUI程序主动附着到父进程（cmd）的控制台，实现输出+阻塞"""
    # 检测标准输出是否已重定向（> 或 >>）
    stdout_handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
    stderr_handle = kernel32.GetStdHandle(-12)  # STD_ERROR_HANDLE
    stdout_redirected = stdout_handle and kernel32.GetFileType(stdout_handle) == 1  # FILE_TYPE_DISK
    stderr_redirected = stderr_handle and kernel32.GetFileType(stderr_handle) == 1
    
    # 尝试附着到父进程的控制台
    if kernel32.AttachConsole(-1):  # -1 表示附着到父进程（cmd）
        # 只有未重定向时才重置输出，否则保留重定向
        if not stdout_redirected:
            sys.stdout = open('CONOUT$', 'w', encoding='utf-8', buffering=1)
        if not stderr_redirected:
            sys.stderr = open('CONOUT$', 'w', encoding='utf-8', buffering=1)
        return True
    return False
# 尝试附着到父控制台（cmd运行时生效，双击时无效果），用于解决disable打包模式下命令行无法输出的问题。
attach_to_parent_console()

import os
import winreg
import platform
import subprocess
import threading
import re
import math
import hashlib
import zipfile
import argparse
import datetime
import logging
import struct
import time
from io import BytesIO
from PIL import Image, ImageDraw, ImageChops
from androguard.core.apk import APK
from androguard.core.axml import AXMLParser,AXMLPrinter,ARSCParser
from androguard.util import get_certificate_name_string, set_log

from typing import Union, Optional, List, Tuple, Dict, Any
import bisect
from asn1crypto import keys, x509
from lxml import etree

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QWIDGETSIZE_MAX, QHeaderView,
    QPushButton, QFileDialog, QTextEdit, QLabel, QGroupBox, QSizePolicy, QMessageBox, QDesktopWidget,
    QTableWidget, QTableWidgetItem, QGridLayout, QSplitter, QDialogButtonBox, QStackedWidget, QDialog, QCheckBox, QLineEdit,
    QComboBox
)
from PyQt5.QtGui import QPixmap, QIcon, QTextOption, QCursor
from PyQt5.QtCore import Qt, QSize, QTimer, QTranslator, QCoreApplication, QThread, pyqtSignal


## APK文件信息解析工具-APK Helper，方便查看 apk 的主要信息。

# 使用 nuitka 打包成32位exe的命令：
# py3.8_32 -m nuitka --standalone --assume-yes-for-downloads --windows-console-mode=disable --output-dir=dist --enable-plugin=pyqt5 --include-package-data=androguard --windows-icon-from-ico=1.ico --include-data-files=1.ico=./ --include-data-files=*.bat=./ --include-raw-dir=translations=translations apk_helper.py
# 控制台模式说明（--windows-console-mode=disable）：打包成GUI程序（无控制台窗口），命令行执行时也不会输出内容，但可以使用 > 和 >> 重定向输出。
# 看似 attach 模式更合适，但是会有其他问题，比如运行cmd命令会报句柄错误。
# 所以最终采用 disable 模式 + 代码输出到控制台的方案。


# ============================================================================
# 全局变量和常量定义
# ============================================================================

b_ver = "4.0"
b_date = "20260301"
b_auth = "wzsx150"
is_arch_64bit = True    # 暂时没用，主要是用于不同位数系统时不同处理方式
BASE_DIR = ""    # 基目录，可能会在临时目录
PRO_DIR = ""     # 程序或者脚本实际所在目录


# 获取操作系统位数信息，根据不同位数的windows系统，进行不同的处理。将来可以扩展。
arch = platform.architecture()
if arch[0] != '64bit':
    is_arch_64bit = False


# 日志级别配置
DEFAULT_LOG_LEVEL = "INFO"
CURRENT_LOG_LEVEL = DEFAULT_LOG_LEVEL
level_map = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}
# 日志缓存配置
LOG_CACHE_MAX_SIZE = 1024 * 1024  # 日志缓存最大大小（字节），默认1024KB
# 创建完全独立的 logger 给程序自己用
app_logger = logging.getLogger("apk_helper")
# 全局内存日志处理器实例
memory_log_handler = None

class MemoryLogHandler(logging.Handler):
    """
    内存日志处理器，用于缓存日志到内存中。
    
    支持限制缓存大小，当日志超过最大大小时，会删除最早的日志记录。
    """
    
    def __init__(self, max_size=LOG_CACHE_MAX_SIZE):
        """
        初始化内存日志处理器。
        
        Args:
            max_size: 日志缓存的最大大小（字节），默认为 LOG_CACHE_MAX_SIZE
        """
        super().__init__()
        self.log_records = []
        self.max_size = max_size
        self.current_size = 0
    
    def emit(self, record):
        """
        处理一条日志记录。
        
        Args:
            record: 日志记录对象
        """
        try:
            msg = self.format(record)
            msg_size = len(msg.encode('utf-8', errors='replace')) + 1
            
            while self.current_size + msg_size > self.max_size and self.log_records:
                removed_msg = self.log_records.pop(0)
                removed_size = len(removed_msg.encode('utf-8', errors='replace')) + 1
                self.current_size -= removed_size
            
            if self.current_size + msg_size <= self.max_size:
                self.log_records.append(msg)
                self.current_size += msg_size
        except Exception:
            self.handleError(record)
    
    def get_logs(self):
        """
        获取所有缓存的日志。
        
        Returns:
            str: 所有日志记录合并后的字符串
        """
        return '\n'.join(self.log_records)
    
    def clear(self):
        """
        清空日志缓存。
        """
        self.log_records.clear()
        self.current_size = 0

class FlexibleFormatter(logging.Formatter):
    """
    灵活的日志格式化器，支持通过 extra 参数控制是否显示 funcName。
    
    使用方式：
        app_logger.info("消息内容")                    # 默认显示 funcName
        app_logger.info("消息内容", extra={"show_func": False})  # 不显示 funcName
    """
    
    def __init__(self, fmt_with_func, fmt_without_func=None, style="{"):
        """
        初始化灵活格式化器。
        
        Args:
            fmt_with_func: 包含 funcName 的日志格式
            fmt_without_func: 不包含 funcName 的日志格式，默认为去掉 [{funcName}] 部分
            style: 格式化风格，默认为 "{"
        """
        super().__init__(fmt_with_func, style=style)
        self.fmt_with_func = fmt_with_func
        if fmt_without_func is None:
            self.fmt_without_func = fmt_with_func.replace(" [{funcName}]", "")
        else:
            self.fmt_without_func = fmt_without_func
        self.style = style
    
    def format(self, record):
        """
        格式化日志记录。
        
        Args:
            record: 日志记录对象
            
        Returns:
            str: 格式化后的日志字符串
        """
        show_func = getattr(record, "show_func", True)
        if show_func:
            self._style = logging.StrFormatStyle(self.fmt_with_func)
        else:
            self._style = logging.StrFormatStyle(self.fmt_without_func)
        return super().format(record)

def setup_logger():
    """
    配置应用程序日志记录器。
    
    初始化 app_logger，设置日志级别、格式化和输出处理器。
    日志输出到标准输出，格式为：级别 | 消息内容
    同时添加内存日志处理器用于缓存日志。
    
    Returns:
        None
    """
    global DEFAULT_LOG_LEVEL, memory_log_handler
    app_logger.setLevel(level_map.get(DEFAULT_LOG_LEVEL, logging.INFO))
    app_logger.handlers.clear()
    
    # 修改日志输出格式，默认输出所在位置的函数名
    formatter = FlexibleFormatter("{levelname: <8} | [{funcName}] {message}")
    
    # 重新包装 stdout，使用 UTF-8 编码并设置 errors='replace'
    # 解决 Windows 控制台 GBK 编码无法显示某些 Unicode 字符的问题
    from io import TextIOWrapper
    utf8_stdout = TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    handler = logging.StreamHandler(utf8_stdout)
    handler.setFormatter(formatter)
    app_logger.addHandler(handler)
    
    # 添加内存日志处理器
    memory_log_handler = MemoryLogHandler(LOG_CACHE_MAX_SIZE)
    memory_log_handler.setFormatter(formatter)
    app_logger.addHandler(memory_log_handler)

def set_log_level(level_name):
    """
    动态设置日志级别。
    
    Args:
        level_name: 日志级别名称，支持 DEBUG、INFO、WARNING、ERROR
        
    Returns:
        None
        
    Note:
        设置后会立即生效，影响后续所有日志输出
    """
    global CURRENT_LOG_LEVEL
    CURRENT_LOG_LEVEL = level_name
    level = level_map.get(level_name, logging.INFO)
    app_logger.setLevel(level)


class APKParser:
    """
    统一的APK解析管理器，避免重复解析相同资源。
    
    该类封装了APK文件的解析操作，提供统一的资源访问接口，
    避免在多次访问时重复解析APK文件，提高解析效率。
    
    Attributes:
        apk_path: APK文件的完整路径
        _custom_apk: CustomAPK实例，用于解析APK内容
        _android_resources: Android资源解析器
        _zip_file: ZipFile实例，用于访问APK内的文件
        _files_list: APK中的文件列表
        
    Example:
        with APKParser('/path/to/app.apk') as parser:
            apk = parser.get_custom_apk()
            package_name = apk.get_package()
    """
    
    def __init__(self, apk_path):
        """
        初始化APK解析器。
        
        Args:
            apk_path: APK文件的完整路径
        """
        self.apk_path = apk_path
        self._custom_apk = CustomAPK(self.apk_path)
        self._android_resources = self._custom_apk.get_android_resources()
        self._zip_file = zipfile.ZipFile(self.apk_path, 'r')
        self._files_list = self.get_zip_file().namelist()
        
    def get_custom_apk(self):
        """
        获取CustomAPK实例。
        
        Returns:
            CustomAPK: 自定义APK解析对象，提供APK信息解析方法
        """
        return self._custom_apk
    
    def get_zip_file(self):
        """
        获取ZipFile实例（懒加载）。
        
        Returns:
            zipfile.ZipFile: 用于访问APK内文件的ZipFile对象
        """
        return self._zip_file
    
    def get_files_list(self):
        """
        获取APK中的文件列表。
        
        Returns:
            list: APK包内所有文件的路径列表
        """
        return self._files_list
    
    def close(self):
        """
        关闭所有打开的资源。
        
        释放ZipFile句柄和APK解析器资源，应在使用完毕后调用。
        
        Returns:
            None
        """
        if self._zip_file is not None:
            self._zip_file.close()
            self._zip_file = None
        # 清理 androguard 相关对象（这些对象占用大量内存）
        self._custom_apk = None
        self._android_resources = None
        self._files_list = None
    
    def __enter__(self):
        """
        支持with语句上下文管理器。
        
        Returns:
            APKParser: 当前实例
        """
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        支持with语句，自动关闭资源。
        
        Args:
            exc_type: 异常类型
            exc_val: 异常值
            exc_tb: 异常追踪信息
            
        Returns:
            None
        """
        self.close()


class CustomAPK(APK):
    """
    自定义APK解析类，继承自androguard的APK类。
    
    该类扩展了原生APK类的功能，提供了更精确的应用图标获取、
    SDK版本解析和本地化应用名称解析等功能。
    
    主要改进：
    - get_app_icon: 优化图标获取逻辑，支持多种图标声明方式
    - get_compile_sdk_version: 获取编译SDK版本
    - get_build_sdk_version: 获取构建SDK版本
    - get_app_name_zh: 获取中文本地化应用名称
    """

    def get_app_icon(self, max_dpi: int = 65536) -> Union[str, None]:
        """
        获取应用图标文件路径，支持多种图标声明方式和密度选择。
        
        图标查找优先级：
        1. activity-alias 中声明的图标（针对主Activity的别名）
        2. 主 Activity 中声明的图标
        3. application 标签中声明的图标
        4. 猜测默认图标资源名（ic_launcher）
        
        密度选择策略：
        - 在不超过max_dpi的前提下，选择最高密度的图标
        - 支持的密度：ldpi(120), mdpi(160), hdpi(240), xhdpi(320), 
          xxhdpi(480), xxxhdpi(640), anydpi(65534), nodpi(65535)
        
        Args:
            max_dpi: 最大DPI限制，默认65536（不限制）
            
        Returns:
            str: 图标文件在APK中的路径，如 "res/mipmap-xxxhdpi/ic_launcher.png"
            None: 未找到图标时返回None
            
        References:
            - https://developer.android.com/guide/practices/screens_support.html
            - https://developer.android.com/ndk/reference/group___configuration.html
        """
        main_activity_name = self.get_main_activity()
        # 1. main_activity 的 activity-alias 最优先
        app_logger.debug(f"main_activities: {self.get_main_activities()}")
        app_icon = None
        for activity_name in self.get_main_activities():
            app_icon = self.get_attribute_value(
                'activity-alias', 'icon', targetActivity=main_activity_name, name=activity_name
            )
            if app_icon:
                app_logger.debug(f"找到 activity-alias 图标 {app_icon}")
                break
        # 2. main_activity 其次
        if not app_icon:
            app_icon = self.get_attribute_value(
                'activity', 'icon', name=main_activity_name
            )
            if app_icon:
                app_logger.debug(f"找到 activity 图标 {app_icon}")
        # 3. application 最次
        if not app_icon:
            app_icon = self.get_attribute_value('application', 'icon')
            if app_icon:
                app_logger.debug(f"找到 application 图标 {app_icon}")

        res_parser = self.get_android_resources()
        if not res_parser:
            # Can not do anything below this point to resolve...
            return None
        # 4. 猜测：默认图标的资源名称是否存在。注：这里其实还可以扩展更多资源名
        if not app_icon:
            res_id = res_parser.get_res_id_by_key(
                self.package, 'mipmap', 'ic_launcher'
            )
            if res_id:
                app_icon = "@%x" % res_id

        if not app_icon:
            res_id = res_parser.get_res_id_by_key(
                self.package, 'drawable', 'ic_launcher'
            )
            if res_id:
                app_icon = "@%x" % res_id
        # 5. 还找不到，就是认为找不到了
        if not app_icon:
            # If the icon can not be found, return now
            return None

        if app_icon.startswith("@"):
            app_icon_id = app_icon[1:]
            app_icon_id = app_icon_id.split(':')[-1]
            res_id = int(app_icon_id, 16)
            candidates = res_parser.get_resolved_res_configs(res_id)

            app_icon = None
            current_dpi = -1

            try:
                for config, file_name in candidates:
                    app_logger.debug(f"@{app_icon_id} 资源对应文件路径：{file_name}")
                    dpi = config.get_density()
                    if current_dpi < dpi <= max_dpi:
                        app_icon = file_name
                        current_dpi = dpi
            except Exception as e:
                app_logger.warning("获取应用图标时出错: %s" % e)

        return app_icon

    def get_compile_sdk_version(self) -> str:
        """
        获取APK的编译SDK版本。
        
        从AndroidManifest.xml的uses-sdk或manifest标签中获取compileSdkVersion属性。
        该版本表示开发时使用的Android SDK版本。
        
        Returns:
            str: 编译SDK版本号字符串，如 "33"
            None: 未设置时返回None
        """
        compile_sdk = self.get_attribute_value("uses-sdk", "compileSdkVersion")
        if not compile_sdk:
            compile_sdk = self.get_attribute_value("manifest", "compileSdkVersion")
        return compile_sdk

    def get_build_sdk_version(self) -> str:
        """
        获取APK的构建SDK版本（platformBuildVersionCode）。
        
        该版本通常与compileSdkVersion相同，但在某些情况下可能不同。
        表示构建APK时使用的平台版本。
        
        Returns:
            str: 构建SDK版本号字符串，如 "33"
            None: 未设置时返回None
        """
        build_sdk = self.get_attribute_value("uses-sdk", "platformBuildVersionCode")
        if not build_sdk:
            build_sdk = self.get_attribute_value("manifest", "platformBuildVersionCode")
        return build_sdk

    def get_app_name_zh(self) -> Union[str, None]:
        """
        获取应用的中文本地化名称。
        
        按照以下优先级获取应用名称：
        1. zh-CN（简体中文）
        2. zh（中文通用）
        3. zh-HK（繁体中文-香港）
        4. zh-TW（繁体中文-台湾）
        
        如果找不到中文名称，返回None。
        
        Returns:
            str: 中文本地化应用名称
            None: 未找到中文名称时返回None
            
        Note:
            如果应用名称引用了android包的资源（如@android:string/...），
            需要framework-res.apk才能解析，此时返回None。
        """
        app_name = self.get_attribute_value('application', 'label')
        if app_name is None:
            activities = self.get_main_activities()
            main_activity_name = None
            if len(activities) > 0:
                main_activity_name = activities.pop()
            app_name = self.get_attribute_value('activity', 'label', name=main_activity_name)

        if app_name is None:
            app_logger.warning("main activity 好像没有设置应用名称！")
            return None

        if app_name.startswith("@"):
            res_parser = self.get_android_resources()
            if not res_parser:
                return None

            res_id, package = res_parser.parse_id(app_name)

            if package and package != self.get_package():
                if package == 'android':
                    app_logger.warning("遇到 android 包名的资源 ID！无法解析，依赖 framework-res.apk。")
                    return None
                else:
                    app_logger.warning("遇到包名为 '{}' 的资源 ID！无法解析".format(package))
                    return None

            try:
                candidates = res_parser.get_resolved_res_configs(res_id)
                
                app_logger.debug(f"找到 {len(candidates)} 个候选资源")
                
                zh_cn_name = None
                zh_name = None
                zh_hk_name = None
                zh_tw_name = None
                
                for idx, (config, name) in enumerate(candidates):
                    try:
                        locale = config.get_language_and_region()
                        app_logger.debug(f"候选 {idx}: locale={locale}, 名称={name}")
                    except Exception as e:
                        locale = ""
                        app_logger.debug(f"候选 {idx}: 获取locale失败, 名称={name}, 错误={e}")

                    if not locale or (not 'zh' in locale):
                        continue

                    if locale == 'zh-rCN' or locale == 'zh-CN':
                        zh_cn_name = name
                        break
                    elif locale == 'zh':
                        zh_name = name
                    elif locale == 'zh-rHK' or locale == 'zh-HK':
                        zh_hk_name = name
                    elif locale == 'zh-rTW' or locale == 'zh-TW':
                        zh_tw_name = name
                    app_logger.debug(f"找到 {locale} 应用名: {name}")

                if zh_cn_name:
                    app_logger.debug(f"使用 zh-CN 应用名: {zh_cn_name}")
                    return zh_cn_name
                elif zh_name:
                    app_logger.debug(f"使用 zh 应用名: {zh_name}")
                    return zh_name
                elif zh_hk_name:
                    app_logger.debug(f"使用 zh-HK 应用名: {zh_hk_name}")
                    return zh_hk_name
                elif zh_tw_name:
                    app_logger.debug(f"使用 zh-TW 应用名: {zh_tw_name}")
                    return zh_tw_name
                    
            except Exception as e:
                app_logger.warning("获取本地化应用名称时出错: %s" % e)
        
        return None


class XmlIconParser:
    """
    APK自适应图标解析器类。
    
    用于解析APK中的各种XML格式图标（如adaptive-icon、layer-list、
    selector、vector等），并提取或合成为最终的图标图像数据。
    
    支持的图标类型：
    - adaptive-icon: 自适应图标（Android 8.0+），包含前景和背景图层
    - layer-list: 图层列表，多个drawable叠加
    - selector: 状态选择器，根据状态显示不同图标
    - vector: 矢量图Drawable
    - bitmap: 位图引用
    
    Attributes:
        zip_file: ZipFile对象，用于访问APK内的文件
        xml_path: XML图标文件在APK中的路径
        apk_parser: APKParser实例，用于获取已解析的资源
        arsc_parser: Android资源解析器
        _icon_data: 解析后的图标二进制数据
        _icon_sure: 图标是否确定正确
        _xml_nest_level: XML嵌套层级计数
        _color_cache: 颜色资源缓存
        _float_cache: 浮点资源缓存
    """
    
    # ==================== Android官方AdaptiveIconDrawable常量 ====================
    # 参考：AdaptiveIconDrawable.java
    
    # 遮罩路径定义在100x100的坐标系中
    MASK_SIZE = 100.0
    
    # 默认遮罩路径（圆角矩形/Squircle）
    # 来源：Android源码 core/res/res/values/config.xml 中的 config_icon_mask
    # 这是一个圆角矩形，圆角半径约8个单位（8%）
    DEFAULT_ICON_MASK_PATH = "M50,0L92,0C96.42,0 100,4.58 100 8L100,92C100, 96.42 96.42 100 92 100L8 100C4.58, 100 0 96.42 0 92L0 8 C 0 4.42 4.42 0 8 0L50 0Z"
    
    # 图层内边距百分比（每边25%）
    # 参考：AdaptiveIconDrawable.java 第105行
    EXTRA_INSET_PERCENTAGE = 1.0 / 4.0  # 0.25
    
    # 视口缩放比例 = 1 / (1 + 2 * 0.25) = 1 / 1.5 ≈ 0.6667
    # 参考：AdaptiveIconDrawable.java 第106行
    DEFAULT_VIEW_PORT_SCALE = 1.0 / (1.0 + 2.0 * EXTRA_INSET_PERCENTAGE)  # ≈ 0.6667
    
    # 安全区域缩放比例（在可见区域内再缩小）
    # 参考：AdaptiveIconDrawable.java 第94行
    SAFEZONE_SCALE = 66.0 / 72.0  # ≈ 0.9167

    def __init__(self, zip_file, xml_path, apk_parser=None):
        """
        初始化XML图标解析器。
        
        Args:
            zip_file: zipfile.ZipFile对象（只读），用于访问APK内容
            xml_path: APK文件内的XML图标文件路径
            apk_parser: APKParser实例（可选），用于获取已解析的资源
        """
        self.zip_file = zip_file
        self.xml_path = xml_path
        self.apk_parser = apk_parser
        self.arsc_parser = None
        self._icon_data = None
        self._icon_sure = True
        self._xml_nest_level = 0
        # 资源解析缓存
        self._color_cache = {}  # 颜色资源缓存
        self._float_cache = {}  # 浮点资源缓存
        # 缓存文件列表，避免重复调用 namelist()
        if self.apk_parser:
            self._files_list = self.apk_parser.get_files_list()
        else:
            self._files_list = self.zip_file.namelist()
        self._initialize()
    
    def _format_resource_id(self, resource_id):
        """
        格式化资源ID为十六进制字符串格式。
        
        Args:
            resource_id: 资源ID（整数）
            
        Returns:
            str: 格式化的字符串，如 "@7F040015"
        """
        return f"@{resource_id:08X}"
    
    def _format_hex(self, value, length=8):
        """
        格式化十六进制数值，统一使用大写。
        
        Args:
            value: 数值
            length: 输出长度，默认8
            
        Returns:
            str: 格式化的字符串，如 "7F040015"
        """
        return f"{value:0{length}X}"
    
    def find_resource(self, resource_name=None, resource_id=None):
        """
        统一的资源查找函数。
        
        优先按资源ID解析，再按资源名解析，支持资源混淆场景。
        对于图片资源，优先返回高密度版本。
        
        Args:
            resource_name: 完整的资源名称（如 @drawable/ic_launcher）
            resource_id: 资源ID（整数）
            
        Returns:
            str: 文件路径
            None: 未找到资源时返回None
        """
        if not self.zip_file:
            return None
        
        files = self._files_list
        
        # 支持的扩展名
        image_extensions = ['.png', '.webp', '.jpg', '.jpeg', '.gif']
        all_extensions = image_extensions + ['.xml']
        
        # ==================== 第一步：获取最终的 xml_name ====================
        final_xml_name = None
        
        # 优先通过资源ID获取 xml_name
        if resource_id and self.arsc_parser:
            try:
                final_xml_name = self.arsc_parser.get_resource_xml_name(resource_id)
                app_logger.debug(f"resource_id=@{hex(resource_id)}, xml_name={final_xml_name}")
            except Exception as e:
                app_logger.debug(f"通过资源ID获取 xml_name 失败: {e}")
        
        # 如果没有ID或ID解析失败，使用传入的 resource_name
        if not final_xml_name and resource_name:
            final_xml_name = resource_name
        
        # 如果都没有，返回 None
        if not final_xml_name:
            return None
        
        # ==================== 第二步：尝试通过 get_resolved_res_configs 获取实际文件路径 ====================
        if resource_id and self.arsc_parser:
            try:
                app_logger.debug(f"尝试通过 get_resolved_res_configs 获取文件路径，resource_id=@{hex(resource_id)}")
                
                # 收集所有配置和文件
                config_file_list = []
                for config, file_name in self.arsc_parser.get_resolved_res_configs(resource_id):
                    if file_name and file_name in files:
                        # 获取密度值
                        density = 0
                        if hasattr(config, 'get_density'):
                            try:
                                density = config.get_density() or 0
                            except:
                                pass
                        
                        # 判断是否是图片文件
                        ext = os.path.splitext(file_name)[1].lower()
                        is_image = ext in image_extensions
                        
                        config_file_list.append({
                            'file': file_name,
                            'density': density,
                            'is_image': is_image,
                            'config': config
                        })
                        app_logger.debug(f"找到配置: file={file_name}, density={density}, is_image={is_image}")
                
                if config_file_list:
                    # 按优先级排序：图片文件优先，高密度优先
                    # 密度值: xxxhdpi=640, xxhdpi=480, xhdpi=320, hdpi=240, mdpi=160
                    # 密度越高，优先级越高（排序时降序）
                    def get_sort_key(item):
                        # 图片文件优先（0），XML文件次之（1）
                        file_priority = 0 if item['is_image'] else 1
                        # 密度降序（高密度优先）
                        density_priority = -item['density']
                        return (file_priority, density_priority)
                    
                    config_file_list.sort(key=get_sort_key)
                    
                    # 返回最高优先级的文件
                    best_file = config_file_list[0]['file']
                    app_logger.debug(f"选择最高优先级文件: {best_file} (density={config_file_list[0]['density']})")
                    return best_file
                    
            except Exception as e:
                app_logger.error(f"通过 get_resolved_res_configs 获取文件失败: {e}")
        
        # ==================== 第三步：解析 xml_name 并查找文件 ====================
        # 解析 xml_name，提取资源类型和名称
        match = re.match(r'@(?:([^:]+):)?(\w+)/(.+)', final_xml_name)
        if not match:
            return None
        
        _, res_type, res_name = match.groups()
        
        # 确定基础目录
        if res_type == 'mipmap':
            base_dirs = ['res/mipmap', 'res/drawable']
        elif res_type == 'drawable':
            base_dirs = ['res/drawable', 'res/mipmap']
        else:
            base_dirs = [f'res/{res_type}']
        
        app_logger.debug(f"搜索目录: {base_dirs}, 资源名: {res_name}")
        
        # 收集所有匹配的文件
        matched_files = []
        
        # 精确匹配（无限定符）
        for base_dir in base_dirs:
            for ext in all_extensions:
                path = f"{base_dir}/{res_name}{ext}"
                if path in files:
                    matched_files.append(path)
        
        # 带限定符的匹配
        for base_dir in base_dirs:
            for file_path in files:
                if file_path.startswith(base_dir) and f"/{res_name}." in file_path:
                    file_ext = os.path.splitext(file_path)[1].lower()
                    if file_ext in all_extensions and file_path not in matched_files:
                        matched_files.append(file_path)
        
        if not matched_files:
            return None
        
        # 按优先级排序：图片文件优先，高分辨率优先
        # 优先级顺序: xxxhdpi > xxhdpi > xhdpi > hdpi > mdpi > anydpi > 其他
        def get_resolution_priority(file_path):
            density_order = ['xxxhdpi', 'xxhdpi', 'xhdpi', 'hdpi', 'mdpi', 'anydpi', 'ldpi', 'tvdpi', 'nodpi']
            for i, density in enumerate(density_order):
                if f'-{density}' in file_path:
                    return i
            return len(density_order)  # 其他情况优先级最低
        
        def get_file_priority(file_path):
            ext = os.path.splitext(file_path)[1].lower()
            if ext in image_extensions:
                return 0
            else:
                return 1
        
        matched_files.sort(key=lambda x: (get_file_priority(x), get_resolution_priority(x)))
        
        if matched_files:
            app_logger.debug(f"找到资源文件(仅取第一个): {matched_files}")
        
        return matched_files[0] if matched_files else None

    def _initialize(self):
        """
        初始化资源解析器并解析XML文件。
        
        从APKParser获取已解析的Android资源，然后自动解析XML文件。
        """
        # 优先尝试从 APKParser 获取已解析的资源
        if self.apk_parser:
            try:
                custom_apk = self.apk_parser.get_custom_apk()
                if custom_apk:
                    android_resources = custom_apk.get_android_resources()
                    if android_resources:
                        self.arsc_parser = android_resources
                        app_logger.debug("成功从 APKParser 获取已解析的 arsc 资源")
            except Exception as e:
                app_logger.error(f"从 APKParser 获取 arsc 资源失败: {e}")
        
        if not self.arsc_parser:
            app_logger.error(f"无法获取 arsc 资源")
        
        # 自动解析 XML 文件并生成图标数据
        self._parse_xml()

    def _parse_xml(self):
        """
        解析XML文件并生成图标数据。
        
        根据XML根标签类型选择相应的提取方法：
        - adaptive-icon: 自适应图标
        - layer-list: 图层列表
        - selector: 状态选择器
        - vector: 矢量图
        - bitmap: 位图引用
        """
        try:
            # 检查 XML 文件是否存在
            if self.xml_path not in self._files_list:
                app_logger.debug(f"未找到图标文件路径: {self.xml_path}")
                return
            
            # 读取 XML 文件内容
            xml_data = self.zip_file.read(self.xml_path)
            # 将二进制 XML 转换为 lxml Element 对象
            xml_obj = self.parse_binary_xml_to_obj(xml_data)
            
            # 根据 XML 根标签类型，选择相应的提取方法
            if xml_obj.tag.endswith('adaptive-icon'):
                # 自适应图标：前景+背景
                app_logger.debug("解析到 adaptive-icon 图标(XML类型)")
                self._icon_data, self._icon_sure = self._extract_adaptive_icon(xml_data)
            elif xml_obj.tag.endswith('layer-list'):
                # 图层列表：多个 drawable 叠加
                app_logger.debug("解析到 layer-list 图标(XML类型)")
                self._icon_data = self._extract_layer_list_icon(xml_data)
                self._icon_sure = True
            elif xml_obj.tag.endswith('selector'):
                # 状态选择器：根据状态显示不同图标
                app_logger.debug("解析到 selector 图标(XML类型)")
                self._icon_data = self._extract_selector_icon(xml_data)
                self._icon_sure = True
            elif xml_obj.tag.endswith('vector'):
                # 矢量图：Vector Drawable
                app_logger.debug("解析到 vector 图标(XML类型)")
                self._icon_data = self._extract_vector_icon(xml_data)
                self._icon_sure = True
            elif xml_obj.tag.endswith('bitmap'):
                # 位图引用
                app_logger.debug("解析到 bitmap 图标(XML类型)")
                self._icon_data = self._extract_bitmap_icon(xml_obj)
                self._icon_sure = True
            else:
                app_logger.debug(f"未知的 XML 类型: {xml_obj.tag}")
        
        except Exception as e:
            app_logger.error(f"解析 XML 失败: {e}")
            import traceback
            app_logger.error(traceback.format_exc())

    def _extract_adaptive_icon(self, xml_data):
        """
        提取Adaptive Icon并合成完整图标。
        
        解析自适应图标的前景和背景图层，合成为最终的图标图像。
        支持多种资源类型：drawable、mipmap、color、inline_vector等。
        当只解析出前景或背景时，仍然返回图标（此时icon_sure为False）。
        
        Args:
            xml_data: 二进制XML数据
            
        Returns:
            tuple: (图标数据, icon_sure)
                - 图标数据: PNG格式的二进制数据
                - icon_sure: 图标是否确定正确
            tuple: (None, False) 解析失败时返回
        """
        try:
            layers = self.parse_adaptive_icon_xml(xml_data)
            
            app_logger.debug("解析到的图层信息:")
            for layer_name in ['background', 'foreground', 'monochrome']:
                layer_info = layers[layer_name]
                if layer_info.get('xml_name'):
                    app_logger.debug(f"  {layer_name}:")
                    app_logger.debug(f"    XML名称: {layer_info.get('xml_name')}")
                    app_logger.debug(f"    资源 ID: {hex(layer_info['resource_id']) if layer_info.get('resource_id') else None}")
                    app_logger.debug(f"    资源类型: {layer_info.get('resource_type')}")
                    if layer_info.get('inline_vector'):
                        app_logger.debug(f"    内嵌Vector: 是")
            
            fg_info = layers['foreground']
            bg_info = layers['background']
            
            if not fg_info.get('xml_name') and not bg_info.get('xml_name'):
                app_logger.error("缺少 foreground 和 background 图层")
                return None, False
            
            fg_type, fg_data = None, None
            bg_type, bg_data = None, None
            
            # 处理 foreground
            if fg_info.get('xml_name'):
                if fg_info.get('resource_type') == 'inline_vector':
                    fg_type = 'inline_vector'
                    fg_data = fg_info.get('inline_vector')
                    app_logger.debug(f"foreground 是内嵌 vector")
                elif fg_info.get('resource_type') == 'inset_xml':
                    # inset_xml类型：需要渲染inset XML数据
                    fg_type = 'inset_xml'
                    fg_data = fg_info.get('inline_vector')  # inset XML数据存储在inline_vector字段
                    app_logger.debug(f"foreground 是 inset XML")
                else:
                    fg_type, fg_data = self.resolve_resource_to_actual_path(fg_info, self.xml_path)
            
            # 处理 background
            if bg_info.get('xml_name'):
                if bg_info.get('resource_type') == 'inline_vector':
                    bg_type = 'inline_vector'
                    bg_data = bg_info.get('inline_vector')
                    app_logger.debug(f"background 是内嵌 vector")
                elif bg_info.get('resource_type') == 'inset_xml':
                    # inset_xml类型：需要渲染inset XML数据
                    bg_type = 'inset_xml'
                    bg_data = bg_info.get('inline_vector')  # inset XML数据存储在inline_vector字段
                    app_logger.debug(f"background 是 inset XML")
                else:
                    bg_type, bg_data = self.resolve_resource_to_actual_path(bg_info, self.xml_path)
            
            app_logger.debug(f"解析结果:")
            app_logger.debug(f"  Background: type={bg_type}, data={bg_data if bg_type != 'inline_vector' else '<inline_vector_data>'}")
            app_logger.debug(f"  Foreground: type={fg_type}, data={fg_data if fg_type != 'inline_vector' else '<inline_vector_data>'}")
            
            fg_image = None
            bg_image = None
            
            if fg_type and fg_data:
                fg_image = self._load_layer_as_image(fg_type, fg_data)
            
            if bg_type and bg_data:
                bg_image = self._load_layer_as_image(bg_type, bg_data)
            
            icon_sure = True
            
            if fg_image is None and bg_image is None:
                app_logger.debug("无法加载前景和背景图片")
                return None, False
            
            if fg_image is None or bg_image is None:
                icon_sure = False
                app_logger.debug("部分资源解析不成功")
            
            output_size = (432, 432)
            
            if fg_image and bg_image:
                combined_image = self.combine_foreground_background(fg_image, bg_image, output_size=output_size)
            elif fg_image:
                combined_image = self._process_single_layer(fg_image, output_size=output_size)
            else:
                combined_image = self._process_single_layer(bg_image, output_size=output_size)
            
            output = BytesIO()
            combined_image.save(output, format='PNG')
            return output.getvalue(), icon_sure
        
        except Exception as e:
            app_logger.error(f"提取 Adaptive Icon 失败: {e}")
            import traceback
            app_logger.error(traceback.format_exc())
            return None, False

    def _load_layer_as_image(self, layer_type, layer_data, size=(432, 432)):
        """
        将图层数据加载为PIL Image对象。
        
        支持文件类型、颜色类型和内嵌vector类型。
        限制XML文件嵌套层数不超过3层，防止无限递归。
        
        与Android官方AdaptiveIconDrawable保持一致：
        图层大小比视口大50%（每边25%的内边距），所以实际渲染尺寸是 size * 1.5
        
        Args:
            layer_type: 图层类型 ('file'、'color' 或 'inline_vector')
            layer_data: 图层数据（文件路径、颜色值或XML二进制数据）
            size: 输出视口尺寸，默认432x432
            
        Returns:
            PIL.Image: 图像对象（尺寸为 size * 1.5）
            None: 加载失败时返回None
        """
        layer_scale = 1.0 / self.DEFAULT_VIEW_PORT_SCALE
        layer_width = int(size[0] * layer_scale)
        layer_height = int(size[1] * layer_scale)
        layer_size = (layer_width, layer_height)
        
        if layer_type == 'file':
            try:
                file_data = self.zip_file.read(layer_data)
                file_ext = os.path.splitext(layer_data)[1].lower()
                
                if file_ext == '.xml':
                    self._xml_nest_level += 1
                    if self._xml_nest_level > 5:
                        app_logger.error(f"错误: XML文件嵌套层数超过5层，无法继续解析: {layer_data}")
                        self._xml_nest_level -= 1
                        return None
                    
                    try:
                        result = self._render_xml_drawable(file_data, layer_size)
                    finally:
                        self._xml_nest_level -= 1
                    return result
                else:
                    image = Image.open(BytesIO(file_data))
                    if image.mode != 'RGBA':
                        image = image.convert('RGBA')
                    return image.resize(layer_size, Image.LANCZOS)
            except Exception as e:
                app_logger.error(f"加载图片文件失败: {e}")
                return None
        
        elif layer_type == 'color':
            try:
                color = self._parse_color_value(layer_data)
                if color:
                    image = Image.new('RGBA', layer_size, color)
                    return image
            except Exception as e:
                app_logger.error(f"创建颜色图层失败: {e}")
                return None
        
        elif layer_type == 'inline_vector':
            try:
                printer = AXMLPrinter(layer_data)
                xml_obj = printer.get_xml_obj()
                
                vector_elem = None
                if xml_obj.tag.endswith('adaptive-icon'):
                    for layer_tag in ['foreground', 'background', 'monochrome']:
                        layer_elem = xml_obj.find('.//{*}' + layer_tag)
                        if layer_elem is not None:
                            vector_elem = layer_elem.find('.//{*}vector')
                            if vector_elem is not None:
                                break
                elif xml_obj.tag.endswith('vector'):
                    vector_elem = xml_obj
                
                if vector_elem is not None:
                    vector_xml = etree.tostring(vector_elem, encoding='unicode')
                    vector_xml_bytes = vector_xml.encode('utf-8')
                    
                    icon_data = self._extract_vector_icon(vector_xml_bytes, size=layer_size)
                    if icon_data:
                        image = Image.open(BytesIO(icon_data))
                        if image.mode != 'RGBA':
                            image = image.convert('RGBA')
                        return image
            except Exception as e:
                app_logger.error(f"渲染内嵌vector失败: {e}")
                return None
        
        elif layer_type == 'inset_xml':
            try:
                # inset_xml类型的数据是纯文本XML（不是二进制AXML）
                # 直接解析XML并渲染
                inset_xml_str = layer_data.decode('utf-8', errors='ignore') if isinstance(layer_data, bytes) else layer_data
                inset_elem = etree.fromstring(inset_xml_str.encode('utf-8'))
                
                # 使用_render_inset_drawable渲染
                result = self._render_inset_drawable(inset_elem, layer_size)
                return result
            except Exception as e:
                app_logger.error(f"渲染inset XML失败: {e}")
                return None
        
        return None

    def _parse_color_value(self, color_value):
        """
        解析颜色值为RGBA元组。
        
        支持多种颜色格式：
        - #RGB
        - #ARGB
        - #RRGGBB
        - #AARRGGBB
        - 元组格式 (r, g, b) 或 (r, g, b, a)
        - 资源引用 @color/xxx 或 @包名:color/xxx
        - 资源ID @7F040007
        
        Args:
            color_value: 颜色值字符串或元组
            
        Returns:
            tuple: RGBA元组 (r, g, b, a)
            None: 解析失败时返回None
        """
        if color_value is None:
            return None
        
        # 处理元组格式
        if isinstance(color_value, tuple):
            if len(color_value) == 4:
                return color_value
            elif len(color_value) == 3:
                return (*color_value, 255)
            return None
        
        # 处理字符串格式
        if isinstance(color_value, str):
            color_str = color_value.strip()
            
            # 处理资源引用
            if color_str.startswith('@'):
                return self._parse_color_state_list(color_str)
            
            if color_str.startswith('#'):
                color_str = color_str[1:]
            
            try:
                if len(color_str) == 6:
                    # #RRGGBB 格式 -> (R, G, B, 255)
                    r = int(color_str[0:2], 16)
                    g = int(color_str[2:4], 16)
                    b = int(color_str[4:6], 16)
                    return (r, g, b, 255)
                elif len(color_str) == 8:
                    # #AARRGGBB 格式 -> (R, G, B, A)
                    a = int(color_str[0:2], 16)
                    r = int(color_str[2:4], 16)
                    g = int(color_str[4:6], 16)
                    b = int(color_str[6:8], 16)
                    return (r, g, b, a)
                elif len(color_str) == 3:
                    # #RGB 格式 -> (R*17, G*17, B*17, 255)
                    r = int(color_str[0], 16) * 17
                    g = int(color_str[1], 16) * 17
                    b = int(color_str[2], 16) * 17
                    return (r, g, b, 255)
                elif len(color_str) == 4:
                    # #ARGB 格式 -> (R*17, G*17, B*17, A*17)
                    a = int(color_str[0], 16) * 17
                    r = int(color_str[1], 16) * 17
                    g = int(color_str[2], 16) * 17
                    b = int(color_str[3], 16) * 17
                    return (r, g, b, a)
            except ValueError:
                app_logger.error(f"解析颜色值失败: {color_value}")
        
        app_logger.error(f"不支持的颜色值格式: {color_value}, 类型: {type(color_value)}")
        return None

    def _parse_color_state_list(self, color_value):
        """
        解析ColorStateList，返回默认颜色。
        
        与Android官方ColorStateList实现保持一致。
        支持格式：
        - 普通颜色值：直接返回
        - 资源引用 @color/xxx：尝试解析颜色资源
        - 状态颜色列表：返回默认状态的颜色
        
        Args:
            color_value: 颜色值字符串
            
        Returns:
            tuple: RGBA元组 (r, g, b, a)
            None: 解析失败时返回None
        """
        if color_value is None:
            return None
        
        if isinstance(color_value, tuple):
            return color_value
        
        if not isinstance(color_value, str):
            return None
        
        color_str = color_value.strip()
        
        # 如果是资源引用
        if color_str.startswith('@'):
            # 尝试解析资源ID
            res_id = self.parse_resource_id(color_str)
            if res_id:
                # 尝试获取颜色资源值
                color_res_value = self.get_color_resource_value(res_id)
                if color_res_value:
                    # 递归解析
                    return self._parse_color_value(color_res_value)
            
            # 尝试从资源名称解析
            if ':' in color_str[1:]:
                # @包名:类型/名称 格式
                parts = color_str[1:].split(':')
                if len(parts) == 2:
                    type_name = parts[1].split('/')
                    if len(type_name) == 2:
                        res_type, res_name = type_name
                        if res_type == 'color':
                            # 尝试查找颜色资源
                            color_path = self.find_resource(resource_name=f'@color/{res_name}')
                            if color_path:
                                try:
                                    color_data = self.zip_file.read(color_path)
                                    return self._parse_color_state_list_from_xml(color_data)
                                except:
                                    pass
            
            return None
        
        # 直接解析颜色值
        return self._parse_color_value(color_str)
    
    def _parse_color_state_list_from_xml(self, xml_data):
        """
        从XML数据解析ColorStateList。
        
        解析selector格式的颜色状态列表，返回默认状态的颜色。
        
        Args:
            xml_data: XML数据（bytes）
            
        Returns:
            tuple: RGBA元组 (r, g, b, a)
            None: 解析失败时返回None
        """
        try:
            xml_obj = self.parse_binary_xml_to_obj(xml_data)
            
            # 检查是否为selector根元素
            if not xml_obj.tag.endswith('selector'):
                # 可能是直接的颜色值
                return self._parse_color_value(xml_obj.text if xml_obj.text else None)
            
            # 获取所有item元素
            items = xml_obj.findall('.//{*}item')
            
            # 优先查找没有 state 属性的 item（默认状态）
            for item in items:
                has_state = False
                for attr in item.attrib:
                    if 'state' in attr.lower():
                        has_state = True
                        break
                
                if not has_state:
                    # 获取 color 属性
                    color_attr = item.get('{http://schemas.android.com/apk/res/android}color')
                    if color_attr:
                        return self._parse_color_value(color_attr)
            
            # 如果没有找到默认状态，返回第一个item的颜色
            if items:
                first_item = items[0]
                color_attr = first_item.get('{http://schemas.android.com/apk/res/android}color')
                if color_attr:
                    return self._parse_color_value(color_attr)
            
            return None
            
        except Exception as e:
            app_logger.error(f"解析颜色状态列表失败: {e}")
            return None

    def _render_xml_drawable(self, xml_data, size=(432, 432)):
        """
        渲染XML drawable为图片。
        
        支持多种XML drawable类型：vector、layer-list、shape、inset、clip、scale、rotate、ripple等。
        
        Args:
            xml_data: XML数据（bytes或str）
            size: 输出尺寸，默认432x432
            
        Returns:
            PIL.Image: 渲染后的图像对象
            None: 渲染失败时返回None
        """
        try:
            if isinstance(xml_data, bytes):
                xml_obj = self.parse_binary_xml_to_obj(xml_data)
            else:
                xml_obj = etree.fromstring(xml_data.encode('utf-8'))
            
            tag = xml_obj.tag.split('}')[-1] if '}' in xml_obj.tag else xml_obj.tag
            
            if tag == 'vector':
                # vector 始终按原始尺寸的4倍渲染，保证清晰度
                # 不使用传入的 size 参数，因为 vector 是矢量图，应该按原始比例渲染
                icon_data = self._extract_vector_icon(xml_data, size=None)
                if icon_data:
                    image = Image.open(BytesIO(icon_data))
                    # 如果需要调整到特定尺寸，在这里进行缩放
                    if size is not None and image.size != size:
                        image = image.resize(size, Image.LANCZOS)
                    return image
                return None
            elif tag == 'layer-list':
                return self._render_layer_list_drawable(xml_obj, size)
            elif tag == 'shape':
                return self._render_shape_drawable(xml_obj, size)
            elif tag == 'inset':
                # InsetDrawable: 在内部drawable周围添加内边距
                # 参考：Android官方InsetDrawable.java
                return self._render_inset_drawable(xml_obj, size)
            elif tag in ['clip', 'scale', 'rotate', 'ripple']:
                # 这些标签都包含一个 drawable 属性，我们只需要渲染其内部的 drawable
                drawable_attr = xml_obj.get('{http://schemas.android.com/apk/res/android}drawable')
                if drawable_attr:
                    layer_path = self.find_resource(resource_name=drawable_attr)
                    if layer_path:
                        try:
                            layer_data = self.zip_file.read(layer_path)
                            file_ext = os.path.splitext(layer_path)[1].lower()
                            if file_ext == '.xml':
                                # 递归渲染内部 XML
                                self._xml_nest_level += 1
                                if self._xml_nest_level > 3:
                                    app_logger.error(f"错误: XML文件嵌套层数超过3层，无法继续解析: {layer_path}")
                                    self._xml_nest_level -= 1
                                    return None
                                
                                try:
                                    return self._render_xml_drawable(layer_data, size)
                                finally:
                                    self._xml_nest_level -= 1
                            else:
                                # 直接加载图片
                                layer_image = Image.open(BytesIO(layer_data))
                                if layer_image.mode != 'RGBA':
                                    layer_image = layer_image.convert('RGBA')
                                return layer_image.resize(size, Image.LANCZOS)
                        except Exception as e:
                            app_logger.warning(f"加载 {tag} 标签内部资源失败: {e}")
                return None
            else:
                app_logger.warning(f"不支持的XML drawable类型: {tag}")
                return None
        
        except Exception as e:
            app_logger.error(f"渲染XML drawable失败: {e}")
            import traceback
            app_logger.error(traceback.format_exc())
            return None

    def _get_dimen_value(self, resource_ref, bound_size=None):
        """
        获取dimen资源的像素值。
        
        解析资源引用（如 @7F0700DA 或 @com.package:dimen/name）并返回像素值。
        
        Args:
            resource_ref: 资源引用字符串
            bound_size: 边界尺寸，用于计算百分比
            
        Returns:
            int: 像素值，解析失败返回None
        """
        if not resource_ref or not resource_ref.startswith('@'):
            return None
        
        try:
            # 尝试解析资源ID
            res_id = None
            if resource_ref.startswith('@0x') or resource_ref.startswith('@7F'):
                # 十六进制资源ID
                res_id_str = resource_ref[1:]
                if res_id_str.startswith('0x'):
                    res_id = int(res_id_str, 16)
                else:
                    res_id = int(res_id_str, 16)
            
            # 通过资源ID获取dimen值
            if res_id and self.arsc_parser:
                try:
                    # 使用get_resolved_res_configs获取dimen值
                    resolved = self.arsc_parser.get_resolved_res_configs(res_id)
                    if resolved:
                        # resolved是一个列表，包含(配置, 值)元组
                        for config, value in resolved:
                            if value:
                                # 检查是否是百分比
                                if isinstance(value, str) and '%' in value:
                                    try:
                                        # 解析百分比
                                        percent = float(value.replace('%', '').strip())
                                        if bound_size:
                                            return int(bound_size * percent / 100.0)
                                        else:
                                            # 如果没有bound_size，返回百分比值
                                            return percent
                                    except ValueError:
                                        pass
                                else:
                                    # 尝试解析为dimen字符串
                                    result = self._parse_dimen_string(str(value))
                                    if result is not None:
                                        return result
                except Exception as e:
                    app_logger.debug(f"通过get_resolved_res_configs获取dimen失败: {e}")
            
            return None
            
        except Exception as e:
            app_logger.debug(f"解析dimen资源失败: {e}")
            return None

    def _parse_dimen_string(self, dimen_str):
        """
        解析dimen字符串为像素值。
        
        支持格式：dp、dip、px、sp等
        
        Args:
            dimen_str: dimen字符串（如 "16dp"、"24px"）
            
        Returns:
            int: 像素值
        """
        if not dimen_str:
            return None
        
        dimen_str = dimen_str.strip()
        
        # 默认密度（mdpi = 160dpi）
        density = 2.0  # 假设默认密度为2x（hdpi）
        
        try:
            # 移除单位并解析数值
            if dimen_str.endswith('dp') or dimen_str.endswith('dip'):
                value = float(dimen_str.rstrip('dp').rstrip('dip').strip())
                return int(value * density)
            elif dimen_str.endswith('sp'):
                value = float(dimen_str.rstrip('sp').strip())
                return int(value * density)
            elif dimen_str.endswith('px'):
                value = float(dimen_str.rstrip('px').strip())
                return int(value)
            elif dimen_str.endswith('mm'):
                value = float(dimen_str.rstrip('mm').strip())
                # 1mm ≈ 3.7795dp (at 160dpi)
                return int(value * 3.7795 * density)
            elif dimen_str.endswith('pt'):
                value = float(dimen_str.rstrip('pt').strip())
                # 1pt = 1/72 inch ≈ 2.22dp (at 160dpi)
                return int(value * 2.22 * density)
            elif dimen_str.endswith('in'):
                value = float(dimen_str.rstrip('in').strip())
                # 1in = 160dp (at 160dpi)
                return int(value * 160 * density)
            else:
                # 尝试直接解析为数字
                return int(float(dimen_str))
        except ValueError:
            return None

    def _render_inset_drawable(self, xml_obj, size=(432, 432)):
        """
        渲染inset drawable为图片。
        
        InsetDrawable在内部drawable周围添加内边距，使内部drawable显示得更小。
        与Android官方InsetDrawable.java实现保持一致。
        
        参考：
        - InsetDrawable.java 第270-282行：onBoundsChange()
        - InsetDrawable.java 第284-304行：getIntrinsicWidth/Height()
        
        Args:
            xml_obj: lxml Element对象
            size: 输出尺寸，默认432x432
            
        Returns:
            PIL.Image: 渲染后的图像对象
            None: 渲染失败时返回None
        """
        try:
            ANDROID_NS = '{http://schemas.android.com/apk/res/android}'
            
            # 解析inset属性
            # 支持格式：像素值（如"10dp"）、百分比（如"25%"）、分数（如"25%p"）、资源引用（如"@7F0700DA"）
            def parse_inset_value(value, bound_size):
                """解析inset值，返回像素值"""
                if not value:
                    return 0
                
                value = value.strip()
                
                # 资源引用格式（如 @7F0700DA 或 @com.package:dimen/name）
                if value.startswith('@'):
                    # 尝试解析资源引用
                    try:
                        # 尝试获取dimen资源值，传入bound_size用于计算百分比
                        dimen_value = self._get_dimen_value(value, bound_size)
                        if dimen_value is not None:
                            return dimen_value
                    except Exception as e:
                        app_logger.debug(f"解析资源引用失败: {e}")
                    return 0
                
                # 百分比格式
                if value.endswith('%'):
                    try:
                        fraction = float(value[:-1]) / 100.0
                        return int(bound_size * fraction)
                    except ValueError:
                        return 0
                
                # 分数格式（%p表示父容器百分比）
                if value.endswith('%p'):
                    try:
                        fraction = float(value[:-2]) / 100.0
                        return int(bound_size * fraction)
                    except ValueError:
                        return 0
                
                # 像素/dp值 - 尝试提取数字
                try:
                    # 移除单位后缀
                    num_str = value.rstrip('dp').rstrip('dip').rstrip('px').strip()
                    return int(float(num_str))
                except ValueError:
                    return 0
            
            width, height = size
            
            # 解析四个方向的inset
            inset_all = xml_obj.get(f'{ANDROID_NS}inset')
            inset_left = xml_obj.get(f'{ANDROID_NS}insetLeft')
            inset_top = xml_obj.get(f'{ANDROID_NS}insetTop')
            inset_right = xml_obj.get(f'{ANDROID_NS}insetRight')
            inset_bottom = xml_obj.get(f'{ANDROID_NS}insetBottom')
            
            # 计算各方向的inset值
            left = parse_inset_value(inset_left or inset_all, width)
            top = parse_inset_value(inset_top or inset_all, height)
            right = parse_inset_value(inset_right or inset_all, width)
            bottom = parse_inset_value(inset_bottom or inset_all, height)
            
            app_logger.debug(f"inset值: left={left}, top={top}, right={right}, bottom={bottom}")
            
            # 计算内部drawable的尺寸
            inner_width = width - left - right
            inner_height = height - top - bottom
            
            if inner_width <= 0 or inner_height <= 0:
                app_logger.warning(f"inset值过大，内部尺寸无效: {inner_width}x{inner_height}")
                return Image.new('RGBA', size, (0, 0, 0, 0))
            
            inner_size = (inner_width, inner_height)
            
            # 渲染内部drawable
            drawable_attr = xml_obj.get(f'{ANDROID_NS}drawable')
            if drawable_attr:
                # 解析资源ID
                res_id = self.parse_resource_id(drawable_attr)
                if res_id:
                    # 获取资源名称
                    xml_name = self.resolve_resource_id_to_xml_name(res_id)
                    if xml_name:
                        # 获取资源路径
                        layer_type, layer_path = self.resolve_resource_to_actual_path({
                            'xml_name': xml_name,
                            'resource_id': res_id,
                            'resource_type': self._extract_resource_type(xml_name)
                        }, self.xml_path)
                        
                        if layer_type and layer_path:
                            try:
                                if layer_type == 'file':
                                    layer_data = self.zip_file.read(layer_path)
                                    file_ext = os.path.splitext(layer_path)[1].lower()
                                    if file_ext == '.xml':
                                        # 递归渲染内部 XML
                                        self._xml_nest_level += 1
                                        if self._xml_nest_level > 3:
                                            app_logger.error(f"错误: XML文件嵌套层数超过3层")
                                            self._xml_nest_level -= 1
                                            return None
                                        
                                        try:
                                            inner_image = self._render_xml_drawable(layer_data, inner_size)
                                        finally:
                                            self._xml_nest_level -= 1
                                    else:
                                        # 直接加载图片
                                        inner_image = Image.open(BytesIO(layer_data))
                                        if inner_image.mode != 'RGBA':
                                            inner_image = inner_image.convert('RGBA')
                                        inner_image = inner_image.resize(inner_size, Image.LANCZOS)
                                    
                                    if inner_image:
                                        # 创建最终图像，将内部drawable放置到正确位置
                                        result = Image.new('RGBA', size, (0, 0, 0, 0))
                                        result.paste(inner_image, (left, top))
                                        return result
                            except Exception as e:
                                app_logger.warning(f"渲染内部drawable失败: {e}")
            
            return None
            
        except Exception as e:
            app_logger.error(f"渲染inset drawable失败: {e}")
            return None

    def _render_shape_drawable(self, xml_obj, size=(432, 432)):
        """
        渲染shape drawable为图片。
        
        支持solid（纯色填充）和gradient（渐变）等常见元素。
        与Android官方GradientDrawable实现保持一致。
        
        Args:
            xml_obj: lxml Element对象
            size: 输出尺寸，默认432x432
            
        Returns:
            PIL.Image: 渲染后的图像对象
            None: 渲染失败时返回None
        """
        try:
            base_image = Image.new('RGBA', size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(base_image)
            
            ANDROID_NS = '{http://schemas.android.com/apk/res/android}'
            
            # 解析shape类型
            shape_type = xml_obj.get(f'{ANDROID_NS}shape', 'rectangle')
            
            # 解析corners（圆角）
            corners_elem = xml_obj.find('.//{*}corners')
            corner_radius = 0
            corner_radii = None  # 四个角独立圆角 [topLeft, topRight, bottomRight, bottomLeft]
            if corners_elem is not None:
                radius_attr = corners_elem.get(f'{ANDROID_NS}radius', '0')
                corner_radius = float(radius_attr)
                
                # 检查是否有独立角圆角
                top_left = corners_elem.get(f'{ANDROID_NS}topLeftRadius')
                top_right = corners_elem.get(f'{ANDROID_NS}topRightRadius')
                bottom_right = corners_elem.get(f'{ANDROID_NS}bottomRightRadius')
                bottom_left = corners_elem.get(f'{ANDROID_NS}bottomLeftRadius')
                
                if any([top_left, top_right, bottom_right, bottom_left]):
                    corner_radii = [
                        float(top_left) if top_left else corner_radius,
                        float(top_right) if top_right else corner_radius,
                        float(bottom_right) if bottom_right else corner_radius,
                        float(bottom_left) if bottom_left else corner_radius
                    ]
            
            # 解析stroke（描边）
            stroke_elem = xml_obj.find('.//{*}stroke')
            stroke_color = None
            stroke_width = 0
            stroke_dash_width = 0
            stroke_dash_gap = 0
            if stroke_elem is not None:
                stroke_color_attr = stroke_elem.get(f'{ANDROID_NS}color')
                stroke_color = self._parse_color_value(stroke_color_attr) if stroke_color_attr else None
                stroke_width = float(stroke_elem.get(f'{ANDROID_NS}width', '0'))
                stroke_dash_width = float(stroke_elem.get(f'{ANDROID_NS}dashWidth', '0'))
                stroke_dash_gap = float(stroke_elem.get(f'{ANDROID_NS}dashGap', '0'))
            
            # 处理 solid 元素（纯色填充）
            solid_elem = xml_obj.find('.//{*}solid')
            if solid_elem is not None:
                color_attr = solid_elem.get(f'{ANDROID_NS}color')
                if color_attr:
                    color = self._parse_color_value(color_attr)
                    if color:
                        self._draw_shape_with_corners(base_image, draw, shape_type, size, color, 
                                                      corner_radius, corner_radii)
            
            # 处理 gradient 元素（渐变）
            gradient_elem = xml_obj.find('.//{*}gradient')
            if gradient_elem is not None:
                start_color = gradient_elem.get(f'{ANDROID_NS}startColor')
                end_color = gradient_elem.get(f'{ANDROID_NS}endColor')
                center_color = gradient_elem.get(f'{ANDROID_NS}centerColor')
                angle = gradient_elem.get(f'{ANDROID_NS}angle', '0')
                type_attr = gradient_elem.get(f'{ANDROID_NS}type', 'linear')
                center_x = gradient_elem.get(f'{ANDROID_NS}centerX')
                center_y = gradient_elem.get(f'{ANDROID_NS}centerY')
                gradient_radius = gradient_elem.get(f'{ANDROID_NS}gradientRadius')
                
                start_color_rgba = self._parse_color_value(start_color) if start_color else None
                end_color_rgba = self._parse_color_value(end_color) if end_color else None
                center_color_rgba = self._parse_color_value(center_color) if center_color else None
                
                if start_color_rgba and end_color_rgba:
                    # 解析centerX/centerY（归一化0-1）
                    cx = float(center_x) if center_x else None
                    cy = float(center_y) if center_y else None
                    gr = float(gradient_radius) if gradient_radius else None
                    
                    # 创建渐变效果
                    gradient_image = self._create_gradient_image(
                        start_color_rgba, 
                        end_color_rgba, 
                        size, 
                        float(angle),
                        type_attr,
                        cx, cy, gr,
                        center_color_rgba
                    )
                    if gradient_image:
                        # 创建形状遮罩
                        mask_image = Image.new('L', size, 0)
                        mask_draw = ImageDraw.Draw(mask_image)
                        self._draw_shape_mask(mask_draw, shape_type, size, corner_radius, corner_radii, 255)
                        
                        # 应用遮罩
                        temp_image = Image.new('RGBA', size, (0, 0, 0, 0))
                        temp_image.paste(gradient_image, (0, 0), mask_image)
                        base_image = Image.alpha_composite(base_image, temp_image)
            
            # 绘制描边
            if stroke_color and stroke_width > 0:
                self._draw_shape_stroke(draw, shape_type, size, stroke_color, stroke_width, 
                                        corner_radius, corner_radii, stroke_dash_width, stroke_dash_gap)
            
            return base_image
        
        except Exception as e:
            app_logger.error(f"渲染shape drawable失败: {e}")
            return None
    
    def _draw_shape_with_corners(self, image, draw, shape_type, size, color, corner_radius, corner_radii):
        """
        绘制带圆角的形状。
        
        Args:
            image: PIL图像对象
            draw: ImageDraw对象
            shape_type: 形状类型
            size: 尺寸
            color: 填充颜色
            corner_radius: 圆角半径
            corner_radii: 四角独立圆角
        """
        width, height = size
        
        if shape_type == 'oval':
            draw.ellipse([0, 0, width, height], fill=color)
        elif shape_type == 'line':
            y = height // 2
            draw.line([(0, y), (width, y)], fill=color, width=height)
        elif shape_type == 'ring':
            cx, cy = width // 2, height // 2
            outer_r = min(width, height) // 2
            inner_r = outer_r // 2
            draw.ellipse([cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r], fill=color)
            if inner_r > 0:
                draw.ellipse([cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r], fill=(0, 0, 0, 0))
        else:
            # rectangle（默认）
            if corner_radii:
                # 四角独立圆角
                self._draw_rounded_rect_with_individual_corners(draw, 0, 0, width, height, corner_radii, color)
            elif corner_radius > 0:
                draw.rounded_rectangle([0, 0, width - 1, height - 1], radius=corner_radius, fill=color)
            else:
                draw.rectangle([0, 0, width, height], fill=color)
    
    def _draw_shape_mask(self, draw, shape_type, size, corner_radius, corner_radii, fill_value):
        """
        绘制形状遮罩。
        
        Args:
            draw: ImageDraw对象
            shape_type: 形状类型
            size: 尺寸
            corner_radius: 圆角半径
            corner_radii: 四角独立圆角
            fill_value: 填充值
        """
        width, height = size
        
        if shape_type == 'oval':
            draw.ellipse([0, 0, width, height], fill=fill_value)
        elif shape_type == 'line':
            y = height // 2
            draw.line([(0, y), (width, y)], fill=fill_value, width=height)
        elif shape_type == 'ring':
            cx, cy = width // 2, height // 2
            outer_r = min(width, height) // 2
            draw.ellipse([cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r], fill=fill_value)
        else:
            if corner_radii:
                self._draw_rounded_rect_with_individual_corners(draw, 0, 0, width, height, corner_radii, fill_value)
            elif corner_radius > 0:
                draw.rounded_rectangle([0, 0, width - 1, height - 1], radius=corner_radius, fill=fill_value)
            else:
                draw.rectangle([0, 0, width, height], fill=fill_value)
    
    def _draw_shape_stroke(self, draw, shape_type, size, stroke_color, stroke_width, 
                           corner_radius, corner_radii, dash_width, dash_gap):
        """
        绘制形状描边。
        
        Args:
            draw: ImageDraw对象
            shape_type: 形状类型
            size: 尺寸
            stroke_color: 描边颜色
            stroke_width: 描边宽度
            corner_radius: 圆角半径
            corner_radii: 四角独立圆角
            dash_width: 虚线宽度
            dash_gap: 虚线间隙
        """
        width, height = size
        half_width = stroke_width / 2
        
        if shape_type == 'oval':
            draw.ellipse([half_width, half_width, width - half_width, height - half_width], 
                        outline=stroke_color, width=int(stroke_width))
        elif shape_type == 'line':
            y = height // 2
            draw.line([(0, y), (width, y)], fill=stroke_color, width=int(stroke_width))
        elif shape_type == 'ring':
            cx, cy = width // 2, height // 2
            outer_r = min(width, height) // 2 - half_width
            draw.ellipse([cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r], 
                        outline=stroke_color, width=int(stroke_width))
        else:
            if corner_radii:
                # 四角独立圆角的描边（简化处理）
                draw.rounded_rectangle([half_width, half_width, width - half_width, height - half_width], 
                                       radius=max(corner_radii), outline=stroke_color, width=int(stroke_width))
            elif corner_radius > 0:
                draw.rounded_rectangle([half_width, half_width, width - half_width, height - half_width], 
                                       radius=corner_radius, outline=stroke_color, width=int(stroke_width))
            else:
                draw.rectangle([half_width, half_width, width - half_width, height - half_width], 
                              outline=stroke_color, width=int(stroke_width))
    
    def _draw_rounded_rect_with_individual_corners(self, draw, x1, y1, x2, y2, radii, fill):
        """
        绘制四角独立圆角的矩形。
        
        与Android官方实现一致，支持每个角不同的圆角半径。
        
        Args:
            draw: ImageDraw对象
            x1, y1, x2, y2: 矩形坐标
            radii: 四个角的圆角半径 [topLeft, topRight, bottomRight, bottomLeft]
            fill: 填充颜色
        """
        tl, tr, br, bl = radii
        
        # 如果所有角半径相同，使用内置方法
        if tl == tr == br == bl:
            if tl > 0:
                draw.rounded_rectangle([x1, y1, x2 - 1, y2 - 1], radius=tl, fill=fill)
            else:
                draw.rectangle([x1, y1, x2, y2], fill=fill)
            return
        
        # 使用多边形近似绘制不同圆角的矩形
        points = []
        num_segments = 16
        
        # 左上角
        if tl > 0:
            for i in range(num_segments + 1):
                angle = math.pi + math.pi / 2 * i / num_segments
                px = x1 + tl + tl * math.cos(angle)
                py = y1 + tl + tl * math.sin(angle)
                points.append((px, py))
        else:
            points.append((x1, y1))
        
        # 右上角
        if tr > 0:
            for i in range(num_segments + 1):
                angle = math.pi * 3 / 2 + math.pi / 2 * i / num_segments
                px = x2 - tr + tr * math.cos(angle)
                py = y1 + tr + tr * math.sin(angle)
                points.append((px, py))
        else:
            points.append((x2, y1))
        
        # 右下角
        if br > 0:
            for i in range(num_segments + 1):
                angle = math.pi * 2 * i / num_segments
                px = x2 - br + br * math.cos(angle)
                py = y2 - br + br * math.sin(angle)
                points.append((px, py))
        else:
            points.append((x2, y2))
        
        # 左下角
        if bl > 0:
            for i in range(num_segments + 1):
                angle = math.pi / 2 + math.pi / 2 * i / num_segments
                px = x1 + bl + bl * math.cos(angle)
                py = y2 - bl + bl * math.sin(angle)
                points.append((px, py))
        else:
            points.append((x1, y2))
        
        draw.polygon(points, fill=fill)
    
    def _create_gradient_image(self, start_color, end_color, size, angle=0, gradient_type='linear', 
                                center_x=None, center_y=None, radius=None, middle_color=None):
        """
        创建渐变图像。
        
        与Android官方GradientDrawable实现保持一致，支持：
        - 线性渐变（linear）：支持8方向映射和负角度处理
        - 径向渐变（radial）：支持centerX/centerY/radius
        - 扫描渐变（sweep）：支持centerX/centerY
        
        Args:
            start_color: 起始颜色 (r, g, b, a)
            end_color: 结束颜色 (r, g, b, a)
            size: 图像尺寸 (width, height)
            angle: 渐变角度（度），默认0。与Android官方一致：
                   0=左到右, 90=下到上, 180=右到左, 270=上到下
            gradient_type: 渐变类型，'linear'、'radial' 或 'sweep'，默认 'linear'
            center_x: 径向/扫描渐变中心X（0-1归一化或像素值）
            center_y: 径向/扫描渐变中心Y（0-1归一化或像素值）
            radius: 径向渐变半径
            middle_color: 中间颜色（可选）
            
        Returns:
            PIL.Image: 渐变图像对象
            None: 创建失败时返回None
        """
        try:
            width, height = size
            image = Image.new('RGBA', size)
            pixels = image.load()
            
            # 构建颜色停止点
            color_stops = [(0.0, start_color)]
            if middle_color:
                color_stops.append((0.5, middle_color))
            color_stops.append((1.0, end_color))
            
            if gradient_type == 'linear':
                # 处理负角度，与Android官方一致
                # Android: angle = ((angle % 360) + 360) % 360
                angle = ((angle % 360) + 360) % 360
                
                # Android官方角度到方向的映射（GradientDrawable.java）：
                # 0° = LEFT_RIGHT (左到右)
                # 45° = BL_TR (左下到右上)
                # 90° = BOTTOM_TOP (下到上)
                # 135° = BR_TL (右下到左上)
                # 180° = RIGHT_LEFT (右到左)
                # 225° = TR_BL (右上到左下)
                # 270° = TOP_BOTTOM (上到下)
                # 315° = TL_BR (左上到右下)
                
                # Android的角度是从"左"开始，逆时针旋转
                # 图像坐标系中Y轴向下，所以需要取负角度
                # angle=0 -> dx=1, dy=0 (向右)
                # angle=90 -> dx=0, dy=-1 (向上)
                # angle=180 -> dx=-1, dy=0 (向左)
                # angle=270 -> dx=0, dy=1 (向下)
                angle_rad = math.radians(-angle)
                
                # 计算渐变的起始和结束点
                cx, cy = width / 2, height / 2
                max_dist = math.sqrt((width/2)**2 + (height/2)**2)
                
                dx = math.cos(angle_rad) * max_dist
                dy = math.sin(angle_rad) * max_dist
                
                x0, y0 = cx - dx, cy - dy
                x1, y1 = cx + dx, cy + dy
                
                len_sq = (x1 - x0) ** 2 + (y1 - y0) ** 2
                
                if len_sq == 0:
                    for y in range(height):
                        for x in range(width):
                            pixels[x, y] = start_color
                else:
                    for y in range(height):
                        for x in range(width):
                            t = ((x - x0) * (x1 - x0) + (y - y0) * (y1 - y0)) / len_sq
                            t = max(0.0, min(1.0, t))
                            
                            # 在颜色停止点之间插值
                            r, g, b, a = start_color
                            for i in range(len(color_stops) - 1):
                                t0, (r0, g0, b0, a0) = color_stops[i]
                                t1, (r1, g1, b1, a1) = color_stops[i + 1]
                                if t0 <= t <= t1:
                                    if t1 > t0:
                                        frac = (t - t0) / (t1 - t0)
                                        r = int(r0 + frac * (r1 - r0))
                                        g = int(g0 + frac * (g1 - g0))
                                        b = int(b0 + frac * (b1 - b0))
                                        a = int(a0 + frac * (a1 - a0))
                                    break
                            
                            pixels[x, y] = (r, g, b, a)
                            
            elif gradient_type == 'radial':
                # 径向渐变
                # 处理centerX/centerY
                if center_x is not None:
                    if 0 <= center_x <= 1:
                        cx = int(center_x * width)
                    else:
                        cx = int(center_x)
                else:
                    cx = width // 2
                
                if center_y is not None:
                    if 0 <= center_y <= 1:
                        cy = int(center_y * height)
                    else:
                        cy = int(center_y)
                else:
                    cy = height // 2
                
                # 处理radius
                if radius is not None:
                    if 0 < radius <= 1:
                        r = int(radius * min(width, height))
                    else:
                        r = int(radius)
                else:
                    r = max(width, height) // 2
                
                for y in range(height):
                    for x in range(width):
                        dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
                        t = min(1.0, dist / r) if r > 0 else 0
                        
                        # 在颜色停止点之间插值
                        r_val, g_val, b_val, a_val = start_color
                        for i in range(len(color_stops) - 1):
                            t0, (r0, g0, b0, a0) = color_stops[i]
                            t1, (r1, g1, b1, a1) = color_stops[i + 1]
                            if t0 <= t <= t1:
                                if t1 > t0:
                                    frac = (t - t0) / (t1 - t0)
                                    r_val = int(r0 + frac * (r1 - r0))
                                    g_val = int(g0 + frac * (g1 - g0))
                                    b_val = int(b0 + frac * (b1 - b0))
                                    a_val = int(a0 + frac * (a1 - a0))
                                break
                        
                        pixels[x, y] = (r_val, g_val, b_val, a_val)
                        
            elif gradient_type == 'sweep':
                # 扫描渐变
                if center_x is not None:
                    if 0 <= center_x <= 1:
                        cx = int(center_x * width)
                    else:
                        cx = int(center_x)
                else:
                    cx = width // 2
                
                if center_y is not None:
                    if 0 <= center_y <= 1:
                        cy = int(center_y * height)
                    else:
                        cy = int(center_y)
                else:
                    cy = height // 2
                
                for y in range(height):
                    for x in range(width):
                        dx = x - cx
                        dy = y - cy
                        angle = math.atan2(dy, dx)
                        t = (angle + math.pi) / (2 * math.pi)
                        
                        # 在颜色停止点之间插值
                        r_val, g_val, b_val, a_val = start_color
                        for i in range(len(color_stops) - 1):
                            t0, (r0, g0, b0, a0) = color_stops[i]
                            t1, (r1, g1, b1, a1) = color_stops[i + 1]
                            if t0 <= t <= t1:
                                if t1 > t0:
                                    frac = (t - t0) / (t1 - t0)
                                    r_val = int(r0 + frac * (r1 - r0))
                                    g_val = int(g0 + frac * (g1 - g0))
                                    b_val = int(b0 + frac * (b1 - b0))
                                    a_val = int(a0 + frac * (a1 - a0))
                                break
                        
                        pixels[x, y] = (r_val, g_val, b_val, a_val)
            
            return image
        
        except Exception as e:
            app_logger.error(f"创建渐变图像失败: {e}")
            return None
    
    def _render_layer_list_drawable(self, xml_obj, size=(432, 432)):
        """
        渲染layer-list drawable为图片。
        
        与Android官方LayerDrawable实现保持一致。
        支持inset、gravity、width/height等属性。
        
        Args:
            xml_obj: lxml Element对象
            size: 输出尺寸，默认432x432
            
        Returns:
            PIL.Image: 渲染后的图像对象
            None: 渲染失败时返回None
        """
        try:
            base_image = Image.new('RGBA', size, (0, 0, 0, 0))
            ANDROID_NS = '{http://schemas.android.com/apk/res/android}'
            
            # 解析layer-list的opacity属性
            opacity = 1.0
            opacity_attr = xml_obj.get(f'{ANDROID_NS}opacity')
            if opacity_attr:
                try:
                    opacity = float(opacity_attr)
                    if opacity > 1.0:
                        opacity = opacity / 255.0  # 可能是0-255范围
                except ValueError:
                    pass
            
            # 解析paddingMode（暂不实现，仅记录）
            padding_mode = xml_obj.get(f'{ANDROID_NS}paddingMode', 'nest')
            
            for item in xml_obj.findall('.//{*}item'):
                # 解析item属性
                left = self._parse_dimension_value(item.get(f'{ANDROID_NS}left', '0'), size[0])
                top = self._parse_dimension_value(item.get(f'{ANDROID_NS}top', '0'), size[1])
                right = self._parse_dimension_value(item.get(f'{ANDROID_NS}right', '0'), size[0])
                bottom = self._parse_dimension_value(item.get(f'{ANDROID_NS}bottom', '0'), size[1])
                
                # 解析start/end（RTL支持）
                start = item.get(f'{ANDROID_NS}start')
                end = item.get(f'{ANDROID_NS}end')
                # 简化处理：start等同于left，end等同于right
                if start is not None:
                    left = self._parse_dimension_value(start, size[0])
                if end is not None:
                    right = self._parse_dimension_value(end, size[0])
                
                # 解析显式width/height
                item_width = item.get(f'{ANDROID_NS}width')
                item_height = item.get(f'{ANDROID_NS}height')
                
                # 解析gravity
                gravity = item.get(f'{ANDROID_NS}gravity', '')
                
                # 解析id（暂不使用）
                item_id = item.get(f'{ANDROID_NS}id')
                
                drawable_attr = item.get(f'{ANDROID_NS}drawable')
                if drawable_attr:
                    layer_path = self.find_resource(resource_name=drawable_attr)
                    if layer_path:
                        try:
                            layer_data = self.zip_file.read(layer_path)
                            file_ext = os.path.splitext(layer_path)[1].lower()
                            if file_ext == '.xml':
                                self._xml_nest_level += 1
                                if self._xml_nest_level > 3:
                                    app_logger.error(f"错误: XML文件嵌套层数超过3层，无法继续解析: {layer_path}")
                                    self._xml_nest_level -= 1
                                    continue
                                
                                try:
                                    layer_image = self._render_xml_drawable(layer_data, size)
                                finally:
                                    self._xml_nest_level -= 1
                            else:
                                layer_image = Image.open(BytesIO(layer_data))
                            
                            if layer_image:
                                if layer_image.mode != 'RGBA':
                                    layer_image = layer_image.convert('RGBA')
                                
                                # 计算图层尺寸
                                layer_w, layer_h = layer_image.size
                                
                                # 如果有显式width/height，使用它们
                                if item_width:
                                    layer_w = self._parse_dimension_value(item_width, size[0])
                                if item_height:
                                    layer_h = self._parse_dimension_value(item_height, size[1])
                                
                                # 应用gravity定位
                                pos_x, pos_y = self._apply_gravity(gravity, size, (layer_w, layer_h), (left, top, right, bottom))
                                
                                # 缩放图层到目标尺寸
                                if (item_width or item_height) and (layer_w != layer_image.width or layer_h != layer_image.height):
                                    layer_image = layer_image.resize((layer_w, layer_h), Image.LANCZOS)
                                
                                # 创建与base_image相同尺寸的临时图像
                                temp_image = Image.new('RGBA', size, (0, 0, 0, 0))
                                temp_image.paste(layer_image, (pos_x, pos_y))
                                
                                # 合成到基础图像
                                base_image = Image.alpha_composite(base_image, temp_image)
                        except Exception as e:
                            app_logger.error(f"加载图层失败: {e}")
            
            # 应用opacity
            if opacity < 1.0:
                base_image = self._apply_opacity(base_image, opacity)
            
            return base_image
        
        except Exception as e:
            app_logger.error(f"渲染layer-list drawable失败: {e}")
            return None
    
    def _parse_dimension_value(self, value, reference_size=100):
        """
        解析尺寸值。
        
        支持dp、px、sp等单位，以及百分比。
        
        Args:
            value: 尺寸值字符串
            reference_size: 参考尺寸（用于百分比计算）
            
        Returns:
            int: 像素值
        """
        if value is None:
            return 0
        
        value = str(value).strip()
        
        try:
            # 百分比
            if value.endswith('%'):
                return int(reference_size * float(value[:-1]) / 100)
            
            # dp单位
            if value.endswith('dp') or value.endswith('dip'):
                return int(float(value.rstrip('dip').rstrip('dp')) * 4)  # 假设4x密度
            
            # px单位
            if value.endswith('px'):
                return int(float(value[:-2]))
            
            # sp单位
            if value.endswith('sp'):
                return int(float(value[:-2]) * 4)
            
            # mm单位
            if value.endswith('mm'):
                return int(float(value[:-2]) * 15.12)  # 约160dpi
            
            # in单位
            if value.endswith('in'):
                return int(float(value[:-2]) * 640)  # 约160dpi
            
            # pt单位
            if value.endswith('pt'):
                return int(float(value[:-2]) * 8.89)
            
            # 纯数字（假设为像素）
            return int(float(value))
            
        except (ValueError, AttributeError):
            return 0
    
    def _apply_gravity(self, gravity, container_size, content_size, insets=(0, 0, 0, 0)):
        """
        应用gravity定位。
        
        与Android官方Gravity类实现保持一致。
        
        Args:
            gravity: gravity字符串，如 'center', 'left|top', 'fill_horizontal'
            container_size: 容器尺寸 (width, height)
            content_size: 内容尺寸 (width, height)
            insets: 内边距 (left, top, right, bottom)
            
        Returns:
            tuple: 定位坐标 (x, y)
        """
        container_w, container_h = container_size
        content_w, content_h = content_size
        left, top, right, bottom = insets
        
        # 可用空间
        available_w = container_w - left - right
        available_h = container_h - top - bottom
        
        # 默认位置（左上角）
        x, y = left, top
        
        if not gravity:
            # 默认填充
            return left, top
        
        gravity = gravity.lower()
        
        # 解析gravity标志
        has_center = 'center' in gravity
        has_center_horizontal = 'center_horizontal' in gravity or 'center' in gravity
        has_center_vertical = 'center_vertical' in gravity or 'center' in gravity
        has_left = 'left' in gravity
        has_right = 'right' in gravity
        has_top = 'top' in gravity
        has_bottom = 'bottom' in gravity
        has_fill_horizontal = 'fill_horizontal' in gravity
        has_fill_vertical = 'fill_vertical' in gravity
        has_fill = 'fill' in gravity
        
        # 水平定位
        if has_fill_horizontal or has_fill:
            x = left
            content_w = available_w
        elif has_center_horizontal:
            x = left + (available_w - content_w) // 2
        elif has_right:
            x = left + available_w - content_w
        elif has_left:
            x = left
        else:
            # 默认左对齐
            x = left
        
        # 垂直定位
        if has_fill_vertical or has_fill:
            y = top
            content_h = available_h
        elif has_center_vertical:
            y = top + (available_h - content_h) // 2
        elif has_bottom:
            y = top + available_h - content_h
        elif has_top:
            y = top
        else:
            # 默认顶部对齐
            y = top
        
        return max(0, x), max(0, y)
    
    def _apply_opacity(self, image, opacity):
        """
        应用透明度到图像。
        
        Args:
            image: PIL RGBA图像
            opacity: 透明度 (0.0-1.0)
            
        Returns:
            PIL.Image: 应用透明度后的图像
        """
        if opacity >= 1.0:
            return image
        
        if opacity <= 0.0:
            return Image.new('RGBA', image.size, (0, 0, 0, 0))
        
        pixels = image.load()
        width, height = image.size
        
        for y in range(height):
            for x in range(width):
                r, g, b, a = pixels[x, y]
                pixels[x, y] = (r, g, b, int(a * opacity))
        
        return image

    def _extract_layer_list_icon(self, xml_data):
        """
        提取layer-list图标并合成所有图层。
        
        Args:
            xml_data: 二进制XML数据
            
        Returns:
            bytes: 合成后的PNG格式图标数据
            None: 提取失败时返回None
        """
        try:
            # 解析 XML 获取所有图层的 XML 名称
            layer_names = self.parse_layer_list_xml(xml_data)
            
            if not layer_names:
                return None
            
            app_logger.debug(f"找到 {len(layer_names)} 个图层")
            
            # 将 XML 名称转换为 APK 中的实际文件路径
            layer_paths = []
            for layer_name in layer_names:
                layer_path = self.find_resource(
                    resource_name=layer_name
                )
                if layer_path:
                    layer_paths.append(layer_path)
            
            if not layer_paths:
                return None
            
            # 从 APK 中读取所有图层图片数据并转换为 PIL Image 对象
            images = []
            for layer_path in layer_paths:
                layer_data = self.zip_file.read(layer_path)
                file_ext = os.path.splitext(layer_path)[1].lower()
                if file_ext == '.xml':
                    # 检查XML嵌套层数
                    self._xml_nest_level += 1
                    if self._xml_nest_level > 3:
                        app_logger.error(f"错误: XML文件嵌套层数超过3层，无法继续解析: {layer_path}")
                        self._xml_nest_level -= 1
                        continue
                    
                    try:
                        layer_image = self._render_xml_drawable(layer_data)
                    finally:
                        self._xml_nest_level -= 1
                else:
                    layer_image = Image.open(BytesIO(layer_data))
                
                if layer_image:
                    images.append(layer_image)
            
            if not images:
                return None
            
            # 使用第一张图作为基础图层
            base_image = images[0]
            output_size = base_image.size
            
            # 确保基础图像是 RGBA 模式（支持透明度）
            if base_image.mode != 'RGBA':
                base_image = base_image.convert('RGBA')
            
            # 将其他图层逐个叠加到基础图层上
            for img in images[1:]:
                # 调整图层尺寸与基础图层一致
                img_resized = img.resize(output_size, Image.LANCZOS)
                if img_resized.mode != 'RGBA':
                    img_resized = img_resized.convert('RGBA')
                
                # 使用 alpha 通道作为掩码进行合成
                if img_resized.mode == 'RGBA':
                    r, g, b, a = img_resized.split()
                    base_image.paste(img_resized, (0, 0), a)
                else:
                    base_image.paste(img_resized, (0, 0))
            
            # 将合成后的图片保存为 PNG 格式的字节流
            output = BytesIO()
            base_image.save(output, format='PNG')
            return output.getvalue()
        
        except Exception as e:
            app_logger.error(f"提取 layer-list 图标失败: {e}")
            import traceback
            app_logger.error(traceback.format_exc())
            return None

    def _extract_selector_icon(self, xml_data):
        """
        提取selector图标的默认状态。
        
        Selector是状态选择器，根据控件状态显示不同图标。
        此方法提取默认状态（无状态）的图标。
        
        Args:
            xml_data: 二进制XML数据
            
        Returns:
            bytes: PNG格式图标数据
            None: 提取失败时返回None
        """
        try:
            # 解析 XML 获取默认状态的图标 XML 名称
            default_icon = self.parse_selector_xml(xml_data)
            if default_icon:
                # 将 XML 名称转换为 APK 中的实际文件路径
                icon_path = self.find_resource(
                    resource_name=default_icon
                )
                if icon_path:
                    # 检查是否是XML文件，如果是则需要进一步处理
                    file_ext = os.path.splitext(icon_path)[1].lower()
                    if file_ext == '.xml':
                        # 检查XML嵌套层数
                        self._xml_nest_level += 1
                        if self._xml_nest_level > 3:
                            app_logger.error(f"错误: XML文件嵌套层数超过3层，无法继续解析: {icon_path}")
                            self._xml_nest_level -= 1
                            return None
                        
                        try:
                            xml_icon_data = self.zip_file.read(icon_path)
                            icon_image = self._render_xml_drawable(xml_icon_data)
                            if icon_image:
                                output = BytesIO()
                                icon_image.save(output, format='PNG')
                                return output.getvalue()
                        finally:
                            self._xml_nest_level -= 1
                    else:
                        # 从 APK 中读取图标数据
                        return self.zip_file.read(icon_path)
            return None
        except Exception as e:
            app_logger.error(f"提取 selector 图标失败: {e}")
            return None

    def _extract_bitmap_icon(self, xml_obj):
        """
        提取bitmap图标。
        
        从bitmap标签的src属性获取实际图片文件路径并读取数据。
        
        Args:
            xml_obj: lxml Element对象
            
        Returns:
            bytes: 图标二进制数据
            None: 提取失败时返回None
        """
        try:
            # 获取 bitmap 的 src 属性（指向实际图片文件）
            src_attr = xml_obj.get('{http://schemas.android.com/apk/res/android}src')
            if src_attr:
                # 将 XML 名称转换为 APK 中的实际文件路径
                icon_path = self.find_resource(
                    resource_name=src_attr
                )
                if icon_path:
                    # 从 APK 中读取图标数据
                    return self.zip_file.read(icon_path)
            return None
        except Exception as e:
            app_logger.error(f"提取 bitmap 图标失败: {e}")
            return None

    def _extract_vector_icon(self, xml_data, size=None):
        """
        提取vector drawable图标并渲染为PNG图像。
        
        解析矢量图XML，提取path数据并渲染为位图。
        支持尺寸单位：dp、dip、px、sp、mm、in、pt。
        
        Args:
            xml_data: XML数据（二进制或文本格式）
            size: 输出尺寸 (width, height) 元组，可选。如不指定则使用XML中定义的尺寸
            
        Returns:
            bytes: PNG格式图标数据
            None: 提取失败时返回None
        """
        try:
            ANDROID_NS = '{http://schemas.android.com/apk/res/android}'
            
            # 检查是二进制 XML 还是普通文本 XML
            if xml_data.startswith(b'\x03\x00'):
                printer = AXMLPrinter(xml_data)
                xml_obj = printer.get_xml_obj()
            else:
                xml_obj = etree.fromstring(xml_data)
            
            if not xml_obj.tag.endswith('vector'):
                return None
            
            width_str = xml_obj.get(f'{ANDROID_NS}width', '24dp')
            height_str = xml_obj.get(f'{ANDROID_NS}height', '24dp')
            viewport_width = float(xml_obj.get(f'{ANDROID_NS}viewportWidth', '24'))
            viewport_height = float(xml_obj.get(f'{ANDROID_NS}viewportHeight', '24'))
            
            # 解析 vector 根元素的 alpha 属性
            root_alpha_str = xml_obj.get(f'{ANDROID_NS}alpha', '1.0')
            try:
                root_alpha = max(0.0, min(1.0, float(root_alpha_str)))
            except ValueError:
                root_alpha = 1.0
            
            # 解析 tint 和 tintMode 属性
            tint_color_str = xml_obj.get(f'{ANDROID_NS}tint')
            tint_mode_str = xml_obj.get(f'{ANDROID_NS}tintMode', 'src_in')
            
            # 解析 autoMirrored 属性（RTL支持）
            # 当为true时，在RTL布局中自动水平翻转图标
            auto_mirrored = xml_obj.get(f'{ANDROID_NS}autoMirrored', 'false').lower() == 'true'
            
            app_logger.debug(f"Vector 图标信息:")
            app_logger.debug(f"  尺寸: {width_str} x {height_str}")
            app_logger.debug(f"  视口: {viewport_width} x {viewport_height}")
            app_logger.debug(f"  alpha: {root_alpha}, tint: {tint_color_str}, tintMode: {tint_mode_str}")
            if auto_mirrored:
                app_logger.debug(f"  autoMirrored: {auto_mirrored}")
            
            def parse_color_stops(items: List[Dict[str, Any]], parse_color_func) -> List[Tuple[float, Tuple[int, int, int, int]]]:
                """
                解析颜色停止点列表，返回排序后的(offset, rgba)列表。
                
                Args:
                    items: 颜色停止点字典列表
                    parse_color_func: 颜色解析函数
                    
                Returns:
                    排序后的颜色停止点列表 [(offset, (r, g, b, a)), ...]
                """
                color_stops = []
                for item in items:
                    color_str = item['color']
                    offset = item['offset']
                    rgba = parse_color_func(color_str)
                    if isinstance(rgba, tuple):
                        if offset is None:
                            if len(color_stops) == 0:
                                offset = 0.0
                            elif len(color_stops) == len(items) - 1:
                                offset = 1.0
                            else:
                                offset = (len(color_stops) + 1) / len(items)
                        color_stops.append((offset, rgba))
                
                if len(color_stops) == 0:
                    color_stops = [(0.0, (0, 0, 0, 255)), (1.0, (255, 255, 255, 255))]
                elif len(color_stops) == 1:
                    color_stops.append((1.0, color_stops[0][1]))
                
                color_stops.sort(key=lambda x: x[0])
                return color_stops
            
            def interpolate_color(color_stops: List[Tuple[float, Tuple[int, int, int, int]]], t: float) -> Tuple[int, int, int, int]:
                """
                使用二分查找快速插值颜色。
                
                Args:
                    color_stops: 排序后的颜色停止点列表
                    t: 插值位置 (0.0-1.0)
                    
                Returns:
                    插值后的RGBA颜色元组
                """
                if t <= color_stops[0][0]:
                    return color_stops[0][1]
                if t >= color_stops[-1][0]:
                    return color_stops[-1][1]
                
                offsets = [stop[0] for stop in color_stops]
                idx = bisect.bisect_right(offsets, t) - 1
                
                t0, (r0, g0, b0, a0) = color_stops[idx]
                t1, (r1, g1, b1, a1) = color_stops[idx + 1]
                
                if t1 == t0:
                    frac = 0.0
                else:
                    frac = (t - t0) / (t1 - t0)
                
                r = int(r0 + frac * (r1 - r0))
                g = int(g0 + frac * (g1 - g0))
                b = int(b0 + frac * (b1 - b0))
                a = int(a0 + frac * (a1 - a0))
                return (r, g, b, a)
            
            def draw_with_alpha(base_img, draw_func):
                """
                辅助函数：使用正确处理带alpha的绘制，确保正确合成
                
                Args:
                    base_img: 基础图像
                    draw_func: 绘制函数，接受一个ImageDraw.Draw对象作为参数
                Returns:
                    合成后的图像
                """
                img_width, img_height = base_img.size
                temp_img = Image.new('RGBA', (img_width, img_height), (0, 0, 0, 0))
                temp_draw = ImageDraw.Draw(temp_img)
                draw_func(temp_draw)
                return Image.alpha_composite(base_img, temp_img)
            
            def parse_dimension(dim_str):
                if not dim_str:
                    return 24.0
                dim_str = str(dim_str).strip()
                try:
                    if dim_str.endswith('dp') or dim_str.endswith('dip'):
                        return float(dim_str.rstrip('dip').rstrip('dp'))
                    elif dim_str.endswith('px'):
                        return float(dim_str[:-2])
                    elif dim_str.endswith('sp'):
                        return float(dim_str[:-2])
                    elif dim_str.endswith('mm'):
                        return float(dim_str[:-2]) * 3.779527559
                    elif dim_str.endswith('in'):
                        return float(dim_str[:-2]) * 160
                    elif dim_str.endswith('pt'):
                        return float(dim_str[:-2]) * 2.222222222
                    else:
                        return float(dim_str)
                except ValueError:
                    return 24.0
            
            def parse_color(color_str, alpha=None):
                app_logger.debug(f"  parse_color 输入: color_str={color_str}, alpha={alpha}")
                # 检查是否是渐变信息字典
                if isinstance(color_str, dict) and color_str.get('type') == 'gradient':
                    app_logger.debug(f"  parse_color: 检测到渐变信息字典")
                    # 应用 alpha 参数到渐变的每个 item
                    gradient_info = color_str.copy()
                    new_items = []
                    for item in gradient_info.get('items', []):
                        # 解析 item 的颜色
                        item_color = item['color']
                        if alpha is not None:
                            # 如果有 alpha，解析颜色后再应用 alpha
                            parsed_rgba = parse_color(item_color)
                            if isinstance(parsed_rgba, tuple):
                                # 计算新的 alpha
                                r, g, b, a = parsed_rgba
                                new_a = int(a * alpha)
                                # 转换回颜色字符串
                                new_item_color = f'#{new_a:02X}{r:02X}{g:02X}{b:02X}'
                                new_items.append({'color': new_item_color, 'offset': item['offset']})
                            else:
                                new_items.append(item)
                        else:
                            new_items.append(item)
                    gradient_info['items'] = new_items
                    app_logger.debug(f"  parse_color: 返回渐变信息")
                    return gradient_info
                
                if not color_str:
                    color_rgba = (0, 0, 0, 255)
                else:
                    # 检查是否是字符串（防止已经是元组的情况）
                    if isinstance(color_str, tuple):
                        color_rgba = color_str
                    else:
                        color_str = color_str.strip()
                    # 首先尝试解析颜色资源ID（如 @7F040007 或 @android:0106000B）
                    if color_str.startswith('@'):
                        # 解析资源ID
                        res_id = XmlIconParser.parse_resource_id(color_str)
                        if res_id:
                            # 尝试通过资源ID获取颜色值
                            color_value = self.get_color_resource_value(res_id)
                            if color_value:
                                # 递归调用parse_color来解析获取到的颜色字符串
                                result = parse_color(color_value, alpha)
                                app_logger.debug(f"  parse_color 从资源解析: {color_str} -> {color_value} -> {result}")
                                return result
                        # 如果无法解析资源ID，返回默认灰色（以便能看清path形状）
                        color_rgba = (128, 128, 128, 255)
                        app_logger.debug(f"  parse_color 无法解析资源 {color_str}，使用默认灰色")
                    elif color_str.startswith('?'):
                        # 处理?attr/类型的资源，返回默认灰色
                        color_rgba = (128, 128, 128, 255)
                        app_logger.debug(f"  parse_color ?attr 类型资源，使用默认灰色")
                    elif color_str.startswith('#'):
                        hex_color = color_str[1:]
                        try:
                            # 验证十六进制字符串是否有效
                            valid_hex_chars = set('0123456789abcdefABCDEF')
                            if not all(c in valid_hex_chars for c in hex_color):
                                color_rgba = (128, 128, 128, 255)
                            elif len(hex_color) == 8:
                                # 直接作为普通 ARGB 颜色解析
                                a = int(hex_color[0:2], 16)
                                r = int(hex_color[2:4], 16)
                                g = int(hex_color[4:6], 16)
                                b = int(hex_color[6:8], 16)
                                color_rgba = (r, g, b, a)
                            elif len(hex_color) == 6:
                                r = int(hex_color[0:2], 16)
                                g = int(hex_color[2:4], 16)
                                b = int(hex_color[4:6], 16)
                                color_rgba = (r, g, b, 255)
                            elif len(hex_color) == 4:
                                r = int(hex_color[0], 16) * 17
                                g = int(hex_color[1], 16) * 17
                                b = int(hex_color[2], 16) * 17
                                a = int(hex_color[3], 16) * 17
                                color_rgba = (r, g, b, a)
                            elif len(hex_color) == 3:
                                r = int(hex_color[0], 16) * 17
                                g = int(hex_color[1], 16) * 17
                                b = int(hex_color[2], 16) * 17
                                color_rgba = (r, g, b, 255)
                            else:
                                # 如果长度不符合预期，检查是否是 Android 系统资源 ID 被错误返回
                                # 例如 #0106000c 这种，实际上不是真正的颜色
                                app_logger.warning(f"  警告: 颜色字符串长度不符合预期: {color_str}")
                                color_rgba = (0, 0, 0, 255)
                        except ValueError:
                            color_rgba = (0, 0, 0, 255)
                    else:
                        color_map = {
                            'black': (0, 0, 0, 255), 'white': (255, 255, 255, 255),
                            'red': (255, 0, 0, 255), 'green': (0, 255, 0, 255),
                            'blue': (0, 0, 255, 255), 'yellow': (255, 255, 0, 255),
                            'cyan': (0, 255, 255, 255), 'magenta': (255, 0, 255, 255),
                            'transparent': (0, 0, 0, 0),
                        }
                        if color_str.lower() in color_map:
                            color_rgba = color_map[color_str.lower()]
                        else:
                            color_rgba = (0, 0, 0, 255)
                
                # 如果提供了 alpha 参数，应用透明度
                result = color_rgba
                if alpha is not None:
                    # 确保 alpha 值在 0.0-1.0 范围内
                    safe_alpha = max(0.0, min(1.0, alpha))
                    r, g, b, a = color_rgba
                    new_a = int(a * safe_alpha)
                    # 确保 new_a 在 0-255 范围内
                    new_a = max(0, min(255, new_a))
                    result = (r, g, b, new_a)
                    app_logger.debug(f"  parse_color 应用 alpha: {color_rgba} * {safe_alpha} = {result}")
                
                app_logger.debug(f"  parse_color 结果: {result}")
                return result
            
            def parse_alpha(alpha_str):
                """
                解析透明度值，支持数值和资源ID
                返回 0.0 到 1.0 之间的浮点数
                """
                app_logger.debug(f"  parse_alpha 输入: {alpha_str}")
                if not alpha_str:
                    app_logger.debug(f"  parse_alpha 结果: None (空输入)")
                    return None
                
                alpha_str = alpha_str.strip()
                # 首先尝试解析透明度资源ID
                if alpha_str.startswith('@'):
                    # 解析资源ID
                    res_id = XmlIconParser.parse_resource_id(alpha_str)
                    if res_id:
                        # 尝试通过资源ID获取透明度值
                        alpha_value = self.get_float_resource_value(res_id)
                        if alpha_value is not None:
                            app_logger.debug(f"  parse_alpha 从资源解析: {alpha_value}")
                            return alpha_value
                    # 如果无法解析资源ID，返回默认完全不透明
                    app_logger.warning(f"  parse_alpha 结果: 1.0 (无法解析资源，默认完全不透明)")
                    return 1.0
                elif alpha_str.startswith('?'):
                    # 处理?attr/类型的资源，暂时返回默认完全不透明
                    app_logger.warning(f"  parse_alpha 结果: 1.0 (?attr 类型，默认完全不透明)")
                    return 1.0
                else:
                    # 尝试直接解析为浮点数
                    try:
                        alpha_val = float(alpha_str)
                        # 确保在 0.0-1.0 范围内
                        result = max(0.0, min(1.0, alpha_val))
                        app_logger.debug(f"  parse_alpha 结果: {result} (直接解析)")
                        return result
                    except ValueError:
                        app_logger.warning(f"  parse_alpha 结果: 1.0 (解析失败，默认完全不透明)")
                        return 1.0
            
            def parse_path_data(path_data):
                if not path_data:
                    return []
                commands = []
                pattern = r'([MmLlHhVvCcSsQqTtAaZz])([^MmLlHhVvCcSsQqTtAaZz]*)'
                matches = re.findall(pattern, path_data)
                for cmd, params_str in matches:
                    params_str = params_str.strip()
                    if params_str:
                        params = re.split(r'[,\s]+', params_str)
                        params = [float(p) for p in params if p]
                    else:
                        params = []
                    commands.append((cmd, params))
                return commands
            
            def cubic_bezier_points(x0, y0, x1, y1, x2, y2, x3, y3, num_points=20):
                points = []
                for i in range(num_points + 1):
                    t = i / num_points
                    t2, t3 = t * t, t * t * t
                    mt = 1 - t
                    mt2, mt3 = mt * mt, mt * mt * mt
                    x = mt3 * x0 + 3 * mt2 * t * x1 + 3 * mt * t2 * x2 + t3 * x3
                    y = mt3 * y0 + 3 * mt2 * t * y1 + 3 * mt * t2 * y2 + t3 * y3
                    points.append((x, y))
                return points
            
            def create_linear_gradient(width, height, start_x, start_y, end_x, end_y, items, viewport_width=None, viewport_height=None):
                """
                创建线性渐变图像
                
                与Android官方LinearGradient实现保持一致。
                渐变坐标在viewport坐标系中定义。
                
                Args:
                    width: 图像宽度
                    height: 图像高度
                    start_x: 渐变起始X坐标（viewport坐标系）
                    start_y: 渐变起始Y坐标
                    end_x: 渐变结束X坐标
                    end_y: 渐变结束Y坐标
                    items: 渐变项列表，每个项包含 'color' 和 'offset'
                    viewport_width: viewport宽度（可选）
                    viewport_height: viewport高度（可选）
                
                Returns:
                    PIL Image 对象
                """
                # Android官方：渐变坐标在viewport坐标系中
                # 如果提供了viewport尺寸，将坐标归一化到0-1范围
                if viewport_width is not None and viewport_height is not None and viewport_width > 0 and viewport_height > 0:
                    norm_start_x = start_x / viewport_width
                    norm_start_y = start_y / viewport_height
                    norm_end_x = end_x / viewport_width
                    norm_end_y = end_y / viewport_height
                else:
                    # 判断坐标是否是归一化的（都在0.0-1.0范围内）
                    is_normalized = (
                        0.0 <= start_x <= 1.0 and 
                        0.0 <= start_y <= 1.0 and 
                        0.0 <= end_x <= 1.0 and 
                        0.0 <= end_y <= 1.0
                    )
                    
                    if is_normalized:
                        norm_start_x = start_x
                        norm_start_y = start_y
                        norm_end_x = end_x
                        norm_end_y = end_y
                    else:
                        # 如果不是归一化坐标，使用坐标的最大值来归一化
                        max_coord = max(abs(start_x), abs(start_y), abs(end_x), abs(end_y), 1.0)
                        norm_start_x = start_x / max_coord
                        norm_start_y = start_y / max_coord
                        norm_end_x = end_x / max_coord
                        norm_end_y = end_y / max_coord
                        # 确保在 0.0-1.0 范围内
                        norm_start_x = max(0.0, min(1.0, norm_start_x))
                        norm_start_y = max(0.0, min(1.0, norm_start_y))
                        norm_end_x = max(0.0, min(1.0, norm_end_x))
                        norm_end_y = max(0.0, min(1.0, norm_end_y))
                
                # 将归一化坐标转换为像素坐标
                x0 = int(norm_start_x * width)
                y0 = int(norm_start_y * height)
                x1 = int(norm_end_x * width)
                y1 = int(norm_end_y * height)
                
                # 解析所有 item 的颜色和 offset
                color_stops = []
                for item in items:
                    color_str = item['color']
                    offset = item['offset']
                    
                    # 解析颜色
                    rgba = parse_color(color_str)
                    if isinstance(rgba, tuple):
                        if offset is None:
                            # 如果没有 offset，自动分配
                            if len(color_stops) == 0:
                                offset = 0.0
                            elif len(color_stops) == len(items) - 1:
                                offset = 1.0
                            else:
                                offset = (len(color_stops) + 1) / (len(items))
                        color_stops.append((offset, rgba))
                
                # 确保至少有两个颜色停止
                if len(color_stops) == 0:
                    color_stops = [(0.0, (0, 0, 0, 255)), (1.0, (255, 255, 255, 255))]
                elif len(color_stops) == 1:
                    color_stops.append((1.0, color_stops[0][1]))
                
                # 按 offset 排序
                color_stops.sort(key=lambda x: x[0])
                
                # 创建图像
                img = Image.new('RGBA', (width, height))
                pixels = img.load()
                
                # 计算渐变方向向量
                dx = x1 - x0
                dy = y1 - y0
                len_sq = dx * dx + dy * dy
                
                # 如果渐变是一个点，使用第一个颜色
                if len_sq == 0:
                    r, g, b, a = color_stops[0][1]
                    for y in range(height):
                        for x in range(width):
                            pixels[x, y] = (r, g, b, a)
                    return img
                
                # 遍历每个像素计算颜色
                for y in range(height):
                    for x in range(width):
                        # 计算该点在渐变方向上的投影比例
                        t = ((x - x0) * dx + (y - y0) * dy) / len_sq
                        t = max(0.0, min(1.0, t))
                        
                        # 找到 t 所在的颜色区间
                        r, g, b, a = 0, 0, 0, 0
                        for i in range(len(color_stops) - 1):
                            t0, (r0, g0, b0, a0) = color_stops[i]
                            t1, (r1, g1, b1, a1) = color_stops[i + 1]
                            if t0 <= t <= t1:
                                # 插值
                                if t1 == t0:
                                    frac = 0.0
                                else:
                                    frac = (t - t0) / (t1 - t0)
                                r = int(r0 + frac * (r1 - r0))
                                g = int(g0 + frac * (g1 - g0))
                                b = int(b0 + frac * (b1 - b0))
                                a = int(a0 + frac * (a1 - a0))
                                break
                        else:
                            # 如果没找到，使用最后一个颜色
                            r, g, b, a = color_stops[-1][1]
                        
                        pixels[x, y] = (r, g, b, a)
                
                return img
            
            def create_radial_gradient(width, height, center_x, center_y, radius, items, tile_mode='clamp', viewport_width=None, viewport_height=None):
                """
                创建径向渐变图像。
                
                与Android官方RadialGradient实现保持一致。
                渐变坐标在viewport坐标系中定义。
                
                Args:
                    width: 图像宽度
                    height: 图像高度
                    center_x: 渐变中心X坐标（viewport坐标系）
                    center_y: 渐变中心Y坐标
                    radius: 渐变半径
                    items: 渐变项列表，每个项包含 'color' 和 'offset'
                    tile_mode: 平铺模式 ('clamp', 'repeat', 'mirror')
                    viewport_width: viewport宽度（可选）
                    viewport_height: viewport高度（可选）
                
                Returns:
                    PIL Image 对象
                """
                # Android官方：渐变坐标在viewport坐标系中
                if viewport_width is not None and viewport_height is not None and viewport_width > 0 and viewport_height > 0:
                    norm_center_x = center_x / viewport_width
                    norm_center_y = center_y / viewport_height
                    max_viewport_dim = max(viewport_width, viewport_height)
                    norm_radius = radius / max_viewport_dim if max_viewport_dim > 0 else 0.5
                else:
                    # 判断坐标是否是归一化的
                    is_normalized = (0.0 <= center_x <= 1.0 and 0.0 <= center_y <= 1.0 and 0.0 <= radius <= 1.0)
                    
                    if is_normalized:
                        norm_center_x = center_x
                        norm_center_y = center_y
                        norm_radius = radius
                    else:
                        # 如果不是归一化坐标，使用坐标的最大值来归一化
                        max_coord = max(abs(center_x), abs(center_y), abs(radius), 1.0)
                        norm_center_x = center_x / max_coord
                        norm_center_y = center_y / max_coord
                        norm_radius = radius / max_coord
                        # 确保在 0.0-1.0 范围内
                        norm_center_x = max(0.0, min(1.0, norm_center_x))
                        norm_center_y = max(0.0, min(1.0, norm_center_y))
                        norm_radius = max(0.0, min(1.0, norm_radius))
                
                cx = int(norm_center_x * width)
                cy = int(norm_center_y * height)
                r = int(norm_radius * min(width, height))
                
                color_stops = []
                for item in items:
                    color_str = item['color']
                    offset = item['offset']
                    rgba = parse_color(color_str)
                    if isinstance(rgba, tuple):
                        if offset is None:
                            if len(color_stops) == 0:
                                offset = 0.0
                            elif len(color_stops) == len(items) - 1:
                                offset = 1.0
                            else:
                                offset = (len(color_stops) + 1) / len(items)
                        color_stops.append((offset, rgba))
                
                if len(color_stops) == 0:
                    color_stops = [(0.0, (0, 0, 0, 255)), (1.0, (255, 255, 255, 255))]
                elif len(color_stops) == 1:
                    color_stops.append((1.0, color_stops[0][1]))
                
                color_stops.sort(key=lambda x: x[0])
                
                img = Image.new('RGBA', (width, height))
                pixels = img.load()
                
                for y in range(height):
                    for x in range(width):
                        dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
                        t = dist / r if r > 0 else 0
                        
                        if tile_mode == 'clamp':
                            t = max(0.0, min(1.0, t))
                        elif tile_mode == 'repeat':
                            t = t % 1.0
                        elif tile_mode == 'mirror':
                            t = t % 2.0
                            if t > 1.0:
                                t = 2.0 - t
                        
                        r_val, g_val, b_val, a_val = 0, 0, 0, 0
                        for i in range(len(color_stops) - 1):
                            t0, (r0, g0, b0, a0) = color_stops[i]
                            t1, (r1, g1, b1, a1) = color_stops[i + 1]
                            if t0 <= t <= t1:
                                if t1 == t0:
                                    frac = 0.0
                                else:
                                    frac = (t - t0) / (t1 - t0)
                                r_val = int(r0 + frac * (r1 - r0))
                                g_val = int(g0 + frac * (g1 - g0))
                                b_val = int(b0 + frac * (b1 - b0))
                                a_val = int(a0 + frac * (a1 - a0))
                                break
                        else:
                            r_val, g_val, b_val, a_val = color_stops[-1][1]
                        
                        pixels[x, y] = (r_val, g_val, b_val, a_val)
                
                return img
            
            def create_sweep_gradient(width, height, center_x, center_y, items, viewport_width=None, viewport_height=None):
                """
                创建扫描渐变（角度渐变）图像。
                
                与Android官方SweepGradient实现保持一致。
                扫描渐变从中心点向外辐射，颜色随角度变化。
                渐变坐标在viewport坐标系中定义。
                
                Args:
                    width: 图像宽度
                    height: 图像高度
                    center_x: 渐变中心X坐标（viewport坐标系）
                    center_y: 渐变中心Y坐标
                    items: 渐变项列表，每个项包含 'color' 和 'offset'
                    viewport_width: viewport宽度（可选）
                    viewport_height: viewport高度（可选）
                
                Returns:
                    PIL Image 对象
                """
                # Android官方：渐变坐标在viewport坐标系中
                if viewport_width is not None and viewport_height is not None and viewport_width > 0 and viewport_height > 0:
                    norm_center_x = center_x / viewport_width
                    norm_center_y = center_y / viewport_height
                else:
                    # 判断坐标是否是归一化的
                    is_normalized = (0.0 <= center_x <= 1.0 and 0.0 <= center_y <= 1.0)
                    
                    if is_normalized:
                        norm_center_x = center_x
                        norm_center_y = center_y
                    else:
                        # 如果不是归一化坐标，使用坐标的最大值来归一化
                        max_coord = max(abs(center_x), abs(center_y), 1.0)
                        norm_center_x = center_x / max_coord
                        norm_center_y = center_y / max_coord
                        # 确保在 0.0-1.0 范围内
                        norm_center_x = max(0.0, min(1.0, norm_center_x))
                        norm_center_y = max(0.0, min(1.0, norm_center_y))
                
                cx = int(norm_center_x * width)
                cy = int(norm_center_y * height)
                
                color_stops = []
                for item in items:
                    color_str = item['color']
                    offset = item['offset']
                    rgba = parse_color(color_str)
                    if isinstance(rgba, tuple):
                        if offset is None:
                            if len(color_stops) == 0:
                                offset = 0.0
                            elif len(color_stops) == len(items) - 1:
                                offset = 1.0
                            else:
                                offset = (len(color_stops) + 1) / len(items)
                        color_stops.append((offset, rgba))
                
                if len(color_stops) == 0:
                    color_stops = [(0.0, (0, 0, 0, 255)), (1.0, (255, 255, 255, 255))]
                elif len(color_stops) == 1:
                    color_stops.append((1.0, color_stops[0][1]))
                
                color_stops.sort(key=lambda x: x[0])
                
                img = Image.new('RGBA', (width, height))
                pixels = img.load()
                
                for y in range(height):
                    for x in range(width):
                        dx = x - cx
                        dy = y - cy
                        angle = math.atan2(dy, dx)
                        t = (angle + math.pi) / (2 * math.pi)
                        
                        r_val, g_val, b_val, a_val = 0, 0, 0, 0
                        for i in range(len(color_stops) - 1):
                            t0, (r0, g0, b0, a0) = color_stops[i]
                            t1, (r1, g1, b1, a1) = color_stops[i + 1]
                            if t0 <= t <= t1:
                                if t1 == t0:
                                    frac = 0.0
                                else:
                                    frac = (t - t0) / (t1 - t0)
                                r_val = int(r0 + frac * (r1 - r0))
                                g_val = int(g0 + frac * (g1 - g0))
                                b_val = int(b0 + frac * (b1 - b0))
                                a_val = int(a0 + frac * (a1 - a0))
                                break
                        else:
                            r_val, g_val, b_val, a_val = color_stops[-1][1]
                        
                        pixels[x, y] = (r_val, g_val, b_val, a_val)
                
                return img
            
            def quadratic_bezier_points(x0, y0, x1, y1, x2, y2, num_points=20):
                points = []
                for i in range(num_points + 1):
                    t = i / num_points
                    mt = 1 - t
                    x = mt * mt * x0 + 2 * mt * t * x1 + t * t * x2
                    y = mt * mt * y0 + 2 * mt * t * y1 + t * t * y2
                    points.append((x, y))
                return points
            
            def render_arc_arcpoints(points, current_x, current_y, rx, ry, x_axis_rotation, large_arc_flag, sweep_flag, x, y):
                if rx == 0 or ry == 0:
                    points.append((x, y))
                    return
                rx, ry = abs(rx), abs(ry)
                cos_phi, sin_phi = math.cos(x_axis_rotation), math.sin(x_axis_rotation)
                dx, dy = (current_x - x) / 2, (current_y - y) / 2
                x1p = cos_phi * dx + sin_phi * dy
                y1p = -sin_phi * dx + cos_phi * dy
                rxp_sq = x1p * x1p / (rx * rx) if rx > 0 else 0
                ryp_sq = y1p * y1p / (ry * ry) if ry > 0 else 0
                lambda_sq = rxp_sq + ryp_sq
                if lambda_sq > 1:
                    lambda_val = math.sqrt(lambda_sq)
                    rx *= lambda_val
                    ry *= lambda_val
                sq = max(0, (rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p))
                denom = (rx * rx * y1p * y1p + ry * ry * x1p * x1p)
                if denom > 0:
                    sq /= denom
                coef = math.sqrt(sq)
                if large_arc_flag == sweep_flag:
                    coef = -coef
                cxp = coef * rx * y1p / ry if ry > 0 else 0
                cyp = coef * -ry * x1p / rx if rx > 0 else 0
                cx = cos_phi * cxp - sin_phi * cyp + (current_x + x) / 2
                cy = sin_phi * cxp + cos_phi * cyp + (current_y + y) / 2
                
                def angle_between(ux, uy, vx, vy):
                    n = math.sqrt(ux * ux + uy * uy) * math.sqrt(vx * vx + vy * vy)
                    if n == 0:
                        return 0
                    c = max(-1, min(1, (ux * vx + uy * vy) / n))
                    a = math.acos(c)
                    return -a if ux * vy - uy * vx < 0 else a
                
                theta1 = angle_between(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry) if rx > 0 and ry > 0 else 0
                dtheta = angle_between((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry) if rx > 0 and ry > 0 else 0
                
                # SVG规范：sweep_flag=1表示顺时针（角度减少），sweep_flag=0表示逆时针（角度增加）
                # 修正：顺时针方向角度应该为负，逆时针方向角度应该为正
                if sweep_flag:
                    # 顺时针：角度应该为负
                    if dtheta > 0:
                        dtheta -= 2 * math.pi
                else:
                    # 逆时针：角度应该为正
                    if dtheta < 0:
                        dtheta += 2 * math.pi
                
                num_segments = max(1, int(abs(dtheta) / (math.pi / 8)))
                for i in range(num_segments + 1):
                    t = theta1 + dtheta * i / num_segments
                    px, py = rx * math.cos(t), ry * math.sin(t)
                    points.append((cos_phi * px - sin_phi * py + cx, sin_phi * px + cos_phi * py + cy))
            
            def apply_transform(x, y, transform):
                """
                应用变换到坐标点。
                
                与Android官方实现保持一致。
                变换顺序：先平移到pivot点，然后缩放，然后旋转，然后平移回来，最后平移。
                即：translate(pivot) -> scale -> rotate -> translate(-pivot) -> translate(offset)
                
                Args:
                    x, y: 原始坐标
                    transform: 变换字典，包含translateX, translateY, scaleX, scaleY, rotation, pivotX, pivotY
                
                Returns:
                    (x, y): 变换后的坐标
                """
                tx = transform.get('translateX', 0)
                ty = transform.get('translateY', 0)
                sx = transform.get('scaleX', 1)
                sy = transform.get('scaleY', 1)
                rotation = transform.get('rotation', 0)
                pivot_x = transform.get('pivotX', 0)
                pivot_y = transform.get('pivotY', 0)
                
                # 1. 平移到pivot点
                x_pivot = x - pivot_x
                y_pivot = y - pivot_y
                
                # 2. 缩放
                x_scaled = x_pivot * sx
                y_scaled = y_pivot * sy
                
                # 3. 旋转
                if rotation != 0:
                    rad = math.radians(rotation)
                    cos_r = math.cos(rad)
                    sin_r = math.sin(rad)
                    x_rotated = x_scaled * cos_r - y_scaled * sin_r
                    y_rotated = x_scaled * sin_r + y_scaled * cos_r
                else:
                    x_rotated = x_scaled
                    y_rotated = y_scaled
                
                # 4. 平移回来并应用偏移
                x_final = x_rotated + pivot_x + tx
                y_final = y_rotated + pivot_y + ty
                
                return x_final, y_final
            
            def apply_tint(color, tint_color, tint_mode='src_in'):
                """
                应用 tint 着色到颜色上。
                
                Args:
                    color: 原始颜色 (r, g, b, a) 元组
                    tint_color: 着色颜色 (r, g, b, a) 元组
                    tint_mode: 着色模式，支持 src_in, src_over, src_atop, multiply, screen, add
                
                Returns:
                    着色后的颜色 (r, g, b, a) 元组
                """
                if not tint_color or tint_color[3] == 0:
                    return color
                if not color:
                    return tint_color
                
                r, g, b, a = color
                tr, tg, tb, ta = tint_color
                
                mode = tint_mode.lower() if isinstance(tint_mode, str) else 'src_in'
                
                if mode == 'src_in':
                    # src_in: 只保留 tint 颜色，使用原始 alpha
                    return (tr, tg, tb, a)
                elif mode == 'src_over':
                    # src_over: tint 覆盖在原始颜色上
                    if ta == 255:
                        return (tr, tg, tb, a)
                    out_a = a + ta * (255 - a) / 255
                    if out_a == 0:
                        return (0, 0, 0, 0)
                    out_r = int((r * (255 - ta) + tr * ta) / 255)
                    out_g = int((g * (255 - ta) + tg * ta) / 255)
                    out_b = int((b * (255 - ta) + tb * ta) / 255)
                    return (out_r, out_g, out_b, int(out_a))
                elif mode == 'src_atop':
                    # src_atop: 只在原始颜色不透明的地方显示 tint
                    if a == 0:
                        return (r, g, b, a)
                    return (tr, tg, tb, a)
                elif mode == 'multiply':
                    # multiply: 颜色相乘
                    return (int(r * tr / 255), int(g * tg / 255), int(b * tb / 255), a)
                elif mode == 'screen':
                    # screen: 屏幕混合
                    out_r = int(255 - (255 - r) * (255 - tr) / 255)
                    out_g = int(255 - (255 - g) * (255 - tg) / 255)
                    out_b = int(255 - (255 - b) * (255 - tb) / 255)
                    return (out_r, out_g, out_b, a)
                elif mode == 'add':
                    # add: 颜色相加
                    out_r = min(255, r + tr)
                    out_g = min(255, g + tg)
                    out_b = min(255, b + tb)
                    return (out_r, out_g, out_b, a)
                else:
                    # 默认使用 src_in
                    return (tr, tg, tb, a)
            
            def apply_tint_to_image(img, tint_color, tint_mode='src_in'):
                """
                对整个图像应用 tint 着色。
                
                Args:
                    img: PIL RGBA 图像
                    tint_color: 着色颜色 (r, g, b, a) 元组
                    tint_mode: 着色模式
                
                Returns:
                    着色后的图像
                """
                if not tint_color or tint_color[3] == 0:
                    return img
                
                pixels = img.load()
                width, height = img.size
                for y in range(height):
                    for x in range(width):
                        pixel = pixels[x, y]
                        new_color = apply_tint(pixel, tint_color, tint_mode)
                        pixels[x, y] = new_color
                return img
            
            def draw_stroke_with_caps(draw, subpath, stroke_color, stroke_width_px, stroke_line_cap, stroke_line_join, stroke_miter_limit=4):
                """
                绘制带有线帽样式的描边。
                
                与Android官方Paint实现保持一致。
                PIL的line函数只支持round joint，需要手动处理其他样式。
                
                Args:
                    draw: ImageDraw 对象
                    subpath: 子路径点列表
                    stroke_color: 描边颜色
                    stroke_width_px: 描边宽度（像素）
                    stroke_line_cap: 线帽样式 ('butt', 'round', 'square')
                    stroke_line_join: 连接样式 ('miter', 'round', 'bevel')
                    stroke_miter_limit: 斜接限制（默认4），当join为miter时使用
                """
                if len(subpath) < 2:
                    return
                
                # PIL 的 joint 参数只支持 'round' 或 None
                # 根据 stroke_line_join 决定是否使用 round joint
                # 注意：PIL不直接支持miter和bevel，需要特殊处理
                joint = 'round' if stroke_line_join == 'round' else None
                
                # 对于miter join，我们需要计算并可能切换到bevel
                # 当夹角太小导致miter超过限制时
                use_miter = (stroke_line_join == 'miter')
                use_bevel = (stroke_line_join == 'bevel')
                
                # 绘制主线
                draw.line(subpath, fill=stroke_color, width=stroke_width_px, joint=joint)
                
                # 处理线帽样式
                if stroke_line_cap == 'round':
                    # 在端点绘制圆形
                    if subpath:
                        r = stroke_width_px / 2
                        for pt in [subpath[0], subpath[-1]]:
                            draw.ellipse([pt[0] - r, pt[1] - r, pt[0] + r, pt[1] + r], fill=stroke_color)
                elif stroke_line_cap == 'square':
                    # 在端点绘制方形（延伸半个线宽）
                    if len(subpath) >= 2:
                        r = stroke_width_px / 2
                        # 起点
                        p0, p1 = subpath[0], subpath[1]
                        dx = p0[0] - p1[0]
                        dy = p0[1] - p1[1]
                        length = math.sqrt(dx * dx + dy * dy)
                        if length > 0:
                            dx, dy = dx / length * r, dy / length * r
                            draw.rectangle([p0[0] - r, p0[1] - r, p0[0] + dx + r, p0[1] + dy + r], fill=stroke_color)
                        # 终点
                        p0, p1 = subpath[-1], subpath[-2]
                        dx = p0[0] - p1[0]
                        dy = p0[1] - p1[1]
                        length = math.sqrt(dx * dx + dy * dy)
                        if length > 0:
                            dx, dy = dx / length * r, dy / length * r
                            draw.rectangle([p0[0] - r, p0[1] - r, p0[0] + dx + r, p0[1] + dy + r], fill=stroke_color)
                # 'butt' 是默认行为，不需要额外处理
                
                # 处理miter limit - 当需要时替换为bevel
                # 注意：这是一个简化实现，真正的miter limit需要复杂的计算
                # 这里我们只在stroke_line_join是'miter'时记录日志
                if use_miter and stroke_miter_limit != 4:
                    app_logger.debug(f"miter limit={stroke_miter_limit}（简化实现，暂不完整支持）")
            
            def render_path(draw, path_data, fill_color, stroke_color, stroke_width, transform, scale_x, scale_y, fill_type=None, base_image=None, stroke_line_cap='butt', stroke_line_join='miter', stroke_miter_limit=4, trim_path_start=0, trim_path_end=1, trim_path_offset=0, viewport_width=None, viewport_height=None):
                """
                渲染路径。
                
                与Android官方实现保持一致。
                
                Args:
                    draw: ImageDraw 对象
                    path_data: 路径数据字符串
                    fill_color: 填充颜色
                    stroke_color: 描边颜色
                    stroke_width: 描边宽度
                    transform: 变换字典
                    scale_x, scale_y: 缩放比例
                    fill_type: 填充规则 ('nonZero' 或 'evenOdd')
                    base_image: 基础图像
                    stroke_line_cap: 线帽样式 ('butt', 'round', 'square')
                    stroke_line_join: 连接样式 ('miter', 'round', 'bevel')
                    stroke_miter_limit: 斜接限制
                    trim_path_start: 路径裁剪起始位置 (0-1)
                    trim_path_end: 路径裁剪结束位置 (0-1)
                    trim_path_offset: 路径裁剪偏移 (0-1)
                    viewport_width: viewport宽度（用于渐变坐标转换）
                    viewport_height: viewport高度（用于渐变坐标转换）
                """
                commands = parse_path_data(path_data)
                
                # 获取图像尺寸
                img_width, img_height = draw.im.size
                
                # 所有子路径 - 每个子路径是一个点列表
                subpaths = []
                current_subpath = []
                current_x, current_y = 0, 0
                start_x, start_y = 0, 0
                last_ctrl_x, last_ctrl_y = 0, 0
                
                for cmd, params in commands:
                    if cmd == 'M':
                        # 新的子路径开始 - 先保存当前子路径
                        if current_subpath:
                            subpaths.append(current_subpath.copy())
                        current_subpath = []
                        # 处理多个 M 命令参数
                        for i in range(0, len(params), 2):
                            current_x, current_y = params[i], params[i + 1]
                            start_x, start_y = current_x, current_y
                            tx, ty = apply_transform(current_x, current_y, transform)
                            current_subpath.append((tx * scale_x, ty * scale_y))
                    elif cmd == 'm':
                        # 新的子路径开始（相对坐标）
                        if current_subpath:
                            subpaths.append(current_subpath.copy())
                        current_subpath = []
                        # 处理多个 m 命令参数
                        for i in range(0, len(params), 2):
                            current_x += params[i]
                            current_y += params[i + 1]
                            start_x, start_y = current_x, current_y
                            tx, ty = apply_transform(current_x, current_y, transform)
                            current_subpath.append((tx * scale_x, ty * scale_y))
                    elif cmd == 'L':
                        for i in range(0, len(params), 2):
                            current_x, current_y = params[i], params[i + 1]
                            tx, ty = apply_transform(current_x, current_y, transform)
                            current_subpath.append((tx * scale_x, ty * scale_y))
                    elif cmd == 'l':
                        for i in range(0, len(params), 2):
                            current_x += params[i]
                            current_y += params[i + 1]
                            tx, ty = apply_transform(current_x, current_y, transform)
                            current_subpath.append((tx * scale_x, ty * scale_y))
                    elif cmd == 'H':
                        for p in params:
                            current_x = p
                            tx, ty = apply_transform(current_x, current_y, transform)
                            current_subpath.append((tx * scale_x, ty * scale_y))
                    elif cmd == 'h':
                        for p in params:
                            current_x += p
                            tx, ty = apply_transform(current_x, current_y, transform)
                            current_subpath.append((tx * scale_x, ty * scale_y))
                    elif cmd == 'V':
                        for p in params:
                            current_y = p
                            tx, ty = apply_transform(current_x, current_y, transform)
                            current_subpath.append((tx * scale_x, ty * scale_y))
                    elif cmd == 'v':
                        for p in params:
                            current_y += p
                            tx, ty = apply_transform(current_x, current_y, transform)
                            current_subpath.append((tx * scale_x, ty * scale_y))
                    elif cmd == 'C':
                        for i in range(0, len(params), 6):
                            bezier_points = cubic_bezier_points(current_x, current_y, params[i], params[i+1], params[i+2], params[i+3], params[i+4], params[i+5])
                            for bx, by in bezier_points:
                                tx, ty = apply_transform(bx, by, transform)
                                current_subpath.append((tx * scale_x, ty * scale_y))
                            current_x, current_y = params[i+4], params[i+5]
                            last_ctrl_x, last_ctrl_y = params[i+2], params[i+3]
                    elif cmd == 'c':
                        for i in range(0, len(params), 6):
                            x1, y1 = current_x + params[i], current_y + params[i+1]
                            x2, y2 = current_x + params[i+2], current_y + params[i+3]
                            x, y = current_x + params[i+4], current_y + params[i+5]
                            bezier_points = cubic_bezier_points(current_x, current_y, x1, y1, x2, y2, x, y)
                            for bx, by in bezier_points:
                                tx, ty = apply_transform(bx, by, transform)
                                current_subpath.append((tx * scale_x, ty * scale_y))
                            current_x, current_y = x, y
                            last_ctrl_x, last_ctrl_y = x2, y2
                    elif cmd == 'S':
                        for i in range(0, len(params), 4):
                            x1, y1 = 2 * current_x - last_ctrl_x, 2 * current_y - last_ctrl_y
                            bezier_points = cubic_bezier_points(current_x, current_y, x1, y1, params[i], params[i+1], params[i+2], params[i+3])
                            for bx, by in bezier_points:
                                tx, ty = apply_transform(bx, by, transform)
                                current_subpath.append((tx * scale_x, ty * scale_y))
                            current_x, current_y = params[i+2], params[i+3]
                            last_ctrl_x, last_ctrl_y = params[i], params[i+1]
                    elif cmd == 's':
                        for i in range(0, len(params), 4):
                            x1, y1 = 2 * current_x - last_ctrl_x, 2 * current_y - last_ctrl_y
                            x2, y2 = current_x + params[i], current_y + params[i+1]
                            x, y = current_x + params[i+2], current_y + params[i+3]
                            bezier_points = cubic_bezier_points(current_x, current_y, x1, y1, x2, y2, x, y)
                            for bx, by in bezier_points:
                                tx, ty = apply_transform(bx, by, transform)
                                current_subpath.append((tx * scale_x, ty * scale_y))
                            current_x, current_y = x, y
                            last_ctrl_x, last_ctrl_y = x2, y2
                    elif cmd == 'Q':
                        for i in range(0, len(params), 4):
                            bezier_points = quadratic_bezier_points(current_x, current_y, params[i], params[i+1], params[i+2], params[i+3])
                            for bx, by in bezier_points:
                                tx, ty = apply_transform(bx, by, transform)
                                current_subpath.append((tx * scale_x, ty * scale_y))
                            current_x, current_y = params[i+2], params[i+3]
                            last_ctrl_x, last_ctrl_y = params[i], params[i+1]
                    elif cmd == 'q':
                        for i in range(0, len(params), 4):
                            x1, y1 = current_x + params[i], current_y + params[i+1]
                            x, y = current_x + params[i+2], current_y + params[i+3]
                            bezier_points = quadratic_bezier_points(current_x, current_y, x1, y1, x, y)
                            for bx, by in bezier_points:
                                tx, ty = apply_transform(bx, by, transform)
                                current_subpath.append((tx * scale_x, ty * scale_y))
                            current_x, current_y = x, y
                            last_ctrl_x, last_ctrl_y = x1, y1
                    elif cmd == 'T':
                        for i in range(0, len(params), 2):
                            x1, y1 = 2 * current_x - last_ctrl_x, 2 * current_y - last_ctrl_y
                            bezier_points = quadratic_bezier_points(current_x, current_y, x1, y1, params[i], params[i+1])
                            for bx, by in bezier_points:
                                tx, ty = apply_transform(bx, by, transform)
                                current_subpath.append((tx * scale_x, ty * scale_y))
                            current_x, current_y = params[i], params[i+1]
                            last_ctrl_x, last_ctrl_y = x1, y1
                    elif cmd == 't':
                        for i in range(0, len(params), 2):
                            x1, y1 = 2 * current_x - last_ctrl_x, 2 * current_y - last_ctrl_y
                            x, y = current_x + params[i], current_y + params[i+1]
                            bezier_points = quadratic_bezier_points(current_x, current_y, x1, y1, x, y)
                            for bx, by in bezier_points:
                                tx, ty = apply_transform(bx, by, transform)
                                current_subpath.append((tx * scale_x, ty * scale_y))
                            current_x, current_y = x, y
                            last_ctrl_x, last_ctrl_y = x1, y1
                    elif cmd == 'A':
                        for i in range(0, len(params), 7):
                            arc_points = []
                            render_arc_arcpoints(arc_points, current_x, current_y, params[i], params[i+1], math.radians(params[i+2]), int(params[i+3]), int(params[i+4]), params[i+5], params[i+6])
                            for px, py in arc_points:
                                tx, ty = apply_transform(px, py, transform)
                                current_subpath.append((tx * scale_x, ty * scale_y))
                            current_x, current_y = params[i+5], params[i+6]
                    elif cmd == 'a':
                        for i in range(0, len(params), 7):
                            x, y = current_x + params[i+5], current_y + params[i+6]
                            arc_points = []
                            render_arc_arcpoints(arc_points, current_x, current_y, params[i], params[i+1], math.radians(params[i+2]), int(params[i+3]), int(params[i+4]), x, y)
                            for px, py in arc_points:
                                tx, ty = apply_transform(px, py, transform)
                                current_subpath.append((tx * scale_x, ty * scale_y))
                            current_x, current_y = x, y
                    elif cmd == 'Z' or cmd == 'z':
                        tx, ty = apply_transform(start_x, start_y, transform)
                        current_subpath.append((tx * scale_x, ty * scale_y))
                        current_x, current_y = start_x, start_y
                
                # 保存最后一个子路径
                if current_subpath:
                    subpaths.append(current_subpath)
                
                # 处理trimPath - Android官方支持
                # trimPathStart: 路径裁剪起始位置 (0-1)
                # trimPathEnd: 路径裁剪结束位置 (0-1)
                # trimPathOffset: 路径裁剪偏移 (0-1)
                if trim_path_start > 0 or trim_path_end < 1 or trim_path_offset != 0:
                    app_logger.debug(f"trimPath参数: start={trim_path_start}, end={trim_path_end}, offset={trim_path_offset}")
                    app_logger.debug(f"注意: trimPath完整实现需要复杂的路径长度计算，当前为简化版本")
                    # 简化实现：如果trimPathStart >= trimPathEnd，不绘制
                    if trim_path_start >= trim_path_end:
                        subpaths = []
                
                def calculate_winding_direction(subpath):
                    """
                    计算子路径的环绕方向
                    
                    Args:
                        subpath: 子路径点列表 [(x, y), ...]
                        
                    Returns:
                        1: 顺时针
                        -1: 逆时针
                        0: 无效路径
                    """
                    if len(subpath) < 3:
                        return 0
                    
                    area = 0.0
                    n = len(subpath)
                    for i in range(n):
                        x1, y1 = subpath[i]
                        x2, y2 = subpath[(i + 1) % n]
                        area += (x1 * y2) - (x2 * y1)
                    
                    if area > 0:
                        return 1  # 顺时针
                    elif area < 0:
                        return -1  # 逆时针
                    else:
                        return 0
                
                def create_nonzero_mask(subpaths, img_width, img_height):
                    """
                    使用 nonZero 规则创建填充遮罩
                    
                    Args:
                        subpaths: 子路径列表
                        img_width, img_height: 图像尺寸
                        
                    Returns:
                        PIL.Image: 遮罩图像（L模式，0=透明，255=不透明）
                    """
                    mask_img = Image.new('L', (img_width, img_height), 0)
                    mask_draw = ImageDraw.Draw(mask_img)
                    
                    if len(subpaths) == 0:
                        return mask_img
                    
                    # 如果只有一个子路径，直接填充
                    if len(subpaths) == 1:
                        if len(subpaths[0]) >= 3:
                            mask_draw.polygon(subpaths[0], fill=255)
                        return mask_img
                    
                    # 多个子路径：先顺时针，后逆时针，确保主体在眼睛前面
                    
                    # 分离顺时针和逆时针
                    clockwise = []
                    counter_clockwise = []
                    for subpath in subpaths:
                        if len(subpath) < 3:
                            continue
                        dir = calculate_winding_direction(subpath)
                        if dir == 1:
                            clockwise.append(subpath)
                        elif dir == -1:
                            counter_clockwise.append(subpath)
                    
                    # 先处理顺时针（主体），用OR
                    result_mask = Image.new('1', (img_width, img_height), 0)
                    for subpath in clockwise:
                        temp_mask = Image.new('1', (img_width, img_height), 0)
                        temp_draw = ImageDraw.Draw(temp_mask)
                        temp_draw.polygon(subpath, fill=1)
                        result_mask = ImageChops.logical_or(result_mask, temp_mask)
                    
                    # 再处理逆时针（眼睛），用XOR
                    for subpath in counter_clockwise:
                        temp_mask = Image.new('1', (img_width, img_height), 0)
                        temp_draw = ImageDraw.Draw(temp_mask)
                        temp_draw.polygon(subpath, fill=1)
                        result_mask = ImageChops.logical_xor(result_mask, temp_mask)
                    
                    return result_mask.convert('L')
                
                # 填充 - 使用更复杂的路径处理
                if fill_color and subpaths:
                    # 检查是不是渐变字典
                    if isinstance(fill_color, dict) and fill_color.get('type') == 'gradient':
                        app_logger.debug(f"  render_path: 检测到渐变填充，开始渲染渐变")
                        # 渲染渐变
                        try:
                            # 获取图像尺寸
                            img_width, img_height = draw.im.size
                            
                            # 根据渐变类型创建不同的渐变图像
                            gradient_type = fill_color.get('gradient_type', 'linear')
                            
                            if gradient_type == 'radial':
                                # 径向渐变
                                center_x = fill_color.get('centerX', 0.5)
                                center_y = fill_color.get('centerY', 0.5)
                                radius = fill_color.get('radius', 0.5)
                                tile_mode = fill_color.get('tile_mode', 'clamp')
                                gradient_img = create_radial_gradient(
                                    img_width, img_height,
                                    center_x, center_y, radius,
                                    fill_color['items'], tile_mode,
                                    viewport_width, viewport_height
                                )
                            elif gradient_type == 'sweep':
                                # 扫描渐变
                                center_x = fill_color.get('centerX', 0.5)
                                center_y = fill_color.get('centerY', 0.5)
                                gradient_img = create_sweep_gradient(
                                    img_width, img_height,
                                    center_x, center_y,
                                    fill_color['items'],
                                    viewport_width, viewport_height
                                )
                            else:
                                # 线性渐变（默认）
                                gradient_img = create_linear_gradient(
                                    img_width, img_height, 
                                    fill_color['startX'], fill_color['startY'], 
                                    fill_color['endX'], fill_color['endY'], 
                                    fill_color['items'],
                                    viewport_width, viewport_height
                                )
                            
                            # 创建 alpha 遮罩（使用 nonZero 规则）
                            mask_img = create_nonzero_mask(subpaths, img_width, img_height)
                            
                            # 将渐变图像通过 mask 应用到 draw 上
                            # 我们需要先把 draw 的图像取出来，然后混合
                            base_img = draw.im
                            
                            # 处理图像模式问题 - 如果 base_img 是调色板模式（P模式），需要特殊处理
                            if base_img.mode == 'P':
                                # 调色板模式，先转换为 RGBA 模式处理
                                base_rgba = base_img.convert('RGBA')
                                # 确保 gradient_img 也是 RGBA
                                if gradient_img.mode != 'RGBA':
                                    gradient_img = gradient_img.convert('RGBA')
                                # 使用 mask 合成
                                base_rgba.paste(gradient_img, (0, 0), mask_img)
                                # 转换回原来的模式并替换
                                base_img.paste(base_rgba, (0, 0))
                            else:
                                # 确保两张图模式一致
                                if gradient_img.mode != base_img.mode:
                                    gradient_img = gradient_img.convert(base_img.mode)
                                # 使用 mask 合成
                                try:
                                    base_img.paste(gradient_img, (0, 0), mask_img)
                                except TypeError:
                                    # 如果失败，尝试不使用 mask 的方式
                                    # 或者使用其他方法
                                    # 创建一个临时图像
                                    temp_img = Image.new(base_img.mode, (img_width, img_height))
                                    temp_draw = ImageDraw.Draw(temp_img)
                                    # 用白色填充 mask 区域
                                    temp_img.paste(gradient_img, (0, 0))
                                    # 然后只在 mask 为白色的地方复制
                                    for y in range(img_height):
                                        for x in range(img_width):
                                            if mask_img.getpixel((x, y)) > 128:
                                                base_img.putpixel((x, y), temp_img.getpixel((x, y)))
                        except Exception as e:
                            app_logger.error(f"  render_path: 渲染渐变失败: {e}")
                            import traceback
                            app_logger.error(traceback.format_exc())
                            # 如果渐变渲染失败，回退到第一个颜色
                            try:
                                first_color = fill_color['items'][0]['color']
                                parsed_color = parse_color(first_color)
                                if isinstance(parsed_color, tuple):
                                    # 创建 nonZero 遮罩
                                    img_width, img_height = draw.im.size
                                    mask_img = create_nonzero_mask(subpaths, img_width, img_height)
                                    # 使用遮罩填充颜色
                                    temp_img = Image.new('RGBA', (img_width, img_height), (0, 0, 0, 0))
                                    temp_draw = ImageDraw.Draw(temp_img)
                                    temp_draw.rectangle((0, 0, img_width, img_height), fill=parsed_color)
                                    # 将结果合成到 draw 上
                                    base_img = draw.im
                                    if base_img.mode == 'P':
                                        base_rgba = base_img.convert('RGBA')
                                        base_rgba.paste(temp_img, (0, 0), mask_img)
                                        base_img.paste(base_rgba, (0, 0))
                                    else:
                                        if temp_img.mode != base_img.mode:
                                            temp_img = temp_img.convert(base_img.mode)
                                        base_img.paste(temp_img, (0, 0), mask_img)
                            except:
                                pass
                    else:
                        # 纯色填充
                        # 解析 fillType 属性
                        # 官方实现：默认值是 nonZero，不自动检测
                        # fillType="0" 或 "nonZero" → 非零环绕规则（默认）
                        # fillType="1" 或 "evenOdd" → 奇偶规则
                        use_even_odd = False
                        if fill_type is not None:
                            fill_type_str = str(fill_type).strip()
                            if fill_type_str == "1" or fill_type_str.lower() == "evenodd":
                                use_even_odd = True
                        
                        if fill_type is not None:
                            app_logger.debug(f"  render_path: 使用填充规则: {'evenOdd' if use_even_odd else 'nonZero'}")
                        
                        # 使用 aggdraw 库来正确实现填充规则（如果可用）
                        # 先计算描边宽度
                        stroke_width_px = max(1, int(stroke_width * min(scale_x, scale_y))) if stroke_color and stroke_width > 0 else 0
                        
                        if use_even_odd and len(subpaths) > 1:
                            # evenOdd 规则：使用 XOR 操作来实现镂空效果
                            
                            # 创建遮罩图像 (使用 '1' 模式，二值图像)
                            mask_img = Image.new('1', (img_width, img_height), 0)
                            
                            # 对每个子路径，使用 XOR 操作
                            for subpath in subpaths:
                                if len(subpath) >= 3:
                                    # 创建临时遮罩 (使用 '1' 模式)
                                    temp_mask = Image.new('1', (img_width, img_height), 0)
                                    temp_mask_draw = ImageDraw.Draw(temp_mask)
                                    temp_mask_draw.polygon(subpath, fill=1)
                                    
                                    # XOR 操作：mask = mask XOR temp_mask
                                    mask_img = ImageChops.logical_xor(mask_img, temp_mask)
                            
                            # 将遮罩转换为 'L' 模式，以便用于 paste
                            mask_img = mask_img.convert('L')
                            
                            # 绘制填充颜色到临时图像
                            temp_img = Image.new('RGBA', (img_width, img_height), (0, 0, 0, 0))
                            temp_draw = ImageDraw.Draw(temp_img)
                            temp_draw.rectangle((0, 0, img_width, img_height), fill=fill_color)
                            
                            # 应用遮罩
                            result_img = Image.new('RGBA', (img_width, img_height), (0, 0, 0, 0))
                            result_img.paste(temp_img, (0, 0), mask_img)
                            
                            # 描边 - 在result_img上画
                            if stroke_color and stroke_width > 0:
                                stroke_width_px = max(1, int(stroke_width * min(scale_x, scale_y)))
                                result_draw = ImageDraw.Draw(result_img)
                                for subpath in subpaths:
                                    if len(subpath) >= 2:
                                        draw_stroke_with_caps(result_draw, subpath, stroke_color, stroke_width_px, stroke_line_cap, stroke_line_join, stroke_miter_limit)
                            
                            # 将结果绘制到主图像上
                            if base_image is not None:
                                combined = Image.alpha_composite(base_image, result_img)
                                # 返回合成后的图像
                                return combined
                            return result_img
                        else:
                            # nonZero 规则
                            # 创建 nonZero 遮罩
                            mask_img = create_nonzero_mask(subpaths, img_width, img_height)
                            
                            # 绘制填充颜色到临时图像
                            temp_img = Image.new('RGBA', (img_width, img_height), (0, 0, 0, 0))
                            temp_draw = ImageDraw.Draw(temp_img)
                            temp_draw.rectangle((0, 0, img_width, img_height), fill=fill_color)
                            
                            # 应用遮罩
                            result_img = Image.new('RGBA', (img_width, img_height), (0, 0, 0, 0))
                            result_img.paste(temp_img, (0, 0), mask_img)
                            
                            # 描边 - 在result_img上画
                            if stroke_color and stroke_width > 0:
                                stroke_width_px = max(1, int(stroke_width * min(scale_x, scale_y)))
                                result_draw = ImageDraw.Draw(result_img)
                                for subpath in subpaths:
                                    if len(subpath) >= 2:
                                        draw_stroke_with_caps(result_draw, subpath, stroke_color, stroke_width_px, stroke_line_cap, stroke_line_join, stroke_miter_limit)
                            
                            # 将结果绘制到主图像上
                            if base_image is not None:
                                combined = Image.alpha_composite(base_image, result_img)
                                return combined
                            return result_img
            
            if size is not None:
                output_width, output_height = size
            else:
                width_dp = parse_dimension(width_str)
                height_dp = parse_dimension(height_str)
                output_width = int(width_dp) * 4    # 输出当前默认分辨率的4倍，更清晰
                output_height = int(height_dp) * 4    # 输出当前默认分辨率的4倍，更清晰
            
            app_logger.debug(f"  输出尺寸: {output_width} x {output_height} 像素")
            
            image = Image.new('RGBA', (output_width, output_height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            
            # 使用字典来存储图像引用，以便在函数内部修改
            image_ref = {'image': image, 'draw': draw}
            
            scale_x = output_width / viewport_width
            scale_y = output_height / viewport_height
            
            element_counts = {'path': 0, 'group': 0, 'rect': 0, 'oval': 0, 'circle': 0, 'line': 0, 'roundrect': 0, 'clip-path': 0}
            
            def process_element(elem, transform, scale_x, scale_y, clip_paths=None):
                """
                处理 XML 元素。
                
                Args:
                    elem: XML 元素
                    transform: 当前变换字典
                    scale_x, scale_y: 缩放比例
                    clip_paths: 裁剪路径列表（用于 clip-path）
                """
                tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                
                if tag in element_counts:
                    element_counts[tag] += 1
                
                if tag == 'group':
                    # Group 变换：每个属性独立设置，不累加
                    # 官方实现中，变换是在 native 层通过矩阵乘法处理的
                    new_transform = transform.copy()
                    # translateX/Y：累加（平移是累积的）
                    translate_x = elem.get(f'{ANDROID_NS}translateX')
                    translate_y = elem.get(f'{ANDROID_NS}translateY')
                    if translate_x:
                        new_transform['translateX'] = transform.get('translateX', 0) + float(translate_x)
                    if translate_y:
                        new_transform['translateY'] = transform.get('translateY', 0) + float(translate_y)
                    # scaleX/Y：累乘（缩放是累积的）
                    scale_x_val = elem.get(f'{ANDROID_NS}scaleX')
                    scale_y_val = elem.get(f'{ANDROID_NS}scaleY')
                    if scale_x_val:
                        new_transform['scaleX'] = transform.get('scaleX', 1) * float(scale_x_val)
                    if scale_y_val:
                        new_transform['scaleY'] = transform.get('scaleY', 1) * float(scale_y_val)
                    # rotation：累加（旋转是累积的）
                    rotation_val = elem.get(f'{ANDROID_NS}rotation')
                    if rotation_val:
                        new_transform['rotation'] = transform.get('rotation', 0) + float(rotation_val)
                    # pivotX/Y：覆盖（pivot 点是相对于当前 group 的，不累加）
                    pivot_x_val = elem.get(f'{ANDROID_NS}pivotX')
                    pivot_y_val = elem.get(f'{ANDROID_NS}pivotY')
                    if pivot_x_val is not None:
                        new_transform['pivotX'] = float(pivot_x_val)
                    if pivot_y_val is not None:
                        new_transform['pivotY'] = float(pivot_y_val)
                    
                    # 收集 group 内的 clip-path
                    group_clip_paths = clip_paths.copy() if clip_paths else []
                    
                    for child in elem:
                        process_element(child, new_transform, scale_x, scale_y, group_clip_paths)
                
                elif tag == 'clip-path':
                    # 裁剪路径：只影响当前 group 及其子元素
                    path_data = elem.get(f'{ANDROID_NS}pathData')
                    if path_data:
                        clip_path_info = {
                            'pathData': path_data,
                            'transform': transform.copy()
                        }
                        if clip_paths is not None:
                            clip_paths.append(clip_path_info)
                        app_logger.debug(f"添加 clip-path")
                
                elif tag == 'path':
                    path_data = elem.get(f'{ANDROID_NS}pathData')
                    # 解析 fillType 属性
                    fill_type = elem.get(f'{ANDROID_NS}fillType')
                    if fill_type:
                        app_logger.debug(f"path fillType: {fill_type}")
                    # 解析 fillAlpha 属性
                    fill_alpha_str = elem.get(f'{ANDROID_NS}fillAlpha')
                    fill_alpha = parse_alpha(fill_alpha_str)
                    # 解析颜色，应用 fillAlpha
                    fill_color = parse_color(elem.get(f'{ANDROID_NS}fillColor'), fill_alpha)
                    # 解析 stroke 相关属性，包括 strokeAlpha
                    stroke_color_str = elem.get(f'{ANDROID_NS}strokeColor')
                    stroke_alpha_str = elem.get(f'{ANDROID_NS}strokeAlpha')
                    stroke_alpha = parse_alpha(stroke_alpha_str)
                    stroke_color = parse_color(stroke_color_str, stroke_alpha) if stroke_color_str else None
                    stroke_width = float(elem.get(f'{ANDROID_NS}strokeWidth', '0'))
                    
                    # 解析描边样式属性
                    stroke_line_cap = elem.get(f'{ANDROID_NS}strokeLineCap', 'butt')
                    stroke_line_join = elem.get(f'{ANDROID_NS}strokeLineJoin', 'miter')
                    stroke_miter_limit = float(elem.get(f'{ANDROID_NS}strokeMiterLimit', '4'))
                    
                    # 解析 trimPath 属性
                    trim_path_start = float(elem.get(f'{ANDROID_NS}trimPathStart', '0'))
                    trim_path_end = float(elem.get(f'{ANDROID_NS}trimPathEnd', '1'))
                    trim_path_offset = float(elem.get(f'{ANDROID_NS}trimPathOffset', '0'))
                    
                    if path_data:
                        result = render_path(image_ref['draw'], path_data, fill_color, stroke_color, stroke_width, transform, scale_x, scale_y, fill_type, image_ref['image'], stroke_line_cap, stroke_line_join, stroke_miter_limit, trim_path_start, trim_path_end, trim_path_offset, viewport_width, viewport_height)
                        if result is not None:
                            # 更新图像引用
                            image_ref['image'] = result
                            image_ref['draw'] = ImageDraw.Draw(image_ref['image'])
                
                elif tag == 'rect':
                    left, top = float(elem.get(f'{ANDROID_NS}left', '0')), float(elem.get(f'{ANDROID_NS}top', '0'))
                    right, bottom = float(elem.get(f'{ANDROID_NS}right', '0')), float(elem.get(f'{ANDROID_NS}bottom', '0'))
                    fill_color = parse_color(elem.get(f'{ANDROID_NS}color') or elem.get(f'{ANDROID_NS}fillColor'))
                    pts = [(left, top), (right, top), (right, bottom), (left, bottom)]
                    transformed = [apply_transform(x, y, transform) for x, y in pts]
                    transformed_pts = [(tx * scale_x, ty * scale_y) for tx, ty in transformed]
                    
                    def do_draw(d):
                        d.polygon(transformed_pts, fill=fill_color)
                    image_ref['image'] = draw_with_alpha(image_ref['image'], do_draw)
                    image_ref['draw'] = ImageDraw.Draw(image_ref['image'])
                
                elif tag == 'oval':
                    left, top = float(elem.get(f'{ANDROID_NS}left', '0')), float(elem.get(f'{ANDROID_NS}top', '0'))
                    right, bottom = float(elem.get(f'{ANDROID_NS}right', '0')), float(elem.get(f'{ANDROID_NS}bottom', '0'))
                    fill_color = parse_color(elem.get(f'{ANDROID_NS}color') or elem.get(f'{ANDROID_NS}fillColor'))
                    cx, cy = (left + right) / 2, (top + bottom) / 2
                    rx, ry = (right - left) / 2, (bottom - top) / 2
                    pts = []
                    for i in range(37):
                        angle = 2 * math.pi * i / 36
                        tx, ty = apply_transform(cx + rx * math.cos(angle), cy + ry * math.sin(angle), transform)
                        pts.append((tx * scale_x, ty * scale_y))
                    
                    def do_draw(d):
                        d.polygon(pts, fill=fill_color)
                    image_ref['image'] = draw_with_alpha(image_ref['image'], do_draw)
                    image_ref['draw'] = ImageDraw.Draw(image_ref['image'])
                
                elif tag == 'circle':
                    cx, cy = float(elem.get(f'{ANDROID_NS}centerX', '0')), float(elem.get(f'{ANDROID_NS}centerY', '0'))
                    radius = float(elem.get(f'{ANDROID_NS}radius', '0'))
                    fill_color = parse_color(elem.get(f'{ANDROID_NS}color') or elem.get(f'{ANDROID_NS}fillColor'))
                    pts = []
                    for i in range(37):
                        angle = 2 * math.pi * i / 36
                        tx, ty = apply_transform(cx + radius * math.cos(angle), cy + radius * math.sin(angle), transform)
                        pts.append((tx * scale_x, ty * scale_y))
                    
                    def do_draw(d):
                        d.polygon(pts, fill=fill_color)
                    image_ref['image'] = draw_with_alpha(image_ref['image'], do_draw)
                    image_ref['draw'] = ImageDraw.Draw(image_ref['image'])
                
                elif tag == 'line':
                    x1, y1 = float(elem.get(f'{ANDROID_NS}x1', '0')), float(elem.get(f'{ANDROID_NS}y1', '0'))
                    x2, y2 = float(elem.get(f'{ANDROID_NS}x2', '0')), float(elem.get(f'{ANDROID_NS}y2', '0'))
                    stroke_color = parse_color(elem.get(f'{ANDROID_NS}strokeColor'))
                    stroke_width = float(elem.get(f'{ANDROID_NS}strokeWidth', '1'))
                    tx1, ty1 = apply_transform(x1, y1, transform)
                    tx2, ty2 = apply_transform(x2, y2, transform)
                    line_pts = [(tx1 * scale_x, ty1 * scale_y), (tx2 * scale_x, ty2 * scale_y)]
                    
                    def do_draw(d):
                        d.line(line_pts, fill=stroke_color, width=max(1, int(stroke_width * scale_x)))
                    image_ref['image'] = draw_with_alpha(image_ref['image'], do_draw)
                    image_ref['draw'] = ImageDraw.Draw(image_ref['image'])
                
                elif tag == 'roundrect':
                    left, top = float(elem.get(f'{ANDROID_NS}left', '0')), float(elem.get(f'{ANDROID_NS}top', '0'))
                    right, bottom = float(elem.get(f'{ANDROID_NS}right', '0')), float(elem.get(f'{ANDROID_NS}bottom', '0'))
                    rx, ry = float(elem.get(f'{ANDROID_NS}rx', '0')), float(elem.get(f'{ANDROID_NS}ry', '0'))
                    fill_color = parse_color(elem.get(f'{ANDROID_NS}color') or elem.get(f'{ANDROID_NS}fillColor'))
                    pts = []
                    for i in range(9):
                        angle = -math.pi / 2 + math.pi / 2 * i / 8
                        tx, ty = apply_transform(right - rx + rx * math.cos(angle), top + ry + ry * math.sin(angle), transform)
                        pts.append((tx * scale_x, ty * scale_y))
                    for i in range(9):
                        angle = math.pi / 2 * i / 8
                        tx, ty = apply_transform(right - rx + rx * math.cos(angle), bottom - ry + ry * math.sin(angle), transform)
                        pts.append((tx * scale_x, ty * scale_y))
                    for i in range(9):
                        angle = math.pi / 2 + math.pi / 2 * i / 8
                        tx, ty = apply_transform(left + rx + rx * math.cos(angle), bottom - ry + ry * math.sin(angle), transform)
                        pts.append((tx * scale_x, ty * scale_y))
                    for i in range(9):
                        angle = math.pi + math.pi / 2 * i / 8
                        tx, ty = apply_transform(left + rx + rx * math.cos(angle), top + ry + ry * math.sin(angle), transform)
                        pts.append((tx * scale_x, ty * scale_y))
                    
                    def do_draw(d):
                        d.polygon(pts, fill=fill_color)
                    image_ref['image'] = draw_with_alpha(image_ref['image'], do_draw)
                    image_ref['draw'] = ImageDraw.Draw(image_ref['image'])
            
            initial_transform = {'translateX': 0, 'translateY': 0, 'scaleX': 1, 'scaleY': 1, 'rotation': 0, 'pivotX': 0, 'pivotY': 0}
            
            for child in xml_obj:
                process_element(child, initial_transform, scale_x, scale_y, [])
            
            elements_info = [f"{k}: {v}" for k, v in element_counts.items() if v > 0]
            app_logger.debug(f"  渲染元素: {', '.join(elements_info)}")
            
            # 应用 tint 着色
            final_image = image_ref['image']
            if tint_color_str:
                tint_color = parse_color(tint_color_str)
                if isinstance(tint_color, tuple) and tint_color[3] > 0:
                    app_logger.debug(f"  应用 tint: {tint_color}, mode: {tint_mode_str}")
                    final_image = apply_tint_to_image(final_image, tint_color, tint_mode_str)
            
            # 应用根 alpha
            if root_alpha < 1.0:
                app_logger.debug(f"  应用 root alpha: {root_alpha}")
                pixels = final_image.load()
                width, height = final_image.size
                for y in range(height):
                    for x in range(width):
                        r, g, b, a = pixels[x, y]
                        pixels[x, y] = (r, g, b, int(a * root_alpha))
            
            # 应用 autoMirrored（RTL镜像）
            # 注意：这里默认不启用镜像，因为需要知道当前布局方向
            # 如果需要RTL版本，可以传入 is_rtl=True 参数
            # auto_mirrored 变量已解析，可供外部使用
            
            output = BytesIO()
            final_image.save(output, format='PNG')
            return output.getvalue()
        
        except Exception as e:
            app_logger.error(f"提取 vector 图标失败: {e}")
            return None
    
    def _apply_rtl_mirror(self, image):
        """
        应用RTL镜像（水平翻转）。
        
        与Android官方autoMirrored属性实现保持一致。
        当布局方向为RTL时，自动水平翻转图标。
        
        Args:
            image: PIL RGBA图像
            
        Returns:
            PIL.Image: 镜像后的图像
        """
        return image.transpose(Image.FLIP_LEFT_RIGHT)

    def get_icon_data(self):
        """
        获取解析后的图标数据。
        
        Returns:
            bytes: PNG格式的图标二进制数据
            None: 未解析或解析失败时返回None
        """
        return self._icon_data

    def get_icon_sure(self):
        """
        获取图标是否确定解析成功。
        
        Returns:
            bool: True表示图标完整解析，False表示部分解析或推测
        """
        return self._icon_sure
    
    def cleanup(self):
        """
        清理资源，释放内存。
        
        清空缓存数据和引用，应在使用完毕后调用。
        特别是清空 arsc_parser 引用，因为它持有大量 androguard 资源数据。
        """
        self.arsc_parser = None
        self.apk_parser = None
        self.zip_file = None
        self._files_list = None
        self._icon_data = None
        self._color_cache.clear()
        self._float_cache.clear()

    @staticmethod
    def parse_resource_id(resource_id_str):
        """
        解析资源ID字符串，返回整数形式的资源ID。
        
        支持多种格式：
        - "@7F0F0001" (普通格式)
        - "@android:0106000B" (带包名前缀的格式)
        
        Args:
            resource_id_str: 资源ID字符串
            
        Returns:
            int: 整数形式的资源ID
            None: 解析失败时返回None
        """
        if not resource_id_str or not resource_id_str.startswith('@'):
            return None
        try:
            # 去除 @ 前缀
            id_part = resource_id_str[1:]
            # 如果包含冒号，取冒号后面的部分
            if ':' in id_part:
                id_part = id_part.split(':', 1)[1]
            # 尝试解析为十六进制整数
            return int(id_part, 16)
        except ValueError:
            return None

    def resolve_resource_id_to_xml_name(self, resource_id):
        """
        将资源ID转换为XML名称。
        
        Args:
            resource_id: 整数形式的资源ID
            
        Returns:
            str: XML名称字符串（如 "@drawable/ic_foreground"）
            None: 转换失败时返回None
        """
        if not self.arsc_parser:
            app_logger.error(f"ARSCParser 未初始化")
            return None
        
        try:
            xml_name = self.arsc_parser.get_resource_xml_name(resource_id)
            return xml_name
        except Exception as e:
            app_logger.error(f"解析资源 ID 失败: {e}")
            return None

    def resolve_resource_to_actual_path(self, layer_info, current_path):
        """
        将资源信息解析为APK中的实际文件路径或资源值。
        
        支持多种资源类型：drawable、mipmap、color等。
        
        Args:
            layer_info: 图层信息字典，包含 xml_name, resource_id, resource_type
            current_path: 当前XML文件路径
            
        Returns:
            tuple: (路径类型, 数据)
                - 路径类型为 'file' 时，数据为文件路径
                - 路径类型为 'color' 时，数据为颜色值
                - 路径类型为 None 时，表示解析失败
        """
        if not layer_info:
            return None, None
        
        xml_name = layer_info.get('xml_name')
        resource_id = layer_info.get('resource_id')
        resource_type = layer_info.get('resource_type')
        
        app_logger.debug(f"  解析资源: xml_name={xml_name}, resource_id={hex(resource_id) if resource_id else None}, type={resource_type}")
        
        # 处理 color 类型资源 - 直接获取颜色值，不查找文件
        if resource_type == 'color':
            color_value = self.get_color_resource_value(resource_id, xml_name)
            if color_value:
                app_logger.debug(f"    颜色解析结果：{color_value}")
                return 'color', color_value
            return None, None
        
        # 处理 drawable/mipmap 类型资源 - 使用统一的查找函数
        if resource_type in ('drawable', 'mipmap'):
            file_path = self.find_resource(
                resource_name=xml_name,
                resource_id=resource_id
            )
            if file_path:
                return 'file', file_path
        
        return None, None

    def get_color_resource_value(self, resource_id, xml_name=None):
        """
        获取color类型资源的颜色值。
        
        使用androguard库的标准方法，支持Android系统资源ID的硬编码映射。
        结果会被缓存以提高性能。
        
        Args:
            resource_id: 资源ID（整数）
            xml_name: XML名称（可选，未使用）
            
        Returns:
            str: 颜色值（如 "#FFFFFFFF" 格式字符串）
            None: 获取失败时返回None
        """
        # 检查缓存
        if resource_id in self._color_cache:
            app_logger.debug(f"输入: {self._format_resource_id(resource_id)} (从缓存读取)")
            return self._color_cache[resource_id]
        
        # 调用实际的解析函数
        result = self._get_color_resource_value_impl(resource_id, xml_name)
        
        # 存入缓存
        self._color_cache[resource_id] = result
        return result
    
    def _get_color_resource_value_impl(self, resource_id, xml_name=None):
        """
        实际的颜色资源解析函数（不带缓存）。
        
        首先检查Android系统颜色资源ID映射，然后尝试从APK的resources.arsc中获取。
        
        Args:
            resource_id: 资源ID（整数）
            xml_name: XML名称（可选，未使用）
            
        Returns:
            str: 颜色值（如 "#FFFFFFFF" 格式字符串）
            None: 获取失败时返回None
        """
        app_logger.debug(f"输入: {self._format_resource_id(resource_id)}")
        
        # Android系统颜色资源ID的硬编码映射
        # 基于Android系统 android.R.color 类的常见资源ID对应关系
        # 注意：不同Android版本的资源ID可能略有不同，这里使用的是常见值
        android_color_map = {
            0x01060000: "#FFAAAAAA",  # 灰色
            0x01060001: "#FFFFFFFF",  # 白色（深色主题主要文本）
            0x01060002: "#FFFFFFFF",  # 白色（深色主题主要文本，不禁用）
            0x01060003: "#FF000000",  # 黑色（浅色主题主要文本）
            0x01060004: "#FF000000",  # 黑色（浅色主题主要文本，不禁用）
            0x01060005: "#FFBEBEBE",  # 浅灰色（深色主题次要文本）
            0x01060006: "#FFBEBEBE",  # 浅灰色（深色主题次要文本，不禁用）
            0x01060007: "#FF323232",  # 深灰色（浅色主题次要文本）
            0x01060008: "#FFBEBEBE",  # 浅灰色（浅色主题次要文本，不禁用）
            0x01060009: "#FF808080",  # 灰色（标签指示器文本）
            0x0106000A: "#FF000000",  # 黑色（深色编辑框）
            0x0106000B: "#FFFFFFFF",  # 白色
            0x0106000C: "#FF000000",  # 黑色
            0x0106000D: "#00000000",  # 透明
            0x0106000E: "#FF000000",  # 黑色（深色背景）
            0x0106000F: "#FFFFFFFF",  # 白色（浅色背景）
            0x01060010: "#FF808080",  # 灰色（深色主题第三级文本）
            0x01060011: "#FF808080",  # 灰色（浅色主题第三级文本）
            0x01060012: "#FF33B5E5",  # Holo蓝色（亮）
            0x01060013: "#FF0099CC",  # Holo蓝色（暗）
            0x01060014: "#FF99CC00",  # Holo绿色（亮）
            0x01060015: "#FF669900",  # Holo绿色（暗）
            0x01060016: "#FFFF4444",  # Holo红色（亮）
            0x01060017: "#FFCC0000",  # Holo红色（暗）
            0x01060018: "#FFFFBB33",  # Holo橙色（亮）
            0x01060019: "#FFFF8800",  # Holo橙色（暗）
            0x0106001A: "#FFAA66CC",  # Holo紫色
            0x0106001B: "#FF00DDFF",  # Holo蓝色（亮）
        }
        
        # 首先检查是否是Android系统资源ID
        if resource_id in android_color_map:
            app_logger.debug(f"命中系统颜色映射 {self._format_resource_id(resource_id)} -> {android_color_map[resource_id]}")
            return android_color_map[resource_id]
        
        # 尝试从APK的resources.arsc中获取
        if self.arsc_parser and resource_id:
            try:
                app_logger.debug(f"尝试从resources.arsc获取 {self._format_resource_id(resource_id)}")
                
                # 获取资源配置和条目
                configs = list(self.arsc_parser.get_res_configs(resource_id))
                
                app_logger.debug(f"configs数量={len(configs)}")
                
                # 先检查这个资源 ID 的资源类型是什么！
                resource_type_id = (resource_id >> 16) & 0xFF
                app_logger.debug(f"资源ID解析: package={self._format_hex((resource_id >> 24) & 0xFF, 2)}, type={self._format_hex(resource_type_id, 2)}, entry={self._format_hex(resource_id & 0xFFFF, 4)}")
                
                if configs:
                    # 使用第一个配置的条目
                    _, entry = configs[0]
                    
                    app_logger.debug(f"解析到资源条目")
                    
                    # 检查 entry 是否有 key 或 item 属性
                    res_value = None
                    if hasattr(entry, 'key'):
                        res_value = entry.key
                    elif hasattr(entry, 'item'):
                        res_value = entry.item
                    
                    if res_value:
                        app_logger.debug(f"解析到资源值")
                        
                        # 检查是否是引用类型
                        if hasattr(res_value, 'is_reference') and res_value.is_reference():
                            ref_res_id = res_value.data
                            app_logger.debug(f"检测到reference类型，递归解析 {self._format_resource_id(ref_res_id)}")
                            return self.get_color_resource_value(ref_res_id, xml_name)
                        
                        # 检查是否有get_data_type方法或者data_type属性
                        res_value_type = None
                        if hasattr(res_value, 'get_data_type'):
                            res_value_type = res_value.get_data_type()
                            app_logger.debug(f"res_value.get_data_type()={res_value_type}")
                        elif hasattr(res_value, 'data_type'):
                            res_value_type = res_value.data_type
                            app_logger.debug(f"res_value.data_type={res_value_type}")
                        
                        if hasattr(res_value, 'get_data_type_string'):
                            res_value_type_str = res_value.get_data_type_string()
                            app_logger.debug(f"res_value.get_data_type_string()={res_value_type_str}")
                        
                        # 获取data属性
                        entry_data = None
                        if hasattr(res_value, 'get_data'):
                            entry_data = res_value.get_data()
                            app_logger.debug(f"res_value.get_data()={entry_data}")
                        elif hasattr(res_value, 'data'):
                            entry_data = res_value.data
                            app_logger.debug(f"res_value.data={entry_data}")
                        
                        # 检查其他方法（仅在需要时获取值）
                        
                        # 检查是否是reference类型（我们刚才可能漏了，因为is_reference可能不是一个方法）
                        if hasattr(res_value, 'is_reference'):
                            # 看看 is_reference 是方法还是属性
                            if callable(res_value.is_reference):
                                if res_value.is_reference():
                                    ref_res_id = res_value.data
                                    app_logger.debug(f"检测到reference类型（方法），递归解析 {self._format_resource_id(ref_res_id)}")
                                    return self.get_color_resource_value(ref_res_id, xml_name)
                            else:
                                if res_value.is_reference:
                                    ref_res_id = res_value.data
                                    app_logger.debug(f"检测到reference类型（属性），递归解析 {self._format_resource_id(ref_res_id)}")
                                    return self.get_color_resource_value(ref_res_id, xml_name)
                    
                    # 尝试从 stringpool 获取字符串值
                    string_value = None
                    try:
                        if hasattr(self.arsc_parser, 'stringpool_main') and self.arsc_parser.stringpool_main:
                            string_pool = self.arsc_parser.stringpool_main
                            if entry_data is not None and hasattr(string_pool, '__getitem__'):
                                string_value = string_pool[entry_data]
                    except Exception as e:
                        pass
                    
                    # 使用 androguard 的 get_resource_color 方法获取颜色值
                    color_result = self.arsc_parser.get_resource_color(entry)
                    
                    if color_result and len(color_result) >= 2:
                        # 首先检查数据类型，只有颜色类型才使用 color_result[1]
                        use_color = True
                        if res_value_type:
                            # 我们需要判断 res_value_type 是否是颜色类型
                            is_color_type = False
                            if hasattr(res_value, 'get_data_type_string'):
                                type_str = res_value.get_data_type_string()
                                if type_str and 'color' in type_str.lower():
                                    is_color_type = True
                            
                            # 如果不是颜色类型，我们需要做其他处理
                            if not is_color_type:
                                app_logger.debug(f"不是颜色类型，数据类型={res_value_type}, 类型字符串={res_value_type_str if hasattr(res_value, 'get_data_type_string') else 'N/A'}")
                                
                                # 检查是否是 drawable 资源的情况
                                drawable_path = None
                                if hasattr(res_value, 'format_value'):
                                    try:
                                        fmt_val = res_value.format_value()
                                        if fmt_val and (fmt_val.endswith('.xml') or 'drawable' in fmt_val or 'color' in fmt_val):
                                            drawable_path = fmt_val
                                    except:
                                        pass
                                
                                if hasattr(res_value, 'get_data_value'):
                                    try:
                                        data_val = res_value.get_data_value()
                                        if data_val and (data_val.endswith('.xml') or 'drawable' in data_val or 'color' in data_val):
                                            drawable_path = data_val
                                    except:
                                        pass
                                
                                if string_value and (string_value.endswith('.xml') or 'drawable' in string_value or 'color' in string_value):
                                    drawable_path = string_value
                                
                                # 如果找到了 drawable 路径，我们尝试读取和解析它
                                if drawable_path and hasattr(self, 'zip_file'):
                                    try:
                                        app_logger.debug(f"读取 drawable 文件: {drawable_path}")
                                        
                                        # 读取 drawable 文件内容
                                        drawable_data = self.zip_file.read(drawable_path)
                                        
                                        # 打印 XML 文件内容（解码后的）
                                        try:
                                            if drawable_data.startswith(b'\x03\x00'):
                                                printer = AXMLPrinter(drawable_data)
                                                xml_content = printer.get_xml().decode('utf-8', errors='ignore')
                                            else:
                                                xml_content = drawable_data.decode('utf-8', errors='ignore')
                                            app_logger.debug(f"XML文件原始内容：\n{xml_content}")
                                        except Exception as e:
                                            app_logger.warning(f"打印 drawable 内容失败: {e}")
                                        
                                        # 解析这个 XML 文件
                                        # 检查是二进制 XML 还是普通文本 XML
                                        if drawable_data.startswith(b'\x03\x00'):
                                            printer = AXMLPrinter(drawable_data)
                                            xml_obj = printer.get_xml_obj()
                                        else:
                                            xml_obj = etree.fromstring(drawable_data)
                                        
                                        app_logger.debug(f"drawable 根标签: {xml_obj.tag}")
                                        
                                        # 检查是不是 gradient 标签
                                        if 'gradient' in xml_obj.tag.lower():
                                            app_logger.debug(f"检测到 gradient 资源")
                                            
                                            ANDROID_NS = '{http://schemas.android.com/apk/res/android}'
                                            
                                            # 获取 angle 属性（如果有）
                                            angle_attr = xml_obj.get(f'{ANDROID_NS}angle')
                                            angle = float(angle_attr) if angle_attr else None
                                            
                                            # 获取 startX, startY, endX, endY 属性
                                            start_x_attr = xml_obj.get(f'{ANDROID_NS}startX')
                                            start_y_attr = xml_obj.get(f'{ANDROID_NS}startY')
                                            end_x_attr = xml_obj.get(f'{ANDROID_NS}endX')
                                            end_y_attr = xml_obj.get(f'{ANDROID_NS}endY')
                                            
                                            # 根据 angle 或 startX/Y/endX/Y 确定渐变方向
                                            if start_x_attr is not None and start_y_attr is not None and end_x_attr is not None and end_y_attr is not None:
                                                # 如果都指定了，直接使用
                                                start_x = float(start_x_attr)
                                                start_y = float(start_y_attr)
                                                end_x = float(end_x_attr)
                                                end_y = float(end_y_attr)
                                            elif angle is not None:
                                                # 否则根据 angle 计算渐变方向
                                                # Android官方angle属性标准（GradientDrawable.java）：
                                                # 0° = LEFT_RIGHT (左到右)
                                                # 45° = BL_TR (左下到右上)
                                                # 90° = BOTTOM_TOP (下到上)
                                                # 135° = BR_TL (右下到左上)
                                                # 180° = RIGHT_LEFT (右到左)
                                                # 225° = TR_BL (右上到左下)
                                                # 270° = TOP_BOTTOM (上到下)
                                                # 315° = TL_BR (左上到右下)
                                                normalized_angle = angle % 360.0
                                                
                                                if normalized_angle == 0.0:
                                                    # 0° = 左到右
                                                    start_x, start_y = 0.0, 0.5
                                                    end_x, end_y = 1.0, 0.5
                                                elif normalized_angle == 45.0:
                                                    # 45° = 左下到右上
                                                    start_x, start_y = 0.0, 1.0
                                                    end_x, end_y = 1.0, 0.0
                                                elif normalized_angle == 90.0:
                                                    # 90° = 下到上
                                                    start_x, start_y = 0.5, 1.0
                                                    end_x, end_y = 0.5, 0.0
                                                elif normalized_angle == 135.0:
                                                    # 135° = 右下到左上
                                                    start_x, start_y = 1.0, 1.0
                                                    end_x, end_y = 0.0, 0.0
                                                elif normalized_angle == 180.0:
                                                    # 180° = 右到左
                                                    start_x, start_y = 1.0, 0.5
                                                    end_x, end_y = 0.0, 0.5
                                                elif normalized_angle == 225.0:
                                                    # 225° = 右上到左下
                                                    start_x, start_y = 1.0, 0.0
                                                    end_x, end_y = 0.0, 1.0
                                                elif normalized_angle == 270.0:
                                                    # 270° = 上到下
                                                    start_x, start_y = 0.5, 0.0
                                                    end_x, end_y = 0.5, 1.0
                                                elif normalized_angle == 315.0:
                                                    # 315° = 左上到右下
                                                    start_x, start_y = 0.0, 0.0
                                                    end_x, end_y = 1.0, 1.0
                                                else:
                                                    # 对于其他角度，使用三角函数计算
                                                    # Android的角度是从左开始逆时针旋转
                                                    # 在图像坐标系中（y轴向下），需要调整
                                                    # 角度转弧度，并调整坐标系
                                                    # Android: 0° = 向右, 90° = 向上
                                                    # 图像坐标: 0° = 向右, 90° = 向下
                                                    # 所以需要用 -angle 来转换
                                                    rad = math.radians(-normalized_angle)
                                                    dx = math.cos(rad)
                                                    dy = math.sin(rad)
                                                    # 找到从中心出发，到达边缘的最大距离
                                                    max_dist = max(abs(dx), abs(dy)) if abs(dx) > 0 or abs(dy) > 0 else 1
                                                    if max_dist > 0:
                                                        dx /= max_dist
                                                        dy /= max_dist
                                                    start_x = 0.5 - dx * 0.5
                                                    start_y = 0.5 - dy * 0.5
                                                    end_x = 0.5 + dx * 0.5
                                                    end_y = 0.5 + dy * 0.5
                                            else:
                                                # 默认：TOP_BOTTOM (从上到下)，与Android官方一致
                                                start_x = 0.5
                                                start_y = 0.0
                                                end_x = 0.5
                                                end_y = 1.0
                                            
                                            # 查找 gradient 下的 item 元素
                                            items = xml_obj.findall('.//item')
                                            gradient_items = []
                                            
                                            if items:
                                                # 有 item 元素的情况
                                                for item in items:
                                                    color_attr = item.get(f'{ANDROID_NS}color')
                                                    offset_attr = item.get(f'{ANDROID_NS}offset')
                                                    if color_attr:
                                                        # 解析 color_attr，可能是颜色值或资源引用
                                                        color_attr = color_attr.strip()
                                                        resolved_color = color_attr
                                                        if color_attr.startswith('@'):
                                                            res_id = XmlIconParser.parse_resource_id(color_attr)
                                                            if res_id:
                                                                resolved_color = self.get_color_resource_value(res_id)
                                                        offset = float(offset_attr) if offset_attr else None
                                                        # 添加解析日志
                                                        if color_attr.startswith('@'):
                                                            app_logger.debug(f"解析 gradient item 颜色: {color_attr} -> {resolved_color}")
                                                        gradient_items.append({'color': resolved_color, 'offset': offset})
                                            else:
                                                # 没有 item 元素，可能使用 startColor 和 endColor
                                                start_color_attr = xml_obj.get(f'{ANDROID_NS}startColor')
                                                end_color_attr = xml_obj.get(f'{ANDROID_NS}endColor')
                                                
                                                if start_color_attr and end_color_attr:
                                                    # 解析 startColor 和 endColor
                                                    start_color_attr = start_color_attr.strip()
                                                    resolved_start_color = start_color_attr
                                                    if start_color_attr.startswith('@'):
                                                        res_id = XmlIconParser.parse_resource_id(start_color_attr)
                                                        if res_id:
                                                            resolved_start_color = self.get_color_resource_value(res_id)
                                                    
                                                    end_color_attr = end_color_attr.strip()
                                                    resolved_end_color = end_color_attr
                                                    if end_color_attr.startswith('@'):
                                                        res_id = XmlIconParser.parse_resource_id(end_color_attr)
                                                        if res_id:
                                                            resolved_end_color = self.get_color_resource_value(res_id)
                                                    
                                                    # 添加解析日志
                                                    if start_color_attr.startswith('@'):
                                                        app_logger.debug(f"解析 gradient startColor: {start_color_attr} -> {resolved_start_color}")
                                                    if end_color_attr.startswith('@'):
                                                        app_logger.debug(f"解析 gradient endColor: {end_color_attr} -> {resolved_end_color}")
                                                    gradient_items = [
                                                        {'color': resolved_start_color, 'offset': 0.0},
                                                        {'color': resolved_end_color, 'offset': 1.0}
                                                    ]
                                                elif start_color_attr:
                                                    # 只有 startColor
                                                    start_color_attr = start_color_attr.strip()
                                                    resolved_start_color = start_color_attr
                                                    if start_color_attr.startswith('@'):
                                                        res_id = XmlIconParser.parse_resource_id(start_color_attr)
                                                        if res_id:
                                                            resolved_start_color = self.get_color_resource_value(res_id)
                                                    # 添加解析日志
                                                    if start_color_attr.startswith('@'):
                                                        app_logger.debug(f"解析 gradient startColor: {start_color_attr} -> {resolved_start_color}")
                                                    gradient_items = [{'color': resolved_start_color, 'offset': 0.0}]
                                                elif end_color_attr:
                                                    # 只有 endColor
                                                    end_color_attr = end_color_attr.strip()
                                                    resolved_end_color = end_color_attr
                                                    if end_color_attr.startswith('@'):
                                                        res_id = XmlIconParser.parse_resource_id(end_color_attr)
                                                        if res_id:
                                                            resolved_end_color = self.get_color_resource_value(res_id)
                                                    # 添加解析日志
                                                    if end_color_attr.startswith('@'):
                                                        app_logger.debug(f"解析 gradient endColor: {end_color_attr} -> {resolved_end_color}")
                                                    gradient_items = [{'color': resolved_end_color, 'offset': 1.0}]
                                            
                                            if gradient_items:
                                                angle_info = f", angle={angle}" if angle is not None else ""
                                                app_logger.debug(f"解析到 gradient 信息: start=({start_x:.4f},{start_y:.4f}), end=({end_x:.4f},{end_y:.4f}){angle_info}, items={len(gradient_items)}")
                                            
                                            if gradient_items:
                                                # 返回一个渐变信息字典
                                                return {
                                                    'type': 'gradient',
                                                    'startX': start_x,
                                                    'startY': start_y,
                                                    'endX': end_x,
                                                    'endY': end_y,
                                                    'items': gradient_items
                                                }
                                            elif gradient_items and gradient_items[0]['color']:
                                                # 如果解析渐变失败，返回第一个颜色
                                                return gradient_items[0]['color']
                                        elif 'selector' in xml_obj.tag.lower():
                                            app_logger.debug(f"检测到 selector 资源，暂时跳过")
                                        elif 'shape' in xml_obj.tag.lower():
                                            app_logger.debug(f"检测到 shape 资源")
                                            ANDROID_NS = '{http://schemas.android.com/apk/res/android}'
                                            # 尝试查找 solid 标签
                                            solid = xml_obj.find('.//solid')
                                            if solid is not None:
                                                color_attr = solid.get(f'{ANDROID_NS}color')
                                                if color_attr:
                                                    app_logger.debug(f"从 shape solid 找到颜色: {color_attr}")
                                                    return color_attr
                                    except Exception as e:
                                        app_logger.error(f"解析 drawable 失败: {e}")
                                        import traceback
                                        app_logger.error(traceback.format_exc())
                                
                                # 检查 color_result[1] 是否看起来像是无效的颜色
                                color_str = color_result[1]
                                if color_str and color_str.startswith('#') and len(color_str) == 9:
                                    try:
                                        hex_str = color_str[1:]
                                        r = int(hex_str[2:4], 16)
                                        g = int(hex_str[4:6], 16)
                                        b = int(hex_str[6:8], 16)
                                        a = int(hex_str[0:2], 16)
                                        # 如果 a 是 0 并且 r/g/b 非常小，说明这个可能不是真正的颜色
                                        if a == 0 and (r + g + b) < 10:
                                            app_logger.warning(f"检测到无效颜色值 {color_str}，可能是数据类型不对")
                                            # 这种情况下，返回一个默认的灰色，让图标能正常显示
                                            return "#FF888888"
                                    except:
                                        pass
                        
                        result = color_result[1]
                        app_logger.debug(f"返回颜色值={result}")
                        
                        # 额外检查：如果返回的字符串像资源ID格式，尝试递归解析
                        if result and result.startswith('#') and len(result) == 9:
                            try:
                                # 解析为整数检查是否是资源ID格式
                                hex_str = result[1:]
                                res_id = int(hex_str, 16)
                                # 检查是否像资源ID（高位为01, 02, 07, 08等）
                                if (res_id >> 24) in (0x01, 0x02, 0x03, 0x07, 0x08, 0x7f):
                                    app_logger.debug(f"返回值看起来是资源ID，尝试递归解析 {self._format_resource_id(res_id)}")
                                    return self.get_color_resource_value(res_id, xml_name)
                            except:
                                pass
                        
                        return result  # 返回颜色字符串，如 "#FFFFFFFF"
                
            except Exception as e:
                app_logger.error(f"出错 {e}")
                import traceback
                app_logger.error(traceback.format_exc())
        
        # 如果都找不到，返回默认黑色
        app_logger.warning(f"未找到资源 {self._format_resource_id(resource_id)}，返回默认黑色")
        return "#FF000000"

    def get_float_resource_value(self, resource_id, xml_name=None):
        """
        获取float类型资源的值（如透明度值）。
        
        尝试从APK的resources.arsc中获取浮点数值。
        结果会被缓存以提高性能。
        
        Args:
            resource_id: 资源ID（整数）
            xml_name: XML名称（可选）
            
        Returns:
            float: 浮点数值（范围0.0-1.0）
            None: 获取失败时返回None
        """
        # 检查缓存
        if resource_id in self._float_cache:
            app_logger.debug(f"输入: {self._format_resource_id(resource_id)} (从缓存读取)")
            return self._float_cache[resource_id]
        
        result = None
        
        def hex_to_float(hex_str):
            """将 IEEE 754 单精度浮点数的十六进制表示转换为浮点数"""
            try:
                # 去除 # 前缀
                if hex_str.startswith('#'):
                    hex_str = hex_str[1:]
                # 转换为整数
                i = int(hex_str, 16)
                # 转换为 IEEE 754 浮点数
                return struct.unpack('!f', struct.pack('!I', i))[0]
            except:
                return None
        
        # 尝试从APK的resources.arsc中获取
        if self.arsc_parser and resource_id:
            try:
                # 获取资源配置和条目
                configs = list(self.arsc_parser.get_res_configs(resource_id))
                
                if configs:
                    # 使用第一个配置的条目
                    _, entry = configs[0]
                    
                    app_logger.debug(f"解析浮点资源 {self._format_resource_id(resource_id)}:")
                    app_logger.debug(f"  entry 类型: {type(entry)}")
                    app_logger.debug(f"  entry 内容: {entry}")
                    if hasattr(entry, '__dict__'):
                        app_logger.debug(f"  entry 所有属性: {list(entry.__dict__.keys())}")
                    # 打印 arsc_parser 有哪些方法
                    app_logger.debug(f"  arsc_parser 方法: {[m for m in dir(self.arsc_parser) if m.startswith('get_resource_')]}")
                    
                    # 首先尝试 get_resource_color，因为透明度通常会被错误地识别为颜色
                    try:
                        if hasattr(self.arsc_parser, 'get_resource_color'):
                            color_result = self.arsc_parser.get_resource_color(entry)
                            app_logger.debug(f"  get_resource_color 结果: {color_result}")
                            if color_result and len(color_result) >= 2:
                                # 尝试将第二个结果解析为 IEEE 754 浮点数
                                hex_val = str(color_result[1])
                                float_val = hex_to_float(hex_val)
                                if float_val is not None:
                                    # 确保在 0.0-1.0 范围内
                                    float_val = max(0.0, min(1.0, float_val))
                                    app_logger.debug(f"  从十六进制浮点数解析: {hex_val} -> {float_val}")
                                    result = float_val
                    except Exception as e:
                        app_logger.error(f"  get_resource_color 解析浮点数失败: {e}")
                    
                    # 如果通过 get_resource_color 已经成功解析，就不再尝试其他方法
                    if result is None:
                        # 尝试所有可能的 get_resource_* 方法
                        try:
                            # 收集所有以 get_resource_ 开头的方法
                            resource_methods = [m for m in dir(self.arsc_parser) if m.startswith('get_resource_')]
                            app_logger.debug(f"  尝试的资源方法(函数): {resource_methods}")
                            
                            for method_name in resource_methods:
                                if method_name == 'get_resource_color':
                                    continue  # 已经试过了
                                try:
                                    method = getattr(self.arsc_parser, method_name)
                                    method_result = method(entry)
                                    app_logger.debug(f"    {method_name} 结果: {method_result}")
                                    if method_result and len(method_result) >= 2:
                                        try:
                                            # 尝试直接转换
                                            val = float(method_result[1])
                                            # 确保在 0.0-1.0 范围内
                                            val = max(0.0, min(1.0, val))
                                            app_logger.debug(f"    成功解析: {val}")
                                            if result is None:  # 只有在没有找到结果时才赋值
                                                result = val
                                        except:
                                            # 如果是字符串，尝试去除百分号等
                                            try:
                                                s = str(method_result[1])
                                                if '%' in s:
                                                    s = s.replace('%', '')
                                                    val = float(s) / 100.0
                                                    val = max(0.0, min(1.0, val))
                                                    app_logger.debug(f"    百分比解析: {val}")
                                                    if result is None:
                                                        result = val
                                                else:
                                                    val = float(s)
                                                    val = max(0.0, min(1.0, val))
                                                    app_logger.debug(f"    字符串解析: {val}")
                                                    if result is None:
                                                        result = val
                                            except:
                                                pass
                                except Exception as e:
                                    app_logger.error(f"    {method_name} 失败: {e}")
                                    continue
                        except Exception as e:
                            app_logger.error(f"  尝试 get_resource_* 方法时出错: {e}")
                        
                        # 尝试直接访问 entry 的所有公开属性
                        if result is None:
                            try:
                                if hasattr(entry, '__dict__'):
                                    for attr_name, val in entry.__dict__.items():
                                        if not attr_name.startswith('_') and val is not None:
                                            try:
                                                float_val = float(val)
                                                float_val = max(0.0, min(1.0, float_val))
                                                app_logger.debug(f"  通过属性 {attr_name} 解析: {float_val}")
                                                if result is None:
                                                    result = float_val
                                            except:
                                                try:
                                                    # 尝试作为整数处理（可能是 fraction）
                                                    int_val = int(val)
                                                    float_val = int_val / 65536.0
                                                    float_val = max(0.0, min(1.0, float_val))
                                                    app_logger.debug(f"  通过属性 {attr_name} 作为 fraction 解析: {int_val} -> {float_val}")
                                                    if result is None:
                                                        result = float_val
                                                except:
                                                    pass
                            except Exception as e:
                                app_logger.error(f"  尝试访问 entry 属性时出错: {e}")
                
            except Exception as e:
                app_logger.error(f"从APK获取浮点资源值失败: {e}")
                import traceback
                app_logger.error(traceback.format_exc())
        
        # 如果都找不到，返回 None
        if result is None:
            app_logger.debug(f"无法解析浮点资源 {self._format_resource_id(resource_id)}")
        
        # 存入缓存
        self._float_cache[resource_id] = result
        return result


    @staticmethod
    def parse_binary_xml_to_obj(xml_data):
        """
        将二进制XML转换为lxml Element对象。
        
        使用androguard的AXMLPrinter解析Android二进制XML格式。
        
        Args:
            xml_data: 二进制XML数据（bytes）
            
        Returns:
            lxml.etree.Element: XML元素对象
        """
        printer = AXMLPrinter(xml_data)
        app_logger.debug(f"XML文件原始内容：\n{printer.get_xml().decode('utf-8', errors='ignore')}")
        return printer.get_xml_obj()

    def parse_adaptive_icon_xml(self, xml_data):
        """
        解析Adaptive Icon XML文件，提取前景和背景图层信息。
        
        支持资源ID格式（如@7F0F0001）和多种资源类型（drawable、mipmap、color等）。
        支持多种格式：
        1. 直接在图层元素上使用drawable属性：<background android:drawable="@xxx"/>
        2. 在图层元素内部使用bitmap标签：<background><bitmap android:src="@xxx"/></background>
        3. 在图层元素内部使用inset标签：<foreground><inset android:drawable="@xxx"/></foreground>
        4. 在图层元素内部使用内嵌vector：<foreground><vector .../></foreground>
        
        Args:
            xml_data: 二进制XML数据（bytes）
            
        Returns:
            dict: 包含各图层的完整信息，键为 'foreground'、'background'、'monochrome'，
                  值为包含 xml_name、resource_id、resource_type、inline_vector 的字典
        """
        printer = AXMLPrinter(xml_data)
        xml_obj = printer.get_xml_obj()
        
        result = {
            'foreground': {'xml_name': None, 'resource_id': None, 'resource_type': None, 'inline_vector': None},
            'background': {'xml_name': None, 'resource_id': None, 'resource_type': None, 'inline_vector': None},
            'monochrome': {'xml_name': None, 'resource_id': None, 'resource_type': None, 'inline_vector': None}
        }
        
        if xml_obj.tag.endswith('adaptive-icon'):
            layers = [
                ('background', 'background'),
                ('foreground', 'foreground'),
                ('monochrome', 'monochrome')
            ]
            
            for layer_key, layer_tag in layers:
                layer_elem = xml_obj.find('.//{*}' + layer_tag)
                if layer_elem is not None:
                    attr = None
                    drawable_attr = layer_elem.get('{http://schemas.android.com/apk/res/android}drawable')
                    if drawable_attr:
                        attr = drawable_attr
                    else:
                        # 检查是否有需要特殊处理的子元素（如inset）
                        # 如果有inset子元素，需要将整个inset元素序列化为XML
                        inset_elem = layer_elem.find('.//{*}inset')
                        if inset_elem is not None:
                            # 将inset元素序列化为XML数据
                            inset_xml = etree.tostring(inset_elem, encoding='unicode')
                            inset_xml_bytes = inset_xml.encode('utf-8')
                            result[layer_key] = {
                                'xml_name': '@inset_xml',
                                'resource_id': None,
                                'resource_type': 'inset_xml',
                                'inline_vector': inset_xml_bytes
                            }
                            continue
                        
                        supported_tags = ['bitmap', 'clip', 'scale', 'rotate', 'ripple']
                        attr = None
                        
                        for child_tag in supported_tags:
                            child_elem = layer_elem.find('.//{*}' + child_tag)
                            if child_elem is not None:
                                child_drawable = child_elem.get('{http://schemas.android.com/apk/res/android}drawable')
                                if child_drawable:
                                    attr = child_drawable
                                    break
                                child_src = child_elem.get('{http://schemas.android.com/apk/res/android}src')
                                if child_src:
                                    attr = child_src
                                    break
                        
                        if not attr:
                            vector_elem = layer_elem.find('.//{*}vector')
                            if vector_elem is not None:
                                result[layer_key] = {
                                    'xml_name': '@inline_vector',
                                    'resource_id': None,
                                    'resource_type': 'inline_vector',
                                    'inline_vector': xml_data
                                }
                                continue
                    
                    if attr:
                        res_id = self.parse_resource_id(attr)
                        if res_id:
                            xml_name = self.resolve_resource_id_to_xml_name(res_id)
                            resource_type = self._extract_resource_type(xml_name)
                            result[layer_key] = {
                                'xml_name': xml_name,
                                'resource_id': res_id,
                                'resource_type': resource_type,
                                'inline_vector': None
                            }
        
        return result
    
    def _extract_resource_type(self, xml_name):
        """
        从XML名称中提取资源类型
        
        :param xml_name: XML名称，如 "@drawable/ic_background" 或 "@color/ic_launcher_background"
        :return: 资源类型字符串，如 "drawable"、"mipmap"、"color" 等
        """
        if not xml_name:
            return None
        
        match = re.match(r'@(?:([^:]+):)?(\w+)/(.+)', xml_name)
        if match:
            return match.group(2)
        return None

    def parse_layer_list_xml(self, xml_data):
        """
        解析 layer-list XML，提取所有图层信息
        
        :param xml_data: 二进制 XML 数据 (bytes)
        :return: list 包含所有图层的 XML 名称
        """
        # 将二进制 XML 转换为 lxml Element 对象
        printer = AXMLPrinter(xml_data)
        xml_obj = printer.get_xml_obj()
        
        layers = []
        
        # 检查是否为 layer-list 根元素
        if xml_obj.tag.endswith('layer-list'):
            # 提取所有 item 元素
            items = xml_obj.findall('.//{*}item')
            for item in items:
                # 获取 drawable 属性
                drawable_attr = item.get('{http://schemas.android.com/apk/res/android}drawable')
                if drawable_attr:
                    # 判断是否为资源 ID（长度为9的十六进制字符串）
                    if drawable_attr.startswith('@') and len(drawable_attr) == 9:
                        res_id = self.parse_resource_id(drawable_attr)
                        if res_id:
                            # 将资源 ID 转换为 XML 名称
                            xml_name = self.resolve_resource_id_to_xml_name(res_id)
                            if xml_name:
                                layers.append(xml_name)
                    else:
                        # 直接使用 XML 名称
                        layers.append(drawable_attr)
        
        return layers

    def parse_selector_xml(self, xml_data):
        """
        解析selector XML，提取默认状态的图标。
        
        Selector是状态选择器，根据控件状态（如按下、选中、禁用等）
        显示不同的图标。此方法提取默认状态（无状态属性）的图标。
        
        Args:
            xml_data: 二进制XML数据（bytes）
            
        Returns:
            str: 默认状态的XML名称（如 "@drawable/ic_launcher"）
            None: 未找到默认状态时返回None
        """
        # 将二进制 XML 转换为 lxml Element 对象
        printer = AXMLPrinter(xml_data)
        xml_obj = printer.get_xml_obj()
        
        # 检查是否为 selector 根元素
        if xml_obj.tag.endswith('selector'):
            # 获取所有 item 元素
            items = xml_obj.findall('.//{*}item')
            
            # 优先查找没有 state 属性的 item（默认状态）
            for item in items:
                has_state = False
                for attr in item.attrib:
                    if 'state' in attr:
                        has_state = True
                        break
                if not has_state:
                    # 获取 drawable 属性
                    drawable_attr = item.get('{http://schemas.android.com/apk/res/android}drawable')
                    if drawable_attr:
                        # 判断是否为资源 ID
                        if drawable_attr.startswith('@') and len(drawable_attr) == 9:
                            res_id = self.parse_resource_id(drawable_attr)
                            if res_id:
                                return self.resolve_resource_id_to_xml_name(res_id)
                        else:
                            return drawable_attr
            
            # 如果没有找到默认状态，返回第一个 item
            if items:
                first_item = items[0]
                drawable_attr = first_item.get('{http://schemas.android.com/apk/res/android}drawable')
                if drawable_attr:
                    if drawable_attr.startswith('@') and len(drawable_attr) == 9:
                        res_id = self.parse_resource_id(drawable_attr)
                        if res_id:
                            return self.resolve_resource_id_to_xml_name(res_id)
                    else:
                        return drawable_attr
        
        return None

    @staticmethod
    def parse_path_data_to_points(path_data, scale=1.0, offset_x=0, offset_y=0):
        """
        解析SVG路径数据为点列表，用于绘制遮罩。
        
        与Android官方PathParser实现保持一致。
        支持的命令：M, m, L, l, H, h, V, v, C, c, S, s, Q, q, T, t, A, a, Z, z
        
        Args:
            path_data: SVG路径数据字符串
            scale: 缩放比例
            offset_x: X偏移量
            offset_y: Y偏移量
            
        Returns:
            list: 多边形点列表 [(x, y), ...]
        """
        if not path_data:
            return []
        
        def arc_to_points(x1, y1, rx, ry, phi, large_arc, sweep, x2, y2, num_segments=20):
            """
            将arc命令转换为点列表。
            
            与Android官方PathParser和SVG规范保持一致。
            参考：https://www.w3.org/TR/SVG/implnote.html#ArcImplementationNotes
            
            Args:
                x1, y1: 起点
                rx, ry: 椭圆半径
                phi: x轴旋转角度（弧度）
                large_arc: 大弧标志（0或1）
                sweep: 顺时针标志（0或1）
                x2, y2: 终点
                num_segments: 分段数
                
            Returns:
                list: 点列表
            """
            if rx == 0 or ry == 0:
                return [(x2, y2)]
            
            rx, ry = abs(rx), abs(ry)
            
            cos_phi = math.cos(phi)
            sin_phi = math.sin(phi)
            
            dx = (x1 - x2) / 2
            dy = (y1 - y2) / 2
            
            x1p = cos_phi * dx + sin_phi * dy
            y1p = -sin_phi * dx + cos_phi * dy
            
            lambda_sq = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry) if rx > 0 and ry > 0 else 0
            if lambda_sq > 1:
                lambda_val = math.sqrt(lambda_sq)
                rx *= lambda_val
                ry *= lambda_val
            
            sq = max(0, (rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p))
            denom = (rx * rx * y1p * y1p + ry * ry * x1p * x1p)
            if denom > 0:
                sq /= denom
            else:
                sq = 0
            coef = math.sqrt(sq)
            
            if large_arc == sweep:
                coef = -coef
            
            cxp = coef * rx * y1p / ry if ry > 0 else 0
            cyp = coef * -ry * x1p / rx if rx > 0 else 0
            
            cx = cos_phi * cxp - sin_phi * cyp + (x1 + x2) / 2
            cy = sin_phi * cxp + cos_phi * cyp + (y1 + y2) / 2
            
            def angle_between(ux, uy, vx, vy):
                n = math.sqrt(ux * ux + uy * uy) * math.sqrt(vx * vx + vy * vy)
                if n == 0:
                    return 0
                c = max(-1, min(1, (ux * vx + uy * vy) / n))
                a = math.acos(c)
                if ux * vy - uy * vx < 0:
                    return -a
                return a
            
            theta1 = angle_between(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry) if rx > 0 and ry > 0 else 0
            dtheta = angle_between((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry) if rx > 0 and ry > 0 else 0
            
            if sweep and dtheta < 0:
                dtheta += 2 * math.pi
            elif not sweep and dtheta > 0:
                dtheta -= 2 * math.pi
            
            points = []
            for i in range(num_segments + 1):
                t = theta1 + dtheta * i / num_segments
                px = rx * math.cos(t)
                py = ry * math.sin(t)
                x = cos_phi * px - sin_phi * py + cx
                y = sin_phi * px + cos_phi * py + cy
                points.append((x, y))
            
            return points
        
        points = []
        current_x, current_y = 0.0, 0.0
        start_x, start_y = 0.0, 0.0
        last_ctrl_x, last_ctrl_y = 0.0, 0.0
        
        pattern = r'([MmLlHhVvCcSsQqTtAaZz])([^MmLlHhVvCcSsQqTtAaZz]*)'
        matches = re.findall(pattern, path_data)
        
        for cmd, params_str in matches:
            params_str = params_str.strip()
            if params_str:
                params = re.split(r'[,\s]+', params_str)
                params = [float(p) for p in params if p]
            else:
                params = []
            
            if cmd == 'M':
                if current_x != start_x or current_y != start_y or len(points) > 0:
                    pass
                current_x = params[0] * scale + offset_x
                current_y = params[1] * scale + offset_y
                start_x, start_y = current_x, current_y
                points.append((current_x, current_y))
                for i in range(2, len(params), 2):
                    current_x = params[i] * scale + offset_x
                    current_y = params[i + 1] * scale + offset_y
                    points.append((current_x, current_y))
                    start_x, start_y = current_x, current_y
            elif cmd == 'm':
                current_x += params[0] * scale
                current_y += params[1] * scale
                start_x, start_y = current_x, current_y
                points.append((current_x, current_y))
                for i in range(2, len(params), 2):
                    current_x += params[i] * scale
                    current_y += params[i + 1] * scale
                    points.append((current_x, current_y))
                    start_x, start_y = current_x, current_y
            elif cmd == 'L':
                for i in range(0, len(params), 2):
                    current_x = params[i] * scale + offset_x
                    current_y = params[i + 1] * scale + offset_y
                    points.append((current_x, current_y))
            elif cmd == 'l':
                for i in range(0, len(params), 2):
                    current_x += params[i] * scale
                    current_y += params[i + 1] * scale
                    points.append((current_x, current_y))
            elif cmd == 'H':
                for p in params:
                    current_x = p * scale + offset_x
                    points.append((current_x, current_y))
            elif cmd == 'h':
                for p in params:
                    current_x += p * scale
                    points.append((current_x, current_y))
            elif cmd == 'V':
                for p in params:
                    current_y = p * scale + offset_y
                    points.append((current_x, current_y))
            elif cmd == 'v':
                for p in params:
                    current_y += p * scale
                    points.append((current_x, current_y))
            elif cmd == 'C':
                for i in range(0, len(params), 6):
                    x1 = params[i] * scale + offset_x
                    y1 = params[i + 1] * scale + offset_y
                    x2 = params[i + 2] * scale + offset_x
                    y2 = params[i + 3] * scale + offset_y
                    x3 = params[i + 4] * scale + offset_x
                    y3 = params[i + 5] * scale + offset_y
                    num_segments = 10
                    for j in range(num_segments + 1):
                        t = j / num_segments
                        t2, t3 = t * t, t * t * t
                        mt = 1 - t
                        mt2, mt3 = mt * mt, mt * mt * mt
                        px = mt3 * current_x + 3 * mt2 * t * x1 + 3 * mt * t2 * x2 + t3 * x3
                        py = mt3 * current_y + 3 * mt2 * t * y1 + 3 * mt * t2 * y2 + t3 * y3
                        points.append((px, py))
                    current_x, current_y = x3, y3
                    last_ctrl_x, last_ctrl_y = x2, y2
            elif cmd == 'c':
                for i in range(0, len(params), 6):
                    x1 = current_x + params[i] * scale
                    y1 = current_y + params[i + 1] * scale
                    x2 = current_x + params[i + 2] * scale
                    y2 = current_y + params[i + 3] * scale
                    x3 = current_x + params[i + 4] * scale
                    y3 = current_y + params[i + 5] * scale
                    num_segments = 10
                    for j in range(num_segments + 1):
                        t = j / num_segments
                        t2, t3 = t * t, t * t * t
                        mt = 1 - t
                        mt2, mt3 = mt * mt, mt * mt * mt
                        px = mt3 * current_x + 3 * mt2 * t * x1 + 3 * mt * t2 * x2 + t3 * x3
                        py = mt3 * current_y + 3 * mt2 * t * y1 + 3 * mt * t2 * y2 + t3 * y3
                        points.append((px, py))
                    current_x, current_y = x3, y3
                    last_ctrl_x, last_ctrl_y = x2, y2
            elif cmd == 'Q':
                for i in range(0, len(params), 4):
                    x1 = params[i] * scale + offset_x
                    y1 = params[i + 1] * scale + offset_y
                    x2 = params[i + 2] * scale + offset_x
                    y2 = params[i + 3] * scale + offset_y
                    num_segments = 10
                    for j in range(num_segments + 1):
                        t = j / num_segments
                        mt = 1 - t
                        px = mt * mt * current_x + 2 * mt * t * x1 + t * t * x2
                        py = mt * mt * current_y + 2 * mt * t * y1 + t * t * y2
                        points.append((px, py))
                    current_x, current_y = x2, y2
                    last_ctrl_x, last_ctrl_y = x1, y1
            elif cmd == 'q':
                for i in range(0, len(params), 4):
                    x1 = current_x + params[i] * scale
                    y1 = current_y + params[i + 1] * scale
                    x2 = current_x + params[i + 2] * scale
                    y2 = current_y + params[i + 3] * scale
                    num_segments = 10
                    for j in range(num_segments + 1):
                        t = j / num_segments
                        mt = 1 - t
                        px = mt * mt * current_x + 2 * mt * t * x1 + t * t * x2
                        py = mt * mt * current_y + 2 * mt * t * y1 + t * t * y2
                        points.append((px, py))
                    current_x, current_y = x2, y2
                    last_ctrl_x, last_ctrl_y = x1, y1
            elif cmd == 'A':
                for i in range(0, len(params), 7):
                    rx = params[i] * scale
                    ry = params[i + 1] * scale
                    phi = math.radians(params[i + 2])
                    large_arc = int(params[i + 3])
                    sweep = int(params[i + 4])
                    x2 = params[i + 5] * scale + offset_x
                    y2 = params[i + 6] * scale + offset_y
                    arc_points = arc_to_points(current_x, current_y, rx, ry, phi, large_arc, sweep, x2, y2)
                    points.extend(arc_points)
                    current_x, current_y = x2, y2
            elif cmd == 'a':
                for i in range(0, len(params), 7):
                    rx = params[i] * scale
                    ry = params[i + 1] * scale
                    phi = math.radians(params[i + 2])
                    large_arc = int(params[i + 3])
                    sweep = int(params[i + 4])
                    x2 = current_x + params[i + 5] * scale
                    y2 = current_y + params[i + 6] * scale
                    arc_points = arc_to_points(current_x, current_y, rx, ry, phi, large_arc, sweep, x2, y2)
                    points.extend(arc_points)
                    current_x, current_y = x2, y2
            elif cmd == 'Z' or cmd == 'z':
                points.append((start_x, start_y))
                current_x, current_y = start_x, start_y
        
        return points

    @staticmethod
    def apply_mask_to_image(image, mask_path, output_size):
        """
        应用遮罩到图像上。
        
        与Android官方AdaptiveIconDrawable.draw()方法保持一致。
        使用遮罩路径裁剪图像，实现圆角矩形等效果。
        
        注意：Android的canvas.drawPath()只绘制路径内的区域，
        路径外（四个角）保持Canvas原始状态（透明），即RGBA全为0。
        因此我们需要将透明区域的RGB也清零，而不仅仅是Alpha。
        
        Args:
            image: PIL.Image对象，待遮罩的图像
            mask_path: 遮罩路径数据字符串（100x100坐标系）
            output_size: 输出尺寸 (width, height)
            
        Returns:
            PIL.Image: 遮罩后的图像
        """
        width, height = output_size
        
        scale_x = width / XmlIconParser.MASK_SIZE
        scale_y = height / XmlIconParser.MASK_SIZE
        
        mask_points = XmlIconParser.parse_path_data_to_points(mask_path, scale_x, 0)
        
        mask_img = Image.new('L', (width, height), 0)
        mask_draw = ImageDraw.Draw(mask_img)
        
        if mask_points:
            mask_draw.polygon(mask_points, fill=255)
        
        # 将原图转换为RGBA模式
        image_rgba = image.convert('RGBA') if image.mode != 'RGBA' else image.copy()
        
        # 创建结果图像，初始为全透明（RGBA全为0）
        result = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        result_pixels = result.load()
        mask_pixels = mask_img.load()
        image_pixels = image_rgba.load()
        
        for y in range(height):
            for x in range(width):
                mask_val = mask_pixels[x, y]
                if mask_val > 0:
                    r, g, b, a = image_pixels[x, y]
                    new_alpha = (a * mask_val) // 255
                    result_pixels[x, y] = (r, g, b, new_alpha)
                # else: 保持(0,0,0,0)
        
        return result

    @staticmethod
    def _process_single_layer(layer_image, output_size=(432, 432)):
        """
        处理单个图层，进行裁剪和遮罩。
        
        当只有前景或背景图层时使用此方法。
        按照Android官方逻辑进行裁剪和遮罩处理。
        
        Args:
            layer_image: 单个图层图像（PIL.Image对象）
            output_size: 输出尺寸，默认432x432
            
        Returns:
            PIL.Image: 处理后的图像
        """
        width, height = output_size
        
        layer_width, layer_height = layer_image.size
        center_x = layer_width // 2
        center_y = layer_height // 2
        left = center_x - width // 2
        top = center_y - height // 2
        right = left + width
        bottom = top + height
        
        cropped = layer_image.crop((left, top, right, bottom))
        
        cropped = XmlIconParser.apply_mask_to_image(
            cropped, 
            XmlIconParser.DEFAULT_ICON_MASK_PATH, 
            output_size
        )
        
        return cropped

    @staticmethod
    def combine_foreground_background(fg_image, bg_image, output_size=(432, 432), apply_mask=True):
        """
        合成前景和背景图片为完整的Adaptive Icon。
        
        完全按照Android官方AdaptiveIconDrawable.java的逻辑：
        1. 图层大小比视口大50%（每边25%的内边距）
        2. 先创建一个黑色背景的底图
        3. 在黑色底图上画背景层
        4. 在上面画前景层
        5. 使用遮罩路径裁剪最终图像
        
        参考：
        - AdaptiveIconDrawable.java 第344-362行：updateLayerBoundsInternal()
        - AdaptiveIconDrawable.java 第383-405行：draw()
        
        Args:
            fg_image: 前景图片（PIL.Image对象）
            bg_image: 背景图片（PIL.Image对象）
            output_size: 输出尺寸，默认432x432
            apply_mask: 是否应用遮罩，默认True
            
        Returns:
            PIL.Image: 合成后的图片
        """
        
        width, height = output_size
        
        inset_width = int(width / (XmlIconParser.DEFAULT_VIEW_PORT_SCALE * 2))
        inset_height = int(height / (XmlIconParser.DEFAULT_VIEW_PORT_SCALE * 2))
        
        layer_width = inset_width * 2
        layer_height = inset_height * 2
        
        bg_layer = bg_image.resize((layer_width, layer_height), Image.LANCZOS)
        fg_layer = fg_image.resize((layer_width, layer_height), Image.LANCZOS)
        
        combined = Image.new('RGBA', (layer_width, layer_height), (0, 0, 0, 255))
        
        bg_rgba = bg_layer.convert('RGBA')
        combined = Image.alpha_composite(combined, bg_rgba)
        
        fg_rgba = fg_layer.convert('RGBA')
        combined = Image.alpha_composite(combined, fg_rgba)
        
        center_x = layer_width // 2
        center_y = layer_height // 2
        left = center_x - width // 2
        top = center_y - height // 2
        right = left + width
        bottom = top + height
        
        cropped = combined.crop((left, top, right, bottom))
        
        if apply_mask:
            cropped = XmlIconParser.apply_mask_to_image(
                cropped, 
                XmlIconParser.DEFAULT_ICON_MASK_PATH, 
                output_size
            )
        
        return cropped


# ============================================================================
# APK后台解析工作线程类
# ============================================================================

class ApkWorker(QThread):
    """
    APK后台解析工作线程。
    
    在后台线程中执行APK文件的解析操作，避免阻塞主界面。
    使用多线程并行解析应用信息、签名信息、文件信息和图标。
    
    Signals:
        app_info_finished: 应用信息解析完成信号 (apk_info, error_message, done)
        signature_info_finished: 签名信息解析完成信号 (signature_info, certs, error_message, done)
        file_info_finished: 文件信息解析完成信号 (file_info, error_message, done)
        icon_finished: 图标解析完成信号 (icon_data, error_message, apk_icon_info, done)
        progress_update: 进度更新信号
    
    Attributes:
        apk_path: APK文件路径
        stop_flag: 停止标志，用于中断解析操作
        certs: 证书数据列表
        parser: APKParser解析器实例
        apk_info: 应用信息字典
        apk_icon_info: 图标信息字典
    """
    # 定义多个信号，分别用于不同类型的信息解析完成
    app_info_finished = pyqtSignal(dict, str, bool)  # 应用信息解析完成 (apk_info, error_message, done)
    signature_info_finished = pyqtSignal(str, object, str, bool)  # 签名信息解析完成 (signature_info, certs, error_message, done)
    file_info_finished = pyqtSignal(str, str, bool)  # 文件信息解析完成 (file_info, error_message, done)
    icon_finished = pyqtSignal(object, str, dict, bool)  # 图标解析完成 (icon_data, error_message, apk_icon_info, done) - 使用object类型允许None值
    progress_update = pyqtSignal(str)  # 进度更新信号

    def __init__(self, apk_path):
        """
        初始化APK解析工作线程。
        
        Args:
            apk_path: APK文件的完整路径
        """
        super().__init__()
        self.apk_path = apk_path
        self.stop_flag = False  # 添加停止标志，用于中断操作
        self.certs = None
        self.parser = None  # 统一的APK解析器
        self.init_apk_info() # 初始化apk_info字典

    def init_apk_info(self):
        """
        初始化apk_info和apk_icon_info字典。
        
        创建用于存储应用基本信息和图标信息的字典结构。
        """
        self.apk_info = {
            'package_name': '',
            'app_name': '',
            'chinese_app_name': '',
            'version_name': '',
            'version_code': '',
            'min_sdk_version': '',
            'target_sdk_version': '',
            'build_sdk_version': '',    # 暂时不使用
            'compile_sdk_version': '',    # 若 compile_sdk 不存在，则使用 build_sdk 的值
            'permissions': [],
        }
        self.apk_icon_info = {
            'icon_list': [],
            'icon_path': '',
            'icon_sure': True  # True表示确定的图标，False表示推测/猜测的图标
        }

    def run(self):
        """
        执行APK解析任务。
        
        创建APKParser解析器，然后并行启动四个解析任务：
        - 应用信息解析
        - 签名信息解析
        - 文件信息解析
        - 图标解析
        
        解析完成后关闭解析器释放资源。
        """
        start_time = time.time()
        apk_name = os.path.basename(self.apk_path)
        app_logger.info(f"开始解析APK: {apk_name}")

        # 初始化统一的APK解析器
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        app_logger.info(f"[{current_time}] == 开始文件加载")
        self.parser = APKParser(self.apk_path)
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        app_logger.info(f"[{current_time}] == 完成文件加载")
        
        try:
            # 创建线程分别执行不同的解析任务
            app_thread = threading.Thread(target=self._parse_app_info_task)
            sig_thread = threading.Thread(target=self._parse_signature_info_task)
            file_thread = threading.Thread(target=self._parse_file_info_task)
            icon_thread = threading.Thread(target=self._parse_icon_task)
            
            # 启动所有线程
            app_thread.start()
            sig_thread.start()
            file_thread.start()
            
            # 等待所有线程完成
            app_thread.join()
            
            icon_thread.start()
            
            sig_thread.join()
            file_thread.join()
            icon_thread.join()
        except Exception as e:
            app_logger.error(f"解析任务执行失败: {e}")
        finally:
            # 关闭解析器并清空引用
            if self.parser:
                self.parser.close()
                self.parser = None
            
            # 清空证书数据引用（数据已传递给主窗口）
            self.certs = None
            
            # 清空图标列表中的临时数据
            if self.apk_icon_info and 'icon_list' in self.apk_icon_info:
                self.apk_icon_info['icon_list'] = []

            elapsed_time = time.time() - start_time
            app_logger.info(f"结束解析APK: {apk_name}, 总耗时: {elapsed_time:.2f}秒")

    def stop(self):
        """
        停止解析操作。
        
        设置停止标志，通知所有解析任务停止执行。
        """
        self.stop_flag = True

    def check_stop_flag(self):
        """
        检查停止标志。
        
        Returns:
            bool: 如果需要停止返回True，否则返回False
        """
        return self.stop_flag

    def _parse_app_info_task(self):
        """
        解析应用信息（基本信息+权限信息）的任务。
        
        使用androguard解析APK基本信息，解析完成后发送信号通知主线程。
        """
        try:
            # 使用 androguard 方式解析
            androguard_success, androguard_error = self.parse_apk_info_with_androguard()
            # 发送应用信息解析完成信号
            self.app_info_finished.emit(self.apk_info, "" if androguard_success else androguard_error, True)
        except Exception as e:
            # 发送错误信号
            self.app_info_finished.emit(self.apk_info, f"解析应用信息失败: {e}", True)

    def _parse_signature_info_task(self):
        """
        解析签名信息的任务。
        
        获取APK签名信息，解析完成后发送信号通知主线程。
        """
        try:
            self.signature_info_finished.emit("正在解析签名信息...", None, "", False)
            # 获取签名信息
            signature_info = self.get_signature_info_internal()
            # 发送签名信息解析完成信号
            self.signature_info_finished.emit(signature_info, self.certs, "", True)
        except Exception as e:
            # 发送错误信号
            self.signature_info_finished.emit("", self.certs, f"解析签名信息失败: {str(e)}", True)

    def _parse_file_info_task(self):
        """
        解析文件信息的任务。
        
        获取APK文件大小和MD5哈希值，解析完成后发送信号通知主线程。
        """
        try:
            self.file_info_finished.emit("正在解析文件信息...", "", False)
            # 获取文件信息
            file_info = self.get_file_info_internal(self.apk_path)
            # 发送文件信息解析完成信号
            self.file_info_finished.emit(file_info, "", True)
        except Exception as e:
            # 发送错误信号
            self.file_info_finished.emit("", f"解析文件信息失败: {str(e)}", True)

    def _parse_icon_task(self):
        """
        解析图标的任务。
        
        提取APK应用图标数据，解析完成后发送信号通知主线程。
        """
        try:
            self.icon_finished.emit(None, "", self.apk_icon_info, False)  # 为了显示正在解析中，发一个空信号
            # 解析图标
            icon_data, error_message = self.extract_icon_internal()
            # 发送图标解析完成信号
            self.icon_finished.emit(icon_data, error_message, self.apk_icon_info, True)
        except Exception as e:
            self.icon_finished.emit(None, f"解析图标失败: {str(e)}", self.apk_icon_info, True)

    def get_signature_info_internal(self):
        """
        获取APK签名信息。
        
        解析APK的V1/V2/V3签名状态，提取证书信息并计算证书哈希值。
        
        Returns:
            str: 格式化的签名信息文本
        """
        self.certs = None
        signature_info = []
        try:
            # 使用统一的解析器获取APK实例
            apk_obj = self.parser.get_custom_apk()
            
            signature_info.append(f"应用包名: {apk_obj.get_package()}")
            signature_info.append(f"V1签名状态: {'已签名' if apk_obj.is_signed_v1() else '未签名'}")
            signature_info.append(f"V2签名状态: {'已签名' if apk_obj.is_signed_v2() else '未签名'}")
            signature_info.append(f"V3签名状态: {'已签名' if apk_obj.is_signed_v3() else '未签名'}")
            
            # 获取所有证书
            certs = set(
                apk_obj.get_certificates_der_v3()
                + apk_obj.get_certificates_der_v2()
                + [apk_obj.get_certificate_der(x) for x in apk_obj.get_signature_names()]
            )
            
            if len(certs) > 0:
                self.certs = certs
                signature_info.append(f"\n++++存在 {len(certs)} 个证书++++")
                
                cert_index = 1
                for cert in certs:
                    signature_info.append(f"\n证书 {cert_index}:")
                    
                    try:
                        x509_cert = x509.Certificate.load(cert)
                        signature_info.append(f"主题: {get_certificate_name_string(x509_cert.subject, short=True)}")
                        signature_info.append(f"颁发者: {get_certificate_name_string(x509_cert.issuer, short=True)}")
                        signature_info.append(f"序列号: {hex(x509_cert.serial_number)}")
                        signature_info.append(f"哈希算法: {x509_cert.hash_algo}")
                        signature_info.append(f"签名算法: {x509_cert.signature_algo}")
                        signature_info.append(f"有效期从: {x509_cert['tbs_certificate']['validity']['not_before'].native}")
                        signature_info.append(f"有效期至: {x509_cert['tbs_certificate']['validity']['not_after'].native}")
                        
                        # 计算证书的各种哈希值
                        signature_info.append("\n证书指纹(哈希值):")
                        signature_info.append(f"MD5: {hashlib.md5(cert).hexdigest().upper()}")
                        signature_info.append(f"SHA1: {hashlib.sha1(cert).hexdigest().upper()}")
                        signature_info.append(f"SHA256: {hashlib.sha256(cert).hexdigest().upper()}")
                        signature_info.append(f"SHA512: {hashlib.sha512(cert).hexdigest().upper()}")
                        
                    except Exception as e:
                        signature_info.append(f"解析证书失败: {str(e)}")
                    
                    cert_index += 1
            else:
                signature_info.append("\n未找到证书")
            
            return '\n'.join(signature_info)
            
        except Exception as e:
            return f"获取签名信息失败: {str(e)}\n" + '\n'.join(signature_info)

    def get_file_info_internal(self, file_path):
        """
        获取APK文件信息。
        
        计算文件大小和MD5哈希值。
        
        Args:
            file_path: APK文件路径
            
        Returns:
            str: 格式化的文件信息文本
        """
        # 文件大小
        file_size = os.path.getsize(file_path)
        size_mb = file_size / (1024 * 1024)
        
        try:
            # 计算文件MD5
            self.file_info_finished.emit("正在计算文件MD5...", "", False)
            md5_hash = hashlib.md5()
            with open(file_path, "rb") as f:
                # 分块读取，避免内存占用过高
                chunk_size = 8192
                for chunk in iter(lambda: f.read(chunk_size), b""):
                    md5_hash.update(chunk)
            
            md5 = md5_hash.hexdigest().upper()
            
            # 拼接信息
            info =  f"文件路径: {file_path}\n"
            info += f"文件 MD5: {md5}\n"
            info += f"文件大小: {file_size:,} 字节 ({size_mb:.2f} MB)"
        except Exception as e:
            info =  f"文件路径: {file_path}\n"
            info += f"解析失败: {e}"
        
        return info

    def extract_icon_internal(self):
        """
        在后台线程中解析APK图标。
        
        首先尝试使用androguard获取图标路径，然后从APK中提取图标数据。
        支持PNG、WebP等常见图标格式，以及XML矢量图标。
        
        Returns:
            tuple: (icon_data, error_message)
                - icon_data: 图标二进制数据
                - error_message: 错误信息，成功时为None
        """
        try:
            icon_list, error = self.extract_icon_by_androguard()
            if icon_list:
                app_logger.info(f"获取到图标路径列表: {icon_list}")
                self.apk_icon_info['icon_list'] = icon_list
            else:
                return None, error
            
            zip_file = self.parser.get_zip_file()
            files = self.parser.get_files_list()
            icon_path = ''
            
            # 1、遍历所有图标资源，如果有非xml的资源且在压缩包中存在，则直接加载这个文件，认为他就是应用图标。如果是xml文件就解析并生成图标。
            for ic_path in icon_list:
                if ic_path in files:
                    root, ext = os.path.splitext(ic_path)
                    if ext.lower() != '.xml':
                        icon_path = ic_path
                        self.apk_icon_info['icon_sure'] = True
                        break
                    elif ext.lower() == '.xml':
                        # 使用 XmlIconParser 解析 XML 图标，解析得到图片文件数据，可以直接返回
                        xml_parser = XmlIconParser(zip_file, ic_path, self.parser)
                        icon_data = xml_parser.get_icon_data()
                        if icon_data:
                            self.apk_icon_info['icon_path'] = ic_path
                            self.apk_icon_info['icon_sure'] = xml_parser.get_icon_sure()
                            # 清理 XmlIconParser 释放内存
                            xml_parser.cleanup()
                            return icon_data, None
                        # 清理 XmlIconParser 释放内存
                        xml_parser.cleanup()
            # 2、如果上述文件都不存在，则修改资源后缀名为png，如果存在该后缀名的资源，则认为他就是应用图标
            if icon_path == '':
                for ic_path in icon_list:
                    root, ext = os.path.splitext(ic_path)
                    new_ic_path = root + '.png'
                    if ext != '.png' and new_ic_path in files:
                        self.apk_icon_info['icon_sure'] = False
                        icon_path = new_ic_path
                        break
            # 3、如果还是都不存在，则修改资源后缀名为webp，如果存在该后缀名的资源，则认为他就是应用图标
            if icon_path == '':
                for ic_path in icon_list:
                    root, ext = os.path.splitext(ic_path)
                    new_ic_path = root + '.webp'
                    if ext != '.webp' and new_ic_path in files:
                        self.apk_icon_info['icon_sure'] = False
                        icon_path = new_ic_path
                        break
            # 4、如果存在图片格式的文件，则加载该资源文件
            if icon_path != '':
                self.apk_icon_info['icon_path'] = icon_path
                with zip_file.open(icon_path) as f:
                    return f.read(), None
            
            
            # 5、根据文件名进行模糊查找，确定文件位置
            icon_list.append("ic_launcher.png")    # 将 ic_launcher 添加进去，最终也查找这个默认图标文件名。
            map_list = ['-xxxhdpi', '-xxhdpi', '-xhdpi', '-hdpi', '-mdpi', '-ldpi', '-tvdpi', '-nodpi', '-anydpi']
            new_file_list = []
            for ic_path in icon_list:
                ic_base_name = os.path.basename(ic_path)
                ic_filename, ic_ext = os.path.splitext(ic_base_name)
                for file_path in files:
                    if f"/{ic_filename}." in file_path and (file_path.startswith('res/mipmap') or file_path.startswith('res/drawable')):
                        root, ext = os.path.splitext(file_path)
                        if ext in [".png", ".webp"]:
                            new_file_list.append(file_path)
            
            ## 5、对筛选出来的文件路径，按照分辨率提取
            if new_file_list:
                for mm in map_list:
                    for file_path in new_file_list:
                        if mm in file_path:
                            icon_path = file_path
                            self.apk_icon_info['icon_sure'] = False
                            self.apk_icon_info['icon_path'] = icon_path
                            with zip_file.open(icon_path) as f:
                                return f.read(), None
            
            return None, None    # 由前台处理的函数进行处理此种情况
        
        except Exception as e:
            return None, f"提取图标失败: {str(e)}"


    def parse_apk_info_with_androguard(self):
        """
        使用androguard库解析APK基本信息。
        
        解析包名、版本信息、SDK版本、应用名、权限等信息。
        
        Returns:
            tuple: (success, error_message)
                - success: 解析是否成功
                - error_message: 错误信息，成功时为空字符串
        """
        try:
            # 使用统一的解析器获取 CustomAPK 实例
            apk_obj = self.parser.get_custom_apk()
            
            # 检查 APK 是否有效
            if not apk_obj.is_valid_APK():
                return False, "无效的 APK 文件"
            
            # 解析包名
            self.apk_info['package_name'] = apk_obj.get_package() or ""
            
            # 解析版本信息
            self.apk_info['version_code'] = apk_obj.get_androidversion_code() or ""
            self.apk_info['version_name'] = apk_obj.get_androidversion_name() or ""
            
            # 解析 SDK 版本
            self.apk_info['min_sdk_version'] = apk_obj.get_min_sdk_version() or ""
            self.apk_info['target_sdk_version'] = apk_obj.get_target_sdk_version() or ""
            self.apk_info['compile_sdk_version'] = apk_obj.get_compile_sdk_version() or ""
            self.apk_info['build_sdk_version'] = apk_obj.get_build_sdk_version() or ""
            if not self.apk_info['compile_sdk_version']:    # 若 compile_sdk 不存在，则使用 build_sdk
                self.apk_info['compile_sdk_version'] = self.apk_info['build_sdk_version']
            
            # 解析应用名，如果不存在中文名，则中文名和默认应用名保持一致
            self.apk_info['app_name'] = apk_obj.get_app_name() or ""
            localized_name = apk_obj.get_app_name_zh()
            self.apk_info['chinese_app_name'] = localized_name if localized_name else self.apk_info['app_name']
            
            # 解析权限
            permissions = apk_obj.get_permissions()
            self.apk_info['permissions'] = list(set(permissions)) if permissions else []
            
            return True, ""
            
        except Exception as e:
            return False, f"androguard 解析失败: {str(e)}"

    def extract_icon_by_androguard(self):
        """
        通过androguard库获取应用图标路径。
        
        使用CustomAPK的get_app_icon方法获取图标文件路径，
        支持多种DPI密度的图标选择。
        
        Returns:
            tuple: (icon_list, error_message)
                - icon_list: 图标路径列表
                - error_message: 错误信息，成功时为None
        """
        try:
            apk = self.parser.get_custom_apk()
            # icon_path = apk.get_app_icon(max_dpi=60000)    # 参考 androguard.core.apk 源码，不优先使用 anydpi 和 nodpi 分辨率
            icon_path = apk.get_app_icon()    # 参考 androguard.core.apk 源码，优先使用 anydpi 和 nodpi 分辨率
            if icon_path:
                app_logger.info(f"获取到的图标路径: {icon_path}")
                icon_list = [icon_path]
                return icon_list, None
            return None, "androguard未找到应用图标"
        except Exception as e:
            import traceback
            app_logger.error(traceback.format_exc())
            return None, f"androguard提取图标失败: {e}"

# ============================================================================
# 自定义UI控件类
# ============================================================================

# 自定义表格类，继承 QTableWidget
class CustomTableWidget(QTableWidget):
    """
    自定义表格控件，继承自QTableWidget。
    
    重写了minimumSizeHint方法，解决表格控件无法缩小到很小尺寸的问题。
    适用于需要灵活调整大小的界面布局。
    """
    
    def minimumSizeHint(self):
        """
        返回自定义的最小尺寸提示。
        
        Returns:
            QSize: 最小尺寸，设置为20x20像素
        """
        return QSize(20, 20)

# 自定义文本类，继承 QTextEdit
class CustomTextEdit(QTextEdit):
    """
    自定义文本编辑控件，继承自QTextEdit。
    
    重写了minimumSizeHint方法，解决文本控件无法缩小到很小尺寸的问题。
    适用于需要灵活调整大小的界面布局。
    """
    
    def minimumSizeHint(self):
        """
        返回自定义的最小尺寸提示。
        
        Returns:
            QSize: 最小尺寸，设置为20x20像素
        """
        return QSize(20, 20)


# 自定义表格类，继承 QTableWidget
class appTableWidget(QTableWidget):
    """
    应用表格控件，继承自QTableWidget。
    
    提供可自定义的sizeHint，用于控制表格的初始显示高度。
    主要用于显示APK信息的应用基本信息和权限信息表格。
    
    Attributes:
        _init_Hint_height: 初始高度提示值
    """
    
    def __init__(self, init_height=600, parent=None):
        """
        初始化应用表格控件。
        
        Args:
            init_height: 初始高度提示值，默认600像素
            parent: 父控件
        """
        super().__init__(parent)
        self._init_Hint_height = init_height

    def sizeHint(self):
        """
        返回控件的尺寸提示。
        
        Returns:
            QSize: 包含原始宽度和自定义高度的尺寸
        """
        original_hint = super().sizeHint()
        return QSize(original_hint.width(), self._init_Hint_height)

    def minimumSizeHint(self):
        """
        返回控件的最小尺寸提示。
        
        Returns:
            QSize: 最小尺寸，设置为20x20像素
        """
        return QSize(20, 20)


# 自定义可点击标签类
class ClickableLabel(QLabel):
    """
    可点击的标签控件，继承自QLabel。
    
    用于显示应用图标并响应点击事件，点击后可显示原图。
    支持鼠标悬停提示和点击光标变化。
    
    Signals:
        clicked: 点击时发出的信号
    
    Attributes:
        _original_pixmap: 原始像素图（用于显示原图）
        _has_icon: 是否有有效图标
    """
    
    clicked = pyqtSignal()
    
    def __init__(self, parent=None):
        """
        初始化可点击标签。
        
        Args:
            parent: 父控件
        """
        super().__init__(parent)
        self._original_pixmap = None
        self._has_icon = False
    
    def setOriginalPixmap(self, pixmap):
        """
        设置原始像素图。
        
        Args:
            pixmap: QPixmap对象，设置为None时清除图标
        """
        self._original_pixmap = pixmap
        self._has_icon = pixmap is not None and not pixmap.isNull()
        self._update_cursor()
    
    def getOriginalPixmap(self):
        """
        获取原始像素图。
        
        Returns:
            QPixmap: 原始像素图对象
        """
        return self._original_pixmap
    
    def _update_cursor(self):
        """
        更新鼠标光标样式。
        
        有图标时显示手型光标，无图标时恢复默认光标。
        """
        if self._has_icon:
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.unsetCursor()
    
    def mousePressEvent(self, event):
        """
        处理鼠标点击事件。
        
        左键点击有效图标时发出clicked信号。
        
        Args:
            event: QMouseEvent鼠标事件对象
        """
        if self._has_icon and event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
    
    def enterEvent(self, event):
        """
        处理鼠标进入事件。
        
        有图标时显示"点击查看原图"提示。
        
        Args:
            event: QEvent事件对象
        """
        if self._has_icon:
            self.setToolTip("点击查看原图")
        else:
            self.setToolTip("")
        super().enterEvent(event)


# 图标弹出窗口类
class IconPopupWindow(QWidget):
    """
    图标弹出窗口控件，用于显示原始尺寸的应用图标。
    
    无边框的弹出窗口，点击窗口或其他位置时自动关闭。
    
    Attributes:
        image_label: 显示图片的标签控件
    """
    
    def __init__(self, pixmap, parent=None):
        """
        初始化图标弹出窗口。
        
        Args:
            pixmap: 要显示的QPixmap图片
            parent: 父控件
        """
        super().__init__(parent)
        
        self.setWindowFlags(
            Qt.Popup |  # 弹出窗口，点击其他位置自动关闭
            Qt.FramelessWindowHint |  # 无边框
            Qt.NoDropShadowWindowHint  # 无阴影
        )
        self.setAttribute(Qt.WA_TranslucentBackground)  # 透明背景
        self.setAttribute(Qt.WA_ShowWithoutActivating)  # 显示时不激活
        self.setAttribute(Qt.WA_DeleteOnClose)  # 关闭时自动删除
        
        # 创建布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建标签显示图片
        self.image_label = QLabel()
        self.image_label.setPixmap(pixmap)
        self.image_label.setAlignment(Qt.AlignCenter)
        
        layout.addWidget(self.image_label)
        
        # 设置窗口大小
        self.adjustSize()
    
    def mousePressEvent(self, event):
        """
        处理鼠标点击事件，点击窗口时关闭。
        
        Args:
            event: QMouseEvent鼠标事件对象
        """
        if event.button() == Qt.LeftButton:
            self.close()
        super().mousePressEvent(event)
    
    def cleanup(self):
        """
        清理资源，释放内存。
        
        清空pixmap等占用内存的资源。
        """
        # 清理图像标签的pixmap
        if self.image_label:
            self.image_label.setPixmap(QPixmap())
            self.image_label.clear()
    
    def closeEvent(self, event):
        """
        处理窗口关闭事件，清理资源。
        
        Args:
            event: QCloseEvent关闭事件对象
        """
        self.cleanup()
        # 调用父类的关闭事件
        super().closeEvent(event)
    
    def hideEvent(self, event):
        """
        处理窗口隐藏事件，清理资源。
        
        Qt.Popup 窗口在点击外部时会触发 hide 而不是 close，
        所以需要在这里也进行清理。
        
        Args:
            event: QHideEvent隐藏事件对象
        """
        self.cleanup()
        super().hideEvent(event)
    
    def show_at_position(self, global_pos):
        """
        在指定位置显示窗口。
        
        窗口居中于指定位置，并确保不超出屏幕边界。
        
        Args:
            global_pos: QPoint全局坐标位置
        """
        # 计算窗口位置，使其居中于鼠标位置
        size = self.size()
        x = global_pos.x() - size.width() // 2
        y = global_pos.y() - size.height() // 2
        
        # 确保窗口在屏幕内
        screen = QApplication.primaryScreen().geometry()
        if x < screen.left():
            x = screen.left()
        elif x + size.width() > screen.right():
            x = screen.right() - size.width()
        if y < screen.top():
            y = screen.top()
        elif y + size.height() > screen.bottom():
            y = screen.bottom() - size.height()
        
        self.move(x, y)
        self.show()


# ============================================================================
# ApkHelper - 主窗口类
# ============================================================================
class ApkHelper(QMainWindow):
    """
    APK文件信息解析工具主窗口类。
    
    提供APK文件的解析、显示和信息导出功能，包括：
    - 应用基本信息（包名、版本、SDK版本等）
    - 应用图标显示和保存
    - 权限信息及中文翻译
    - 签名信息及证书哈希比较
    - 文件信息（大小、MD5等）
    
    支持拖拽APK文件到窗口进行解析，支持文件关联设置。
    
    Attributes:
        version: 程序版本号
        sdk_version_map: SDK版本与Android版本映射表
        permission_map: 权限名称中文映射表
        dangerous_permissions: 危险权限集合
        current_apk_path: 当前解析的APK文件路径
        apk_info: APK基本信息字典
        apk_icon_info: 图标信息字典
        signature_info: 签名信息文本
        file_info: 文件信息文本
        certs: 证书数据列表
    """
    
    def __init__(self):
        """
        初始化APK Helper主窗口。
        
        设置窗口标题、大小、位置，初始化SDK版本映射表、权限映射表，
        创建UI界面和控件，设置初始状态。
        """
        super().__init__()
        # 定义程序版本信息
        self.version = b_ver
        self.setWindowTitle(f"APK文件信息解析工具-APK Helper {self.version}")
        self.setGeometry(100, 100, 400, 580)
        
        # 让窗口显示在屏幕中心
        self.center_window()
        
        # 设置窗口接受拖拽事件
        self.setAcceptDrops(True)

        # SDK版本与安卓版本映射表
        self.sdk_version_map = {
            # 参考Android官方文档: https://developer.android.google.cn/tools/releases/platforms
            "1": "Android 1.0",
            "2": "Android 1.1",
            "3": "Android 1.5 - Cupcake",
            "4": "Android 1.6 - Donut",
            "5": "Android 2.0 - Eclair",
            "6": "Android 2.0.1 - Eclair",
            "7": "Android 2.1 - Eclair",
            "8": "Android 2.2 - Froyo",
            "9": "Android 2.3 - Gingerbread",
            "10": "Android 2.3.3 - Gingerbread",
            "11": "Android 3.0 - Honeycomb",
            "12": "Android 3.1 - Honeycomb",
            "13": "Android 3.2 - Honeycomb",
            "14": "Android 4.0 - Ice Cream Sandwich",
            "15": "Android 4.0.3 - Ice Cream Sandwich",
            "16": "Android 4.1 - Jelly Bean",
            "17": "Android 4.2 - Jelly Bean",
            "18": "Android 4.3 - Jelly Bean",
            "19": "Android 4.4 - KitKat",
            "20": "Android 4.4W - KitKat Wear",
            "21": "Android 5.0 - Lollipop",
            "22": "Android 5.1 - Lollipop",
            "23": "Android 6.0 - Marshmallow",
            "24": "Android 7.0 - Nougat",
            "25": "Android 7.1 - Nougat",
            "26": "Android 8.0 - Oreo",
            "27": "Android 8.1 - Oreo",
            "28": "Android 9.0 - Pie",
            "29": "Android 10",
            "30": "Android 11",
            "31": "Android 12",
            "32": "Android 12L",
            "33": "Android 13",
            "34": "Android 14",
            "35": "Android 15",
            "36": "Android 16",
            "37": "Android 17",
        }

        # 安卓权限中文映射表
        self.permission_map = {
            # ==================== 危险权限 (Dangerous Permissions) ====================
            # 参考Android官方文档: https://developer.android.com/guide/topics/permissions/dangerous-permissions
            "android.permission.READ_CALENDAR": "读取日历",
            "android.permission.WRITE_CALENDAR": "写入日历",
            "android.permission.CAMERA": "相机",
            "android.permission.READ_CONTACTS": "读取联系人",
            "android.permission.WRITE_CONTACTS": "写入联系人",
            "android.permission.GET_ACCOUNTS": "获取账户列表",
            "android.permission.ACCESS_FINE_LOCATION": "精确位置",
            "android.permission.ACCESS_COARSE_LOCATION": "粗略位置",
            "android.permission.ACCESS_BACKGROUND_LOCATION": "后台位置访问",
            "android.permission.ACCESS_MEDIA_LOCATION": "访问媒体位置",
            "android.permission.RECORD_AUDIO": "录音",
            "android.permission.READ_PHONE_STATE": "读取电话状态",
            "android.permission.CALL_PHONE": "拨打电话",
            "android.permission.READ_CALL_LOG": "读取通话记录",
            "android.permission.WRITE_CALL_LOG": "写入通话记录",
            "android.permission.ADD_VOICEMAIL": "添加语音邮件",
            "android.permission.USE_SIP": "使用SIP服务",
            "android.permission.PROCESS_OUTGOING_CALLS": "处理拨出电话",
            "android.permission.ANSWER_PHONE_CALLS": "接听电话",
            "android.permission.BODY_SENSORS": "身体传感器",
            "android.permission.BODY_SENSORS_BACKGROUND": "后台身体传感器",
            "android.permission.ACTIVITY_RECOGNITION": "活动识别",
            "android.permission.SEND_SMS": "发送短信",
            "android.permission.RECEIVE_SMS": "接收短信",
            "android.permission.READ_SMS": "读取短信",
            "android.permission.RECEIVE_WAP_PUSH": "接收WAP推送",
            "android.permission.RECEIVE_MMS": "接收彩信",
            "android.permission.READ_EXTERNAL_STORAGE": "读取外部存储",
            "android.permission.WRITE_EXTERNAL_STORAGE": "写入外部存储",
            "android.permission.READ_MEDIA_IMAGES": "读取媒体图片",
            "android.permission.READ_MEDIA_VIDEO": "读取媒体视频",
            "android.permission.READ_MEDIA_AUDIO": "读取媒体音频",
            "android.permission.POST_NOTIFICATIONS": "发送通知",
            "android.permission.NEARBY_WIFI_DEVICES": "附近WiFi设备",
            "android.permission.BLUETOOTH_SCAN": "蓝牙扫描",
            "android.permission.BLUETOOTH_CONNECT": "蓝牙连接",
            "android.permission.BLUETOOTH_ADVERTISE": "蓝牙广播",
            "android.permission.UWB_RANGING": "超宽带测距",
            
            # ==================== 普通权限 (Normal Permissions) ====================
            "android.permission.INTERNET": "互联网访问",
            "android.permission.ACCESS_NETWORK_STATE": "访问网络状态",
            "android.permission.ACCESS_WIFI_STATE": "访问WiFi状态",
            "android.permission.CHANGE_WIFI_STATE": "改变WiFi状态",
            "android.permission.WAKE_LOCK": "唤醒锁",
            "android.permission.VIBRATE": "振动",
            "android.permission.RECEIVE_BOOT_COMPLETED": "接收开机完成广播",
            "android.permission.INSTALL_SHORTCUT": "安装快捷方式",
            "android.permission.UNINSTALL_SHORTCUT": "卸载快捷方式",
            "android.permission.SYSTEM_ALERT_WINDOW": "显示系统警报窗口",
            "android.permission.GET_TASKS": "获取任务信息",
            "android.permission.KILL_BACKGROUND_PROCESSES": "杀死后台进程",
            "android.permission.SET_WALLPAPER": "设置壁纸",
            "android.permission.SET_WALLPAPER_HINTS": "设置壁纸提示",
            "android.permission.BLUETOOTH": "蓝牙访问",
            "android.permission.BLUETOOTH_ADMIN": "蓝牙管理",
            "android.permission.BLUETOOTH_PRIVILEGED": "蓝牙特权",
            "android.permission.NFC": "近场通信",
            "android.permission.NFC_TRANSACTION_EVENT": "NFC交易事件",
            "android.permission.ACCESS_LOCATION_EXTRA_COMMANDS": "访问位置额外命令",
            "android.permission.BATTERY_STATS": "电池统计",
            "android.permission.READ_SYNC_SETTINGS": "读取同步设置",
            "android.permission.WRITE_SYNC_SETTINGS": "写入同步设置",
            "android.permission.AUTHENTICATE_ACCOUNTS": "账户认证",
            "android.permission.MANAGE_ACCOUNTS": "管理账户",
            "android.permission.USE_CREDENTIALS": "使用凭证",
            "android.permission.MODIFY_AUDIO_SETTINGS": "修改音频设置",
            "android.permission.READ_PHONE_NUMBERS": "读取电话号码",
            "android.permission.ACCESS_NOTIFICATION_POLICY": "访问通知策略",
            "android.permission.REQUEST_INSTALL_PACKAGES": "请求安装应用",
            "android.permission.REQUEST_DELETE_PACKAGES": "请求卸载应用",
            "android.permission.USE_FULL_SCREEN_INTENT": "使用全屏Intent",
            "android.permission.SCHEDULE_EXACT_ALARM": "设置精确闹钟",
            "android.permission.USE_EXACT_ALARM": "使用精确闹钟",
            "android.permission.WRITE_SETTINGS": "写入系统设置",
            "android.permission.WRITE_SECURE_SETTINGS": "写入安全设置",
            "android.permission.CHANGE_NETWORK_STATE": "改变网络状态",
            "android.permission.ACCESS_WIMAX_STATE": "访问WiMAX状态",
            "android.permission.CHANGE_WIMAX_STATE": "改变WiMAX状态",
            "android.permission.REORDER_TASKS": "重新排序任务",
            "android.permission.GET_PACKAGE_SIZE": "获取包大小",
            "android.permission.CLEAR_APP_CACHE": "清除应用缓存",
            "android.permission.CLEAR_APP_USER_DATA": "清除应用数据",
            "android.permission.SET_TIME": "设置时间",
            "android.permission.SET_TIME_ZONE": "设置时区",
            "android.permission.SET_ALARM": "设置闹钟",
            "android.permission.ACCESS_SURFACE_FLINGER": "访问SurfaceFlinger",
            "android.permission.FLASHLIGHT": "闪光灯",
            "android.permission.DISABLE_KEYGUARD": "禁用键盘锁",
            "android.permission.GET_ACCOUNTS_PRIVILEGED": "获取账户（特权）",
            "android.permission.MANAGE_USB": "管理USB",
            "android.permission.ACCESS_KEYGUARD_SECURE_STORAGE": "访问键盘锁安全存储",
            "android.permission.INTERACT_ACROSS_USERS": "跨用户交互",
            "android.permission.INTERACT_ACROSS_USERS_FULL": "完全跨用户交互",
            "android.permission.MANAGE_USERS": "管理用户",
            "android.permission.CREATE_USERS": "创建用户",
            "android.permission.READ_PROFILE": "读取个人资料",
            "android.permission.WRITE_PROFILE": "写入个人资料",
            "android.permission.READ_SOCIAL_STREAM": "读取社交信息流",
            "android.permission.WRITE_SOCIAL_STREAM": "写入社交信息流",
            "android.permission.READ_USER_DICTIONARY": "读取用户词典",
            "android.permission.WRITE_USER_DICTIONARY": "写入用户词典",
            "android.permission.MEDIA_CONTENT_CONTROL": "媒体内容控制",
            "android.permission.EXPAND_STATUS_BAR": "展开状态栏",
            "android.permission.DOWNLOAD_WITHOUT_NOTIFICATION": "无通知下载",
            "android.permission.BROADCAST_STICKY": "发送粘性广播",
            "android.permission.BROADCAST_SMS": "广播短信",
            "android.permission.MODIFY_PHONE_STATE": "修改电话状态",
            "android.permission.READ_PRECISE_PHONE_STATE": "读取精确电话状态",
            "android.permission.ACCESS_VOICE_INTERACTION_SERVICE": "访问语音交互服务",
            "android.permission.REQUEST_COMPANION_RUN_IN_BACKGROUND": "请求配套应用后台运行",
            "android.permission.REQUEST_COMPANION_USE_DATA_IN_BACKGROUND": "请求配套应用后台使用数据",
            "android.permission.REQUEST_COMPANION_START_FOREGROUND_SERVICES_FROM_BACKGROUND": "请求配套应用后台启动前台服务",
            "android.permission.REQUEST_OBSERVE_COMPANION_DEVICE_PRESENCE": "请求观察配套设备存在",
            "android.permission.MANAGE_EXTERNAL_STORAGE": "管理外部存储",
            "android.permission.MANAGE_MEDIA": "管理媒体",
            "android.permission.QUERY_ALL_PACKAGES": "查询所有应用",
            "android.permission.SUSPEND_APPS": "暂停应用",
            "android.permission.TRANSMIT_IR": "红外传输",
            "android.permission.USE_BIOMETRIC": "使用生物识别",
            "android.permission.USE_FINGERPRINT": "使用指纹",
            "android.permission.ACCESS_FINGERPRINT": "访问指纹",
            "android.permission.ACCESS_FINE_LOCATION_EXTRA_COMMANDS": "访问精确位置额外命令",
            "android.permission.CONTROL_LOCATION_UPDATES": "控制位置更新",
            "android.permission.LOCATION_HARDWARE": "定位硬件",
            "android.permission.ACCESS_CHECKIN_PROPERTIES": "访问签入属性",
            "android.permission.ACCESS_FILE_LOCATION": "访问文件位置",
            "android.permission.ACCESS_GPS": "访问GPS",
            "android.permission.ACCESS_IMS_CALL_SERVICE": "访问IMS通话服务",
            "android.permission.ACCESS_IMS_SERVICE": "访问IMS服务",
            "android.permission.ACCESS_INSTANT_APPS": "访问免安装应用",
            "android.permission.ACCESS_INPUT_FLINGER": "访问输入Flinger",
            "android.permission.ACCESS_NETWORK_CONDITIONS": "访问网络条件",
            "android.permission.ACCESS_NOTIFICATIONS": "访问通知",
            "android.permission.ACCESS_PDB_STATE": "访问PDB状态",
            "android.permission.ACCESS_REMOTE_DISPLAY": "访问远程显示",
            "android.permission.ACCESS_RESOURCEMANAGER": "访问资源管理器",
            "android.permission.ACCESS_SIGNAL_STRENGTH": "访问信号强度",
            "android.permission.ACCESS_WIFI_PERF": "访问WiFi性能",
            "android.permission.ACCESS_WIFI_VIRTUAL_INTERFACE": "访问WiFi虚拟接口",
            "android.permission.ACCOUNT_MANAGER": "账户管理器",
            "android.permission.ACTIVITY_ASPECTS": "活动方面",
            "android.permission.AIDL_CAPABILITY": "AIDL能力",
            "android.permission.AMBIENT_WALLPAPER": "动态壁纸",
            "android.permission.APK_VERIFICATION_AGENT": "APK验证代理",
            "android.permission.APK_VERIFICATION_SERVICE": "APK验证服务",
            "android.permission.APP_INSTALL_LOCATION": "应用安装位置",
            "android.permission.APP_OPS_ADMIN": "应用操作管理",
            "android.permission.APP_OPS_STATS": "应用操作统计",
            "android.permission.APPWIDGET_LIST": "应用小部件列表",
            "android.permission.ASSISTANT": "助手",
            "android.permission.AUDIO_ACCESSIBILITY_VOLUME": "音频无障碍音量",
            "android.permission.AUDIO_MONITORING": "音频监控",
            "android.permission.AUDIO_TRIGGER": "音频触发",
            "android.permission.AUTOMOTIVE_DISPLAY_POWER": "车载显示电源",
            "android.permission.AUTOMOTIVE_MEDIA": "车载媒体",
            "android.permission.AUTOMOTIVE_NAVIGATION": "车载导航",
            "android.permission.AUTOMOTIVE_PROJECTION": "车载投影",
            "android.permission.AUTOMOTIVE_TELEMETRY": "车载遥测",
            "android.permission.AUTOMOTIVE_VEHICLE_HARDWARE": "车载硬件",
            "android.permission.AUTOMOTIVE_VENDOR_EXTENSION": "车载厂商扩展",
            "android.permission.BACKUP": "备份",
            "android.permission.BIND_ACCESSIBILITY_SERVICE": "绑定无障碍服务",
            "android.permission.BIND_APPWIDGET": "绑定应用小部件",
            "android.permission.BIND_AUTOFILL_SERVICE": "绑定自动填充服务",
            "android.permission.BIND_CALL_REDIRECTION_SERVICE": "绑定呼叫重定向服务",
            "android.permission.BIND_CALL_SCREENING_SERVICE": "绑定呼叫筛选服务",
            "android.permission.BIND_CARRIER_MESSAGING_CLIENT_SERVICE": "绑定运营商消息客户端服务",
            "android.permission.BIND_CARRIER_MESSAGING_SERVICE": "绑定运营商消息服务",
            "android.permission.BIND_CARRIER_SERVICES": "绑定运营商服务",
            "android.permission.BIND_CHOOSER_TARGET_SERVICE": "绑定选择器目标服务",
            "android.permission.BIND_COMPANION_DEVICE_SERVICE": "绑定配套设备服务",
            "android.permission.BIND_CONDITION_PROVIDER_SERVICE": "绑定条件提供者服务",
            "android.permission.BIND_CONNECTION_SERVICE": "绑定连接服务",
            "android.permission.BIND_CONTROLS": "绑定控制",
            "android.permission.BIND_DEVICE_ADMIN": "绑定设备管理员",
            "android.permission.BIND_DIRECTORY_SEARCH": "绑定目录搜索",
            "android.permission.BIND_DISPLAYHASH_SERVICE": "绑定显示哈希服务",
            "android.permission.BIND_DREAM_SERVICE": "绑定屏保服务",
            "android.permission.BIND_INCALL_SERVICE": "绑定通话服务",
            "android.permission.BIND_INPUT_METHOD": "绑定输入法",
            "android.permission.BIND_JOB_SERVICE": "绑定作业服务",
            "android.permission.BIND_KEYGUARD_APPWIDGET": "绑定键盘锁小部件",
            "android.permission.BIND_MIDI_DEVICE_SERVICE": "绑定MIDI设备服务",
            "android.permission.BIND_NFC_SERVICE": "绑定NFC服务",
            "android.permission.BIND_NOTIFICATION_LISTENER_SERVICE": "绑定通知监听器服务",
            "android.permission.BIND_PRINT_SERVICE": "绑定打印服务",
            "android.permission.BIND_QUICK_ACCESS_WALLET_SERVICE": "绑定快速访问钱包服务",
            "android.permission.BIND_QUICK_SETTINGS_TILE": "绑定快速设置磁贴",
            "android.permission.BIND_REMOTEVIEWS": "绑定远程视图",
            "android.permission.BIND_ROUTE_PROVIDER": "绑定路由提供者",
            "android.permission.BIND_SCREENING_SERVICE": "绑定筛选服务",
            "android.permission.BIND_TELECOM_CONNECTION_SERVICE": "绑定电信连接服务",
            "android.permission.BIND_TEXT_SERVICE": "绑定文本服务",
            "android.permission.BIND_TV_INPUT": "绑定电视输入",
            "android.permission.BIND_VOICE_INTERACTION": "绑定语音交互",
            "android.permission.BIND_VOICE_INTERACTION_SERVICE": "绑定语音交互服务",
            "android.permission.BIND_VPN_SERVICE": "绑定VPN服务",
            "android.permission.BIND_WALLPAPER": "绑定壁纸",
            "android.permission.BLUETOOTH_MAP": "蓝牙MAP",
            "android.permission.BLUETOOTH_PRIVILEGED": "蓝牙特权",
            "android.permission.BRICK": "变砖",
            "android.permission.BROADCAST_CALENDAR": "广播日历",
            "android.permission.BROADCAST_CONTENT_NOTIFICATIONS": "广播内容通知",
            "android.permission.BROADCAST_NETWORK": "广播网络",
            "android.permission.BROADCAST_PACKAGE_REMOVED": "广播包已移除",
            "android.permission.BROADCAST_PHONE_STATE": "广播电话状态",
            "android.permission.BROADCAST_PREFERRED": "广播首选",
            "android.permission.BROADCAST_WAP_PUSH": "广播WAP推送",
            "android.permission.CABLING_PROVIDER": "布线提供者",
            "android.permission.CALL_COMPANION_APP": "呼叫配套应用",
            "android.permission.CALL_PRIVILEGED": "呼叫特权",
            "android.permission.CAMERA_DISABLE_TRANSPARENT": "相机禁用透明",
            "android.permission.CAMERA_SEND_SYSTEM_EVENTS": "相机发送系统事件",
            "android.permission.CAPTURE_AUDIO_HOTWORD": "捕获音频热词",
            "android.permission.CAPTURE_AUDIO_OUTPUT": "捕获音频输出",
            "android.permission.CAPTURE_SECURE_VIDEO_OUTPUT": "捕获安全视频输出",
            "android.permission.CAPTURE_TV_INPUT": "捕获电视输入",
            "android.permission.CAPTURE_VIDEO_OUTPUT": "捕获视频输出",
            "android.permission.CARRIER_FILTER_SMS": "运营商过滤短信",
            "android.permission.CARRIER_PRIVILEGED": "运营商特权",
            "android.permission.CHANGE_APP_IDLE_STATE": "改变应用空闲状态",
            "android.permission.CHANGE_COMPONENT_ENABLED_STATE": "改变组件启用状态",
            "android.permission.CHANGE_CONFIGURATION": "改变配置",
            "android.permission.CHANGE_DEVICE_IDLE_TEMP_WHITELIST": "改变设备空闲临时白名单",
            "android.permission.CHANGE_DISPLAY_SIZE": "改变显示大小",
            "android.permission.CHANGE_HARDWARE": "改变硬件",
            "android.permission.CHANGE_INPUT_METHOD": "改变输入法",
            "android.permission.CHANGE_OVERLAY_PACKAGES": "改变悬浮窗包",
            "android.permission.CHANGE_SCREEN_MODE": "改变屏幕模式",
            "android.permission.CHANGE_USB_DEBUG_MODE": "改变USB调试模式",
            "android.permission.CHANGE_WIFI_STATE": "改变WiFi状态",
            "android.permission.CHANGE_WIFI_MULTICAST_STATE": "改变WiFi多播状态",
            "android.permission.CHANGE_ZTE_SCREEN_MODE": "改变中兴屏幕模式",
            "android.permission.CLEAR_APP_CACHE": "清除应用缓存",
            "android.permission.CLEAR_APP_USER_DATA": "清除应用数据",
            "android.permission.CONTROL_KEYGUARD": "控制键盘锁",
            "android.permission.CONTROL_POLICY_ACCESS": "控制策略访问",
            "android.permission.CONTROL_VPN": "控制VPN",
            "android.permission.CONTROL_WIFI_DISPLAY": "控制WiFi显示",
            "android.permission.COPY_DATA_PROTECT": "复制数据保护",
            "android.permission.CONTENT_PROVIDER_DEBUG": "内容提供者调试",
            "android.permission.CONTROL_SYSTEM_DIALOGS": "控制系统对话框",
            "android.permission.CONTROL_VIBRATOR": "控制振动器",
            "android.permission.CONTROL_WAKE_LOCK": "控制唤醒锁",
            "android.permission.CREATE_THUMBNAIL": "创建缩略图",
            "android.permission.CREATE_USER": "创建用户",
            "android.permission.CREDENTIAL_MANAGER_QUERY_URI": "凭证管理器查询URI",
            "android.permission.CRYPT_KEEPER": "加密守护者",
            "android.permission.DELETE_CACHE_FILES": "删除缓存文件",
            "android.permission.DELETE_PACKAGES": "删除应用包",
            "android.permission.DEVICE_POWER": "设备电源",
            "android.permission.DIAGNOSTIC": "诊断",
            "android.permission.DISABLE_APP": "禁用应用",
            "android.permission.DISABLE_KEYGUARD": "禁用键盘锁",
            "android.permission.DISPATCH_NFC_MESSAGE": "分发NFC消息",
            "android.permission.DOMAIN_VERIFICATION_AGENT": "域名验证代理",
            "android.permission.DOWNLOAD_CACHE_NON_PURGEABLE": "下载缓存不可清除",
            "android.permission.DUMP": "转储",
            "android.permission.ENABLE_KEYGUARD": "启用键盘锁",
            "android.permission.ENTER_CAR_MODE": "进入车载模式",
            "android.permission.ENTER_CAR_MODE_PRIORITIZED": "优先进入车载模式",
            "android.permission.ESCAPE_EMBEDDED": "逃逸嵌入式",
            "android.permission.EXTERNAL_STORAGE": "外部存储",
            "android.permission.FACTORY_TEST": "工厂测试",
            "android.permission.FILTER_EVENTS": "过滤事件",
            "android.permission.FIND_LOCK_TARGET": "查找锁定目标",
            "android.permission.FOREGROUND_SERVICE": "前台服务",
            "android.permission.FORCE_BACK": "强制返回",
            "android.permission.FORCE_STOP_PACKAGES": "强制停止应用包",
            "android.permission.FRAME_STATS": "帧统计",
            "android.permission.FREEZE_SCREEN": "冻结屏幕",
            "android.permission.FULLSCREEN": "全屏",
            "android.permission.GET_ACCOUNTS": "获取账户",
            "android.permission.GET_ACCOUNTS_PRIVILEGED": "获取账户（特权）",
            "android.permission.GET_APP_OPS_STATS": "获取应用操作统计",
            "android.permission.GET_DETAILED_TASKS": "获取详细任务",
            "android.permission.GET_INTENT_SENDER_STATS": "获取Intent发送者统计",
            "android.permission.GET_PACKAGE_IMPORTANCE": "获取包重要性",
            "android.permission.GET_PACKAGE_SIZE": "获取包大小",
            "android.permission.GET_PASSWORD": "获取密码",
            "android.permission.GET_PROCESS_STATE_AND_OOM_SCORE": "获取进程状态和OOM分数",
            "android.permission.GET_RECOVERY_PROPERTY": "获取恢复属性",
            "android.permission.GET_SIGNATURES": "获取签名",
            "android.permission.GET_TOP_ACTIVITY_INFO": "获取顶部活动信息",
            "android.permission.GLOBAL_SEARCH": "全局搜索",
            "android.permission.GRANT_REVOKE_PERMISSIONS": "授予/撤销权限",
            "android.permission.GRANTS_RUNTIME_PERMISSIONS": "授予运行时权限",
            "android.permission.HARDWARE_TEST": "硬件测试",
            "android.permission.HIDE_NON_SYSTEM_OVERLAY_WINDOWS": "隐藏非系统悬浮窗",
            "android.permission.HOME_APP": "主屏幕应用",
            "android.permission.INCIDENT_REPORT": "事件报告",
            "android.permission.INJECT_EVENTS": "注入事件",
            "android.permission.INSTALL_LOCATION_PROVIDER": "安装位置提供者",
            "android.permission.INSTALL_PACKAGES": "安装应用包",
            "android.permission.INSTALL_PACKAGES_VERIFIER": "安装应用包验证器",
            "android.permission.INSTALL_SHORTCUT": "安装快捷方式",
            "android.permission.INSTANT_APP_FOREGROUND_SERVICE": "免安装应用前台服务",
            "android.permission.INTERNAL_SYSTEM_WINDOW": "内部系统窗口",
            "android.permission.INTERACT_ACROSS_USERS": "跨用户交互",
            "android.permission.INTERACT_ACROSS_USERS_FULL": "完全跨用户交互",
            "android.permission.INTERNAL_DEVELOPMENT": "内部开发",
            "android.permission.INTERNET": "互联网访问",
            "android.permission.INVOKE_CARRIER_SETUP": "调用运营商设置",
            "android.permission.KILL_UID": "杀死UID",
            "android.permission.KILL_BACKGROUND_PROCESSES": "杀死后台进程",
            "android.permission.LAUNCH_TRUSTED_AGENT": "启动可信代理",
            "android.permission.LOAD_RADIO_IMAGE": "加载无线图片",
            "android.permission.LOCAL_MAC_ADDRESS": "本地MAC地址",
            "android.permission.LOCK_DEVICE": "锁定设备",
            "android.permission.LOCK_UI": "锁定UI",
            "android.permission.LOOPER": "循环器",
            "android.permission.MANAGE_ACTIVITY_STACKS": "管理活动栈",
            "android.permission.MANAGE_APP_OPS": "管理应用操作",
            "android.permission.MANAGE_APP_OPS_MODES": "管理应用操作模式",
            "android.permission.MANAGE_AUDIO": "管理音频",
            "android.permission.MANAGE_BACKUP_SERVICE": "管理备份服务",
            "android.permission.MANAGE_BIOMETRIC": "管理生物识别",
            "android.permission.MANAGE_BLOCKED_NUMBERS": "管理黑名单号码",
            "android.permission.MANAGE_CARRIER_OEM_UNLOCK_STATE": "管理运营商OEM解锁状态",
            "android.permission.MANAGE_CARRIER_PROVISIONING": "管理运营商配置",
            "android.permission.MANAGE_CARRIER_SYSTEM": "管理运营商系统",
            "android.permission.MANAGE_COMPANION_DEVICES": "管理配套设备",
            "android.permission.MANAGE_CONTACTS": "管理联系人",
            "android.permission.MANAGE_CREDENTIALS": "管理凭证",
            "android.permission.MANAGE_DEVICE_ADMINS": "管理设备管理员",
            "android.permission.MANAGE_DEVICE_LOCK_STATE": "管理设备锁定状态",
            "android.permission.MANAGE_DEVICE_POLICY": "管理设备策略",
            "android.permission.MANAGE_DISPLAY": "管理显示",
            "android.permission.MANAGE_DOCUMENTS": "管理文档",
            "android.permission.MANAGE_DRM": "管理DRM",
            "android.permission.MANAGE_EXTERNAL_STORAGE": "管理外部存储",
            "android.permission.MANAGE_FINGERPRINT": "管理指纹",
            "android.permission.MANAGE_INPUT": "管理输入",
            "android.permission.MANAGE_IO": "管理IO",
            "android.permission.MANAGE_IME": "管理IME",
            "android.permission.MANAGE_MEDIA": "管理媒体",
            "android.permission.MANAGE_MEDIA_PROJECTION": "管理媒体投影",
            "android.permission.MANAGE_NETWORK": "管理网络",
            "android.permission.MANAGE_NOTIFICATIONS": "管理通知",
            "android.permission.MANAGE_OMX": "管理OMX",
            "android.permission.MANAGE_OWN_CALLS": "管理自己的呼叫",
            "android.permission.MANAGE_PACKAGES": "管理应用包",
            "android.permission.MANAGE_PEER_CONNECTIONS": "管理对等连接",
            "android.permission.MANAGE_PERMISSIONS": "管理权限",
            "android.permission.MANAGE_POWER": "管理电源",
            "android.permission.MANAGE_PROFILE_AND_DEVICE_OWNERS": "管理配置文件和设备所有者",
            "android.permission.MANAGE_PROJECTION": "管理投影",
            "android.permission.MANAGE_PROXY": "管理代理",
            "android.permission.MANAGE_RADIO": "管理无线电",
            "android.permission.MANAGE_RESOURCES": "管理资源",
            "android.permission.MANAGE_SENSORS": "管理传感器",
            "android.permission.MANAGE_SERIAL": "管理串口",
            "android.permission.MANAGE_SERVICE": "管理服务",
            "android.permission.MANAGE_SOUND_TRIGGER": "管理声音触发",
            "android.permission.MANAGE_STORAGE": "管理存储",
            "android.permission.MANAGE_SUBSCRIPTION": "管理订阅",
            "android.permission.MANAGE_SURFACE": "管理表面",
            "android.permission.MANAGE_SYSTEM": "管理系统",
            "android.permission.MANAGE_SYSTEM_DIALOGS": "管理系统对话框",
            "android.permission.MANAGE_SYSTEM_UI": "管理系统UI",
            "android.permission.MANAGE_TELEPHONY": "管理电话",
            "android.permission.MANAGE_TETHERING": "管理网络共享",
            "android.permission.MANAGE_TIME": "管理时间",
            "android.permission.MANAGE_USB": "管理USB",
            "android.permission.MANAGE_USER": "管理用户",
            "android.permission.MANAGE_VOICE_KEYPHRASES": "管理语音关键词",
            "android.permission.MANAGE_WALLPAPER": "管理壁纸",
            "android.permission.MANAGE_WIFI": "管理WiFi",
            "android.permission.MANAGE_WIFI_STATE": "管理WiFi状态",
            "android.permission.MANAGE_WINDOW": "管理窗口",
            "android.permission.MANAGE_WINDOW_SURFACES": "管理窗口表面",
            "android.permission.MASTER_CLEAR": "主清除",
            "android.permission.MEDIA_CONTENT_CONTROL": "媒体内容控制",
            "android.permission.MEDIA_RESOURCE_OVERLAY": "媒体资源覆盖",
            "android.permission.MOUNT_FORMAT_FILESYSTEMS": "挂载/格式化文件系统",
            "android.permission.MOUNT_UNMOUNT_FILESYSTEMS": "挂载/卸载文件系统",
            "android.permission.MOVE_PACKAGE": "移动应用包",
            "android.permission.NET_ADMIN": "网络管理员",
            "android.permission.NET_STATS": "网络统计",
            "android.permission.NETWORK": "网络",
            "android.permission.NFC": "近场通信",
            "android.permission.NFC_HANDOVER_STATUS": "NFC切换状态",
            "android.permission.NFC_PREFERRED_PAYMENT_INFO": "NFC首选支付信息",
            "android.permission.NFC_TRANSACTION_EVENT": "NFC交易事件",
            "android.permission.NOTIFICATION_LISTENER": "通知监听器",
            "android.permission.NOTIFY_SUSPEND_APPS": "通知暂停应用",
            "android.permission.OBSERVE_APP_USAGE": "观察应用使用",
            "android.permission.OBSERVE_SENSOR_PRIVACY": "观察传感器隐私",
            "android.permission.OPENTERA_SERVICE": "OpenTera服务",
            "android.permission.OPT_OUT_FROM_ZEN": "选择退出免打扰",
            "android.permission.OVERRIDE_WIFI_CONFIG": "覆盖WiFi配置",
            "android.permission.PACKAGE_USAGE_STATS": "应用使用统计",
            "android.permission.PACKAGE_VERIFICATION_AGENT": "应用包验证代理",
            "android.permission.PARTNER_PROVIDER_ACCESS": "合作伙伴提供者访问",
            "android.permission.PERSISTENT_ACTIVITY": "持久活动",
            "android.permission.PHONE_CALL_STATE_MONITOR": "电话呼叫状态监控",
            "android.permission.PROCESS_CAMERA_USE": "处理相机使用",
            "android.permission.PROCESS_PHONE_NUMBERS": "处理电话号码",
            "android.permission.PROVIDE_TRUST_AGENT": "提供可信代理",
            "android.permission.QUERY_DO_NOT_DISTURB": "查询免打扰",
            "android.permission.QUERY_PACKAGES": "查询应用包",
            "android.permission.READ_CALENDAR": "读取日历",
            "android.permission.READ_CALL_LOG": "读取通话记录",
            "android.permission.READ_CELL_BROADCASTS": "读取小区广播",
            "android.permission.READ_CONTACTS": "读取联系人",
            "android.permission.READ_EXTERNAL_STORAGE": "读取外部存储",
            "android.permission.READ_FRAME_BUFFER": "读取帧缓冲",
            "android.permission.READ_HISTORY_BOOKMARKS": "读取历史书签",
            "android.permission.READ_HOME_APP_SEARCH_DATA": "读取主屏幕应用搜索数据",
            "android.permission.READ_INPUT_STATE": "读取输入状态",
            "android.permission.READ_LOGS": "读取日志",
            "android.permission.READ_MEDIA_IMAGES": "读取媒体图片",
            "android.permission.READ_MEDIA_VIDEO": "读取媒体视频",
            "android.permission.READ_MEDIA_AUDIO": "读取媒体音频",
            "android.permission.READ_NETWORK_USAGE_HISTORY": "读取网络使用历史",
            "android.permission.READ_PHONE_NUMBERS": "读取电话号码",
            "android.permission.READ_PHONE_STATE": "读取电话状态",
            "android.permission.READ_PRIVILEGED_PHONE_STATE": "读取特权电话状态",
            "android.permission.READ_PROFILE": "读取个人资料",
            "android.permission.READ_SMS": "读取短信",
            "android.permission.READ_SOCIAL_STREAM": "读取社交信息流",
            "android.permission.READ_SYNC_SETTINGS": "读取同步设置",
            "android.permission.READ_SYNC_STATS": "读取同步统计",
            "android.permission.READ_USER_DICTIONARY": "读取用户词典",
            "android.permission.READ_VOICEMAIL": "读取语音邮件",
            "android.permission.REBOOT": "重启",
            "android.permission.RECEIVE_BOOT_COMPLETED": "接收开机完成广播",
            "android.permission.RECEIVE_DATA_ACTIVITY_CHANGE": "接收数据活动变化",
            "android.permission.RECEIVE_EMERGENCY_BROADCAST": "接收紧急广播",
            "android.permission.RECEIVE_MMS": "接收彩信",
            "android.permission.RECEIVE_SMS": "接收短信",
            "android.permission.RECEIVE_WAP_PUSH": "接收WAP推送",
            "android.permission.RECORD_AUDIO": "录音",
            "android.permission.RECOVERY": "恢复",
            "android.permission.REGISTER_CALL_PROVIDER": "注册呼叫提供者",
            "android.permission.REGISTER_CONNECTION_MANAGER": "注册连接管理器",
            "android.permission.REGISTER_SIM_SUBSCRIPTION": "注册SIM订阅",
            "android.permission.REMOTE_NOTIFICATION": "远程通知",
            "android.permission.REMOVE_TASKS": "移除任务",
            "android.permission.REORDER_TASKS": "重新排序任务",
            "android.permission.REQUEST_COMPANION_PROFILE_WATCH": "请求配套配置文件手表",
            "android.permission.REQUEST_COMPANION_PROFILE_AUTOMOTIVE_PROJECTION": "请求配套配置文件车载投影",
            "android.permission.REQUEST_COMPANION_PROFILE_COMPUTER": "请求配套配置文件电脑",
            "android.permission.REQUEST_COMPANION_PROFILE_GLASSES": "请求配套配置文件眼镜",
            "android.permission.REQUEST_COMPANION_PROFILE_HEADPHONES": "请求配套配置文件耳机",
            "android.permission.REQUEST_COMPANION_PROFILE_NEARBY_DEVICE_STREAMING": "请求配套配置文件附近设备流",
            "android.permission.REQUEST_COMPANION_PROFILE_WATCH": "请求配套配置文件手表",
            "android.permission.REQUEST_DELETE_PACKAGES": "请求删除应用包",
            "android.permission.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS": "请求忽略电池优化",
            "android.permission.REQUEST_INSTALL_PACKAGES": "请求安装应用包",
            "android.permission.REQUEST_PASSWORD_COMPLEXITY": "请求密码复杂度",
            "android.permission.REQUEST_SCREEN_CAPTURE": "请求屏幕截图",
            "android.permission.RESTART_PACKAGES": "重启应用包",
            "android.permission.RESTORE": "恢复",
            "android.permission.RESERVE_DISK_SPACE": "预留磁盘空间",
            "android.permission.RETRIEVE_WINDOW_CONTENT": "检索窗口内容",
            "android.permission.REVIVE_SYSTEM": "恢复系统",
            "android.permission.SEND_RESPOND_VIA_MESSAGE": "发送通过消息响应",
            "android.permission.SEND_SMS": "发送短信",
            "android.permission.SERIAL_PORT": "串口",
            "android.permission.SET_ALARM": "设置闹钟",
            "android.permission.SET_ALWAYS_FINISH": "设置总是结束",
            "android.permission.SET_ANIMATION_SCALE": "设置动画比例",
            "android.permission.SET_DEBUG_APP": "设置调试应用",
            "android.permission.SET_DISABLE_APP": "设置禁用应用",
            "android.permission.SET_GLOBAL_ANIMATION_SCALE": "设置全局动画比例",
            "android.permission.SET_ORIENTATION": "设置方向",
            "android.permission.SET_POINTER_SPEED": "设置指针速度",
            "android.permission.SET_PREFERRED_APPLICATIONS": "设置首选应用",
            "android.permission.SET_PROCESS_LIMIT": "设置进程限制",
            "android.permission.SET_SCREEN_COMPATIBILITY": "设置屏幕兼容性",
            "android.permission.SET_TIME": "设置时间",
            "android.permission.SET_TIME_ZONE": "设置时区",
            "android.permission.SET_WALLPAPER": "设置壁纸",
            "android.permission.SET_WALLPAPER_HINTS": "设置壁纸提示",
            "android.permission.SHUTDOWN": "关机",
            "android.permission.SIGNAL_PERSISTENT_PROCESSES": "信号持久进程",
            "android.permission.START_ANY_ACTIVITY": "启动任何活动",
            "android.permission.START_PRINT_SERVICE_CONFIG_ACTIVITY": "启动打印服务配置活动",
            "android.permission.STATUS_BAR": "状态栏",
            "android.permission.STATUS_BAR_SERVICE": "状态栏服务",
            "android.permission.STOP_APP_SWITCHES": "停止应用切换",
            "android.permission.STRICT_MODE_VIBRATE": "严格模式振动",
            "android.permission.SUBSCRIBED_FEEDS_READ": "订阅源读取",
            "android.permission.SUBSCRIBED_FEEDS_WRITE": "订阅源写入",
            "android.permission.SYSTEM_ALERT_WINDOW": "系统警报窗口",
            "android.permission.TEMPORARY_ENABLE_ACCESSIBILITY": "临时启用无障碍",
            "android.permission.TETHER_PRIVILEGED": "网络共享特权",
            "android.permission.TOAST_WINDOW": "吐司窗口",
            "android.permission.TRANSMIT_IR": "红外传输",
            "android.permission.TRUST_LISTENER": "信任监听器",
            "android.permission.UPDATE_DEVICE_STATS": "更新设备统计",
            "android.permission.USE_BIOMETRIC": "使用生物识别",
            "android.permission.USE_FINGERPRINT": "使用指纹",
            "android.permission.USE_FULL_SCREEN_INTENT": "使用全屏Intent",
            "android.permission.USE_ICC_AUTH_WITH_DEVICE_IDENTIFIER": "使用带设备标识符的ICC认证",
            "android.permission.USE_INSTANT_APP_FOREGROUND_SERVICE": "使用免安装应用前台服务",
            "android.permission.USE_SIP": "使用SIP",
            "android.permission.USE_STORAGE": "使用存储",
            "android.permission.USE_WIDGET": "使用小部件",
            "android.permission.VIBRATE": "振动",
            "android.permission.VR_HIGH_PERFORMANCE": "VR高性能",
            "android.permission.WAKE_LOCK": "唤醒锁",
            "android.permission.WRITE_APN_SETTINGS": "写入APN设置",
            "android.permission.WRITE_CALENDAR": "写入日历",
            "android.permission.WRITE_CALL_LOG": "写入通话记录",
            "android.permission.WRITE_CONTACTS": "写入联系人",
            "android.permission.WRITE_EXTERNAL_STORAGE": "写入外部存储",
            "android.permission.WRITE_GSERVICES": "写入Google服务",
            "android.permission.WRITE_HISTORY_BOOKMARKS": "写入历史书签",
            "android.permission.WRITE_MEDIA_STORAGE": "写入媒体存储",
            "android.permission.WRITE_PROFILE": "写入个人资料",
            "android.permission.WRITE_SECURE_SETTINGS": "写入安全设置",
            "android.permission.WRITE_SETTINGS": "写入设置",
            "android.permission.WRITE_SMS": "写入短信",
            "android.permission.WRITE_SOCIAL_STREAM": "写入社交信息流",
            "android.permission.WRITE_SYNC_SETTINGS": "写入同步设置",
            "android.permission.WRITE_USER_DICTIONARY": "写入用户词典",
            "android.permission.WRITE_VOICEMAIL": "写入语音邮件",
            "android.permission.FOREGROUND_SERVICE_MEDIA_PLAYBACK": "前台服务-媒体播放",
            "android.permission.SET_VOLUME_KEY_LONG_PRESS_LISTENER": "设置音量键长按监听器",
            "android.permission.READ_SETTINGS": "读取系统设置",
            "android.permission.ACCESS_SUPERUSER": "访问超级用户",
            "android.permission.WRITE_OWNER_DATA": "写入所有者数据",
            "android.permission.ACCESS_LOCATION": "访问位置",
            "android.permission.SYSTEM_OVERLAY_WINDOW": "系统悬浮窗口",
            "android.permission.ALARM_LOCK": "闹钟锁定",
            "android.permission.READ_APP_BADGE": "读取应用角标",
            "android.permission.READ_PACKAGE_BADGE": "读取包角标",
            "android.permission.USE_FACERECOGNITION": "使用面部识别",
            "android.permission.HIGH_SAMPLING_RATE_SENSORS": "高采样率传感器"
        }
        
        # 危险权限列表（用于排序）
        # 参考Android官方文档: https://developer.android.com/guide/topics/permissions/dangerous-permissions
        # 危险权限需要用户在运行时授权
        self.dangerous_permissions = {
            # CALENDAR（日历）
            "android.permission.READ_CALENDAR",
            "android.permission.WRITE_CALENDAR",
            # CAMERA（相机）
            "android.permission.CAMERA",
            # CONTACTS（联系人）
            "android.permission.READ_CONTACTS",
            "android.permission.WRITE_CONTACTS",
            "android.permission.GET_ACCOUNTS",
            # LOCATION（位置）
            "android.permission.ACCESS_FINE_LOCATION",
            "android.permission.ACCESS_COARSE_LOCATION",
            "android.permission.ACCESS_BACKGROUND_LOCATION",
            "android.permission.ACCESS_MEDIA_LOCATION",
            # MICROPHONE（麦克风）
            "android.permission.RECORD_AUDIO",
            # PHONE（电话）
            "android.permission.READ_PHONE_STATE",
            "android.permission.CALL_PHONE",
            "android.permission.READ_CALL_LOG",
            "android.permission.WRITE_CALL_LOG",
            "android.permission.ADD_VOICEMAIL",
            "android.permission.USE_SIP",
            "android.permission.PROCESS_OUTGOING_CALLS",
            "android.permission.ANSWER_PHONE_CALLS",
            # SENSORS（传感器）
            "android.permission.BODY_SENSORS",
            "android.permission.BODY_SENSORS_BACKGROUND",
            "android.permission.ACTIVITY_RECOGNITION",
            # SMS（短信）
            "android.permission.SEND_SMS",
            "android.permission.RECEIVE_SMS",
            "android.permission.READ_SMS",
            "android.permission.RECEIVE_WAP_PUSH",
            "android.permission.RECEIVE_MMS",
            # STORAGE（存储）
            "android.permission.READ_EXTERNAL_STORAGE",
            "android.permission.WRITE_EXTERNAL_STORAGE",
            "android.permission.READ_MEDIA_IMAGES",
            "android.permission.READ_MEDIA_VIDEO",
            "android.permission.READ_MEDIA_AUDIO",
            # NOTIFICATIONS（通知）- Android 13+
            "android.permission.POST_NOTIFICATIONS",
            # NEARBY_DEVICES（附近设备）- Android 13+
            "android.permission.NEARBY_WIFI_DEVICES",
            "android.permission.BLUETOOTH_SCAN",
            "android.permission.BLUETOOTH_CONNECT",
            "android.permission.BLUETOOTH_ADVERTISE",
            "android.permission.UWB_RANGING",
        }

        # 初始化参数
        self.init_var()
        
        # 初始化UI
        self.init_ui()
        
        # 初始状态下，显示所有属性名，值为空
        self.init_empty_properties()
        
    def init_var(self):
        """
        初始化成员变量。
        
        设置当前APK路径、应用信息、签名信息、文件信息等初始值，
        初始化后台处理线程相关变量。
        """
        self.current_apk_path = ""
        # 初始化应用信息的内容
        self.init_apk_info()        # 保存 应用信息 的键值对
        self.signature_info = ""    # 保存 签名信息 的文本内容
        self.file_info = ""         # 保存 文件信息 的文本内容
        # 初始化证书列表
        self.certs = None
        # 初始化图标数据
        self.icon_data = None
        # 初始化线程中的任务运行状态是否结束
        self.apk_info_status = False
        self.signature_info_status = False
        self.file_info_status = False
        self.icon_info_status = False
        # 初始化后台处理线程
        self.worker_thread = None
        self.worker = None

    def init_apk_info(self):
        """
        初始化APK信息和图标信息字典。
        
        创建apk_info字典存储应用基本信息（包名、版本、SDK版本、权限等），
        创建apk_icon_info字典存储图标相关信息。
        """
        self.apk_info = {
            'package_name': '',
            'app_name': '',
            'chinese_app_name': '',
            'version_name': '',
            'version_code': '',
            'min_sdk_version': '',
            'target_sdk_version': '',
            'build_sdk_version': '',    # 暂时不使用
            'compile_sdk_version': '',    # 若 compile_sdk 不存在，则使用 build_sdk 的值
            'permissions': [],
        }
        self.apk_icon_info = {
            'icon_list': [],
            'icon_path': '',
            'icon_sure': True  # True表示确定的图标，False表示推测/猜测的图标
        }

    def init_ui(self):
        """
        初始化用户界面。
        
        创建并布局所有UI控件，包括：
        - 顶部：应用图标区域和操作按钮区域
        - 中部：应用基本信息表格
        - 中下部：权限信息表格
        - 下部：签名信息文本框
        - 底部：文件信息文本框
        
        使用QSplitter实现各区域的可拖拽调整大小。
        """
        # 主窗口布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.main_layout = QVBoxLayout(central_widget)
        self.main_layout.setContentsMargins(3, 3, 3, 3)    # 窗口内组件与窗口边之间的间距
        # 创建垂直QSplitter，用于实现各区域的拖拽缩放
        self.main_splitter = QSplitter(Qt.Vertical)
        
        # 顶部：应用图标和操作按钮（水平排列）
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        
        #### 应用图标区域
        icon_group = QGroupBox("应用图标")
        icon_group.setFixedSize(100, 100) 
        icon_layout = QVBoxLayout(icon_group)
        icon_layout.setContentsMargins(0, 0, 0, 0)  # 左、上、右、下的边距值
        
        # 使用自定义的可点击标签
        self.icon_label = ClickableLabel()
        self.icon_label.setFixedSize(64, 64)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setToolTip("点击查看原图")
        self.icon_label.clicked.connect(self.show_original_icon)
        
        self.icon_size_label = QLabel("")
        self.icon_size_label.setAlignment(Qt.AlignCenter)
        
        icon_info_layout = QVBoxLayout()
        # icon_info_layout.setSpacing(0)
        # icon_info_layout.setContentsMargins(10, 0, 10, 3)  # 左、上、右、下的边距值
        icon_info_layout.addWidget(self.icon_label)
        icon_info_layout.addWidget(self.icon_size_label)
        icon_info_layout.setAlignment(Qt.AlignCenter)
        
        icon_layout.addLayout(icon_info_layout)
        top_layout.addWidget(icon_group)
        
        # 添加伸缩空间，将按钮推到右侧
        top_layout.addStretch()
        
        #### 操作按钮区域 - 独立区域，放在图标右侧并整体居右
        button1_Height = 20
        button1_width = 100
        about_button_width = 50
        
        button_container = QWidget()
        button_layout = QGridLayout(button_container)
        button_layout.setHorizontalSpacing(15)  # 水平
        button_layout.setVerticalSpacing(5)  # 垂直
        
        self.select_button = QPushButton("选择APK文件")
        self.select_button.setMinimumHeight(button1_Height)
        self.select_button.setFixedWidth(button1_width)
        self.select_button.setToolTip("点击选择APK文件进行分析")
        self.select_button.clicked.connect(self.select_apk_file)
        button_layout.addWidget(self.select_button, 0, 0)
        
        self.association_setting_button = QPushButton("设置关联APK")
        self.association_setting_button.setMinimumHeight(button1_Height)
        self.association_setting_button.setFixedWidth(button1_width)
        self.association_setting_button.setToolTip("设置APK文件与本程序的关联，\n双击APK文件时自动使用本程序打开")
        self.association_setting_button.clicked.connect(self.open_association_settings)
        button_layout.addWidget(self.association_setting_button, 0, 1)
        
        self.save_info_button = QPushButton("保存所有信息")
        self.save_info_button.setMinimumHeight(button1_Height)
        self.save_info_button.setFixedWidth(button1_width)
        self.save_info_button.setToolTip("保存当前APK所有信息到文本文件")
        self.save_info_button.clicked.connect(self.save_all_info)
        button_layout.addWidget(self.save_info_button, 1, 0)
        self.save_info_button.setEnabled(False)
        
        self.copy_info_button = QPushButton("复制所有信息")
        self.copy_info_button.setMinimumHeight(button1_Height)
        self.copy_info_button.setFixedWidth(button1_width)
        self.copy_info_button.setToolTip("复制当前APK所有信息到剪贴板")
        self.copy_info_button.clicked.connect(self.copy_all_info)
        button_layout.addWidget(self.copy_info_button, 1, 1)
        self.copy_info_button.setEnabled(False)
        
        self.save_icon_button = QPushButton("保存应用图标")
        self.save_icon_button.setMinimumHeight(button1_Height)
        self.save_icon_button.setFixedWidth(button1_width)
        self.save_icon_button.setToolTip("保存当前APK的应用图标到本地")
        self.save_icon_button.clicked.connect(self.save_app_icon)
        button_layout.addWidget(self.save_icon_button, 2, 0)
        self.save_icon_button.setEnabled(False)
        
        # 创建第二列右侧的小部件容器，放置窗体置顶和关于按钮
        right_col2_widget = QWidget()
        right_col2_layout = QHBoxLayout(right_col2_widget)
        right_col2_layout.setContentsMargins(0, 0, 0, 0)
        right_col2_layout.setSpacing(8)
        
        self.about_button = QPushButton("关于")
        self.about_button.setMinimumHeight(button1_Height)
        self.about_button.setFixedWidth(about_button_width)
        self.about_button.setToolTip("显示关于本软件的信息")
        self.about_button.clicked.connect(self.show_about)
        right_col2_layout.addWidget(self.about_button)
        
        # 添加置顶复选框
        self.always_on_top_checkbox = QCheckBox("置顶")
        self.always_on_top_checkbox.setMinimumHeight(button1_Height)
        self.always_on_top_checkbox.setToolTip("勾选后使窗口始终保持在最顶层")
        self.always_on_top_checkbox.stateChanged.connect(self.toggle_always_on_top)
        self.always_on_top_checkbox.setStyleSheet("QCheckBox::indicator { width: 12px; height: 12px; } QCheckBox { spacing: 2px; }")
        right_col2_layout.addWidget(self.always_on_top_checkbox)
        
        button_layout.addWidget(right_col2_widget, 2, 1)
        
        
        # 添加拖拽提示文本
        drag_hint = QLabel("提示：拖拽APK文件到窗口即可查看信息")
        drag_hint.setAlignment(Qt.AlignCenter)
        drag_hint.setStyleSheet("color: blue;")
        button_layout.addWidget(drag_hint, 3, 0, 1, 2)  # 横跨两列
        
        button_layout.setRowStretch(4, 1)
        button_layout.setColumnStretch(2, 1)
        
        # 将按钮容器添加到顶部布局
        top_layout.addWidget(button_container)
        top_layout.setContentsMargins(0, 0, 0, 0)  # 左、上、右、下的边距值
        self.main_layout.addWidget(top_widget)
        
        
        #### 应用基本信息区域
        self.app_info_group = QGroupBox("基本信息")
        app_info_layout = QVBoxLayout(self.app_info_group)
        app_info_layout.setContentsMargins(3, 3, 3, 3)    # 内部组件的间距
        
        # 创建堆叠窗口部件来管理表格和文本框
        self.app_info_stacked_widget = QStackedWidget()
        
        # 创建表格视图
        self.app_info_table = CustomTableWidget()
        self.app_info_table.setColumnCount(2)
        # 不显示列名
        self.app_info_table.horizontalHeader().setVisible(False)
        self.app_info_table.verticalHeader().setVisible(False)
        # 设置表格为可选择但不可编辑，支持单元格选择和文本拖选
        self.app_info_table.setEditTriggers(self.app_info_table.NoEditTriggers)
        self.app_info_table.setSelectionBehavior(self.app_info_table.SelectItems)  # 支持单元格选择
        self.app_info_table.setSelectionMode(self.app_info_table.ExtendedSelection)  # 支持扩展选择
        self.app_info_table.setTextElideMode(Qt.ElideNone)  # 不省略文本
        # self.app_info_table.setWordWrap(True)  # 自动换行
        self.app_info_table.setMinimumSize(50, 50)
        # 水平方向可扩展，垂直方向根据内容自适应
        self.app_info_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        
        # 创建内容框视图，用于显示解析状态和错误信息
        self.app_info_content_box = QTextEdit()
        self.app_info_content_box.setReadOnly(True)
        self.app_info_content_box.setMinimumSize(50, 50)
        # 水平方向可扩展，垂直方向固定（高度由代码控制，跟随表格高度）
        self.app_info_content_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        self.app_info_content_box.clear()    # 清空内容框
        # 设置字体
        font = self.app_info_content_box.font()
        # font.setPointSize(16)    # 字号
        font.setBold(True)    # 粗体
        self.app_info_content_box.setFont(font)
        # 设置文档的文本选项
        document = self.app_info_content_box.document()
        document.setDefaultTextOption(QTextOption(Qt.AlignLeft))    # 默认居左显示内容
        
        # 将两个控件添加到堆叠窗口
        self.app_info_stacked_widget.addWidget(self.app_info_table)      # 索引 0 - 表格视图
        self.app_info_stacked_widget.addWidget(self.app_info_content_box) # 索引 1 - 内容框视图
        
        app_info_layout.addWidget(self.app_info_stacked_widget)
        self.main_splitter.addWidget(self.app_info_group)
        
        #### 权限信息区域
        permission_group = QGroupBox("权限信息")
        permission_layout = QVBoxLayout(permission_group)
        permission_layout.setContentsMargins(3, 3, 3, 3)    # 内部组件的间距
        
        self.permission_table = CustomTableWidget()
        self.permission_table.setColumnCount(2)  # 两列的表格
        self.permission_table.setHorizontalHeaderLabels(["", ""])  # 列名均为空
        self.permission_table.verticalHeader().setVisible(False)  # 行名不显示
        # self.permission_table.horizontalHeader().setVisible(False)
        header = self.permission_table.horizontalHeader()
        header.setFixedHeight(2)  # 表头高度设为很小，方便拖拽
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        
        # 设置表格为可选择但不可编辑，支持单元格选择和文本拖选
        self.permission_table.setEditTriggers(self.permission_table.NoEditTriggers)
        self.permission_table.setSelectionBehavior(self.permission_table.SelectItems)  # 支持单元格选择
        self.permission_table.setSelectionMode(self.permission_table.ExtendedSelection)  # 支持扩展选择
        self.permission_table.setTextElideMode(Qt.ElideNone)  # 不省略文本

        # 增加垂直滚动条
        self.permission_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.permission_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        permission_layout.addWidget(self.permission_table)
        self.main_splitter.addWidget(permission_group)
        
        #### 签名信息区域
        sig_info_group = QGroupBox("签名信息")
        sig_info_layout = QVBoxLayout(sig_info_group)
        sig_info_layout.setContentsMargins(3, 3, 3, 3)    # 内部组件的间距
        
        # 创建水平布局用于放置文本框和按钮
        sig_horizontal_layout = QHBoxLayout()
        # sig_horizontal_layout.setContentsMargins(3, 3, 3, 3)    # 内部组件的间距，这里暂时不需要修改
        
        self.sig_info_text = CustomTextEdit()
        self.sig_info_text.setReadOnly(True)
        sig_horizontal_layout.addWidget(self.sig_info_text)
        
        # 添加签名详情按钮
        self.show_signature_details_btn = QPushButton(".")
        self.show_signature_details_btn.setFixedWidth(16)
        self.show_signature_details_btn.setToolTip("查看完整的APK签名详情信息")
        self.show_signature_details_btn.clicked.connect(self.show_signature_details_dialog)
        sig_horizontal_layout.addWidget(self.show_signature_details_btn)
        self.show_signature_details_btn.setEnabled(False)
        
        sig_info_layout.addLayout(sig_horizontal_layout)
        self.main_splitter.addWidget(sig_info_group)
        
        #### 文件信息区域
        file_info_group = QGroupBox("文件信息")
        file_info_layout = QVBoxLayout(file_info_group)
        file_info_layout.setContentsMargins(3, 3, 3, 3)    # 内部组件的间距
        self.file_info_text = CustomTextEdit()
        self.file_info_text.setReadOnly(True)
        self.file_info_text.setLineWrapMode(QTextEdit.NoWrap)  # 不自动换行
        self.file_info_text.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        file_info_layout.addWidget(self.file_info_text)
        self.main_splitter.addWidget(file_info_group)
        
        # 设置QSplitter的初始大小比例，可以调整不同区域的初始高度。基于这个比例进行显示，后面加载内容后会更新比例。
        self.main_splitter.setSizes([480, 220, 150, 150])
        
        # 添加QSplitter到主布局
        self.main_layout.addWidget(self.main_splitter)
        # 防止鼠标拖拽时，某些布局被折叠或者隐藏
        self.main_splitter.setCollapsible(0, False)
        self.main_splitter.setCollapsible(1, False)
        self.main_splitter.setCollapsible(2, False)
        self.main_splitter.setCollapsible(3, False)

    def init_empty_properties(self):
        """
        显示空属性内容的界面。
        
        在初始状态或清空APK信息时调用，显示属性名称但值为空的界面。
        清空图标、签名信息、文件信息，设置基本信息表格的属性名。
        """
        # 清空图标、签名信息、文件信息
        self.icon_label.clear()
        self.icon_label.setOriginalPixmap(None)
        self.icon_size_label.setText("")
        self.sig_info_text.setText("")
        self.file_info_text.setText("")

        # 清空表格
        self.app_info_table.setRowCount(0)
        self.permission_table.setRowCount(0)
        self.app_info_table.setColumnWidth(0, 120)  # 设置第一列的列宽
        self.permission_table.setColumnWidth(0, 200)  # 设置第一列的列宽
        
        # 应用基本信息：设置应用基本信息表格的属性名
        properties = [
            "应用包名",
            "默认应用名",
            "中文应用名",
            "版本号",
            "内部版本号",
            "最低兼容SDK版本",
            "目标适配SDK版本",
            "编译构建SDK版本",
        ]
        
        # 应用基本信息：显示属性名，值为空
        for prop in properties:
            self.add_table_row(self.app_info_table, prop, "")
        # 应用基本信息：根据内容自动调整第一列列宽
        self.app_info_table.resizeColumnToContents(0)
        
        # 应用基本信息：调整表格高度以适应空条目，不设置边距，确保高度正好匹配内容
        total_height = 0
        for i in range(self.app_info_table.rowCount()):
            total_height += self.app_info_table.rowHeight(i)
            # app_logger.debug(f"行号: {i}，行高: {self.app_info_table.rowHeight(i)}")
        self.app_info_table.setMaximumHeight(total_height+2)  # 设置应用基本信息表格最大高度
        # 同步设置内容框的高度，保持两个视图高度一致
        self.app_info_content_box.setMaximumHeight(total_height+2)
        
        # 根据应用基本信息表格的高度，更新调整整个主窗口中几个显示区域的比例，目的就是为了让应用信息刚好显示完整（不会显示竖向滚动条）
        height = self.main_splitter.height()  # 主窗口的高度
        app_info_sh = int(1000 * (total_height+40) / height)  # 多增加40个像素作为区域框额外的高度。这样换算出来实际像素对应的高度比例值
        # app_logger.debug(f"main_splitter高度={height}像素, app_info_table高度比例值={app_info_sh}")
        self.main_splitter.setSizes([app_info_sh, 700-app_info_sh, 150, 150])  # 700 给前两个区域，300 给后两个区域，共1000比例值，按比例分摊高度。

    def center_window(self):
        """
        将窗口显示在屏幕中心。
        
        使用QDesktopWidget获取屏幕可用区域，
        计算窗口居中位置并移动窗口。
        """
        # 使用QDesktopWidget来获取屏幕尺寸，更可靠
        desktop = QDesktopWidget()
        # 获取屏幕尺寸
        screen_rect = desktop.availableGeometry()
        # 获取窗口尺寸
        window_rect = self.frameGeometry()
        # 计算居中位置
        center_point = screen_rect.center()
        window_rect.moveCenter(center_point)
        # 设置窗口位置
        self.move(window_rect.topLeft())

    def display_app_info(self):
        """
        显示应用基本信息。
        
        将apk_info中的信息显示在基本信息表格中，包括：
        包名、应用名、中文应用名、版本号、内部版本号、SDK版本等。
        SDK版本会自动转换为对应的Android版本名称。
        """
        # 切换到表格视图
        self.app_info_stacked_widget.setCurrentIndex(0)  # 显示表格
        
        # 清空表格
        self.app_info_table.setRowCount(0)
        
        # 基础信息
        package_name = self.apk_info['package_name'] or "未知"
        default_app_name = self.apk_info['app_name'] or "未知(文件损坏或资源混淆)"
        version_code = self.apk_info['version_code'] or "未知"
        version_name = self.apk_info['version_name'] or "未知"
        # 中文应用名
        chinese_app_name = self.apk_info['chinese_app_name'] or ""

        # SDK版本处理
        min_sdk = self.apk_info['min_sdk_version'] or "未知"
        target_sdk = self.apk_info['target_sdk_version'] or "未知"
        build_sdk = self.apk_info['build_sdk_version'] or "未知"
        compile_sdk = self.apk_info['compile_sdk_version'] or "未知"

        min_sdk_display = f"{min_sdk} ({self.sdk_version_map.get(str(min_sdk), '未知版本')})"
        target_sdk_display = f"{target_sdk} ({self.sdk_version_map.get(str(target_sdk), '未知版本')})"
        compile_sdk_display = f"{compile_sdk} ({self.sdk_version_map.get(str(compile_sdk), '未知版本')})"

        # 添加到表格
        self.add_table_row(self.app_info_table, "应用包名", package_name)
        self.add_table_row(self.app_info_table, "默认应用名", default_app_name)
        self.add_table_row(self.app_info_table, "中文应用名", chinese_app_name)
        self.add_table_row(self.app_info_table, "版本号", version_name)
        self.add_table_row(self.app_info_table, "内部版本号", version_code)
        self.add_table_row(self.app_info_table, "最低兼容SDK版本", min_sdk_display)
        self.add_table_row(self.app_info_table, "目标适配SDK版本", target_sdk_display)
        self.add_table_row(self.app_info_table, "编译构建SDK版本", compile_sdk_display)
        
        # 根据内容自动调整第一列列宽
        self.app_info_table.resizeColumnToContents(0)
        
        # 调整表格高度
        total_height = 0
        for i in range(self.app_info_table.rowCount()):
            total_height += self.app_info_table.rowHeight(i)
        self.app_info_table.setMaximumHeight(total_height+2)  # 设定表格最大高度

    def show_parsing_status(self, message):
        """
        显示解析状态信息。
        
        在解析过程中显示状态提示，切换到内容框视图，
        以蓝色居中文字显示状态信息。
        
        Args:
            message: 要显示的状态信息文本
        """
        # 切换到内容框视图
        self.app_info_stacked_widget.setCurrentIndex(1)  # 显示内容框
        self.app_info_content_box.setTextColor(Qt.blue)    # 设置文本颜色为蓝色
        self.app_info_content_box.setPlainText(f"{message}")    # 设置文本内容
        self.app_info_content_box.setAlignment(Qt.AlignCenter)    # 居中显示
        QApplication.processEvents()  # 强制更新UI

    def show_error_message(self, error_msg):
        """
        显示错误信息。
        
        切换到内容框视图，以红色左对齐文字显示错误信息。
        
        Args:
            error_msg: 要显示的错误信息文本
        """
        # 切换到内容框视图
        self.app_info_stacked_widget.setCurrentIndex(1)  # 显示内容框
        self.app_info_content_box.setTextColor(Qt.red)
        self.app_info_content_box.setText(f"{error_msg}")
        self.app_info_content_box.setAlignment(Qt.AlignLeft)    # 居左显示
        QApplication.processEvents()  # 强制更新UI

    def display_permissions(self):
        """
        显示应用权限信息。
        
        将权限按危险权限、普通权限、未知权限的顺序分类显示，
        并显示权限的中文翻译。危险权限排在最前面。
        """
        self.permission_table.setRowCount(0)    # 清空表格显示的内容
        permissions = self.apk_info['permissions'] or []
        if not permissions:
            self.add_table_row(self.permission_table, "无", "未申请任何权限")
            return
            
        # 将权限分为三类：危险权限、普通权限、未知权限
        dangerous_perms = []
        normal_perms = []
        unknown_perms = []
        
        for perm in permissions:
            if perm in self.dangerous_permissions:
                dangerous_perms.append(perm)
            elif perm in self.permission_map:
                normal_perms.append(perm)
            else:
                unknown_perms.append(perm)
        
        # 按顺序显示权限
        for perm in dangerous_perms:
            chinese_name = self.permission_map.get(perm, "未知权限")
            self.add_table_row(self.permission_table, perm, chinese_name)
        
        for perm in normal_perms:
            chinese_name = self.permission_map.get(perm, "未知权限")
            self.add_table_row(self.permission_table, perm, chinese_name)
        
        for perm in unknown_perms:
            self.add_table_row(self.permission_table, perm, "未知权限")

    def display_signature_info(self):
        """
        显示签名信息。
        
        将签名信息文本显示在签名信息文本框中。
        """
        self.sig_info_text.setText(self.signature_info)

    def show_signature_details_dialog(self):
        """
        显示签名详情对话框。
        
        打开SignatureDetailsDialog对话框，显示完整的APK签名详情信息，
        支持证书哈希值比较功能。
        """
        # 传递主窗口中已有的签名信息文本
        signature_text = self.sig_info_text.toPlainText()
        dialog = SignatureDetailsDialog(signature_text, self)
        dialog.exec_()

    def display_file_info(self):
        """
        显示文件信息。
        
        将文件信息（路径、MD5、大小等）显示在文件信息文本框中。
        """
        self.file_info_text.setText(self.file_info)
    
    def display_app_icon_from_data(self, icon_data, icon_sure):
        """
        从后台线程提供的图标数据显示应用图标。
        
        解析图标二进制数据，显示图标和尺寸信息。
        支持PNG、WebP等常见图片格式。
        
        Args:
            icon_data: 图标的二进制数据
            icon_sure: 图标是准确的（True）或推测的（False）
        """
        try:
            if icon_data is not None:
                # 保存图标数据，用于后续保存功能
                self.icon_data = icon_data
                # app_logger.debug(f"图标路径: {self.apk_icon_info.get('icon_path', '')}，是否准确: {icon_sure}")
                
                # 解析尺寸
                try:
                    with Image.open(BytesIO(icon_data)) as img:
                        width, height = img.size
                    if icon_sure:
                        self.icon_size_label.setText(f"{width} x {height}")
                    else:
                        self.icon_size_label.setText(f"(推测图标)\n{width} x {height}")
                except Exception as e:
                    self.icon_size_label.setText(f"无法解析宽高")
                    app_logger.error(f"无法解析图片的宽度和高度: {str(e)}")
                
                # 显示图标
                pixmap = QPixmap()
                pixmap.loadFromData(icon_data)
                if not pixmap.isNull():
                    # 保存原始像素图
                    self.icon_label.setOriginalPixmap(pixmap)
                    # 显示缩放后的图标
                    scaled_pixmap = pixmap.scaled(self.icon_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    self.icon_label.setPixmap(scaled_pixmap)
                    self.save_icon_button.setEnabled(True)    # 启用保存图标按钮
                else:
                    self.icon_label.setText("无法\n加载\n图标")
                    self.icon_label.setOriginalPixmap(None)
                    self.icon_size_label.setText("")
                    app_logger.warning(f"无法加载图标")
            else:
                self.icon_label.setText(f"未找到\n图标")
                self.icon_label.setOriginalPixmap(None)
                self.icon_size_label.setText("")
                app_logger.warning(f"未找到图标")
        except Exception as e:
            self.icon_label.setText("图标\n解析\n失败")
            self.icon_label.setOriginalPixmap(None)
            self.icon_size_label.setText("")
            app_logger.error(f"图标解析失败: {e}")
    
    def show_original_icon(self):
        """显示原始尺寸的图标弹出窗口"""
        original_pixmap = self.icon_label.getOriginalPixmap()
        if original_pixmap and not original_pixmap.isNull():
            # 清理之前可能存在的弹出窗口
            if hasattr(self, 'icon_popup') and self.icon_popup:
                try:
                    self.icon_popup.cleanup()
                    self.icon_popup.deleteLater()
                except Exception:
                    pass
                self.icon_popup = None
            
            # 获取鼠标的全局位置
            cursor_pos = QCursor.pos()
            
            # 创建并显示弹出窗口
            self.icon_popup = IconPopupWindow(original_pixmap, self)
            # 连接窗口销毁信号，确保引用被清理
            try:
                self.icon_popup.destroyed.disconnect()
            except TypeError:
                pass
            self.icon_popup.destroyed.connect(self._on_icon_popup_destroyed)
            self.icon_popup.show_at_position(cursor_pos)
    
    def _on_icon_popup_destroyed(self):
        """
        图标弹出窗口销毁时的回调函数。
        
        清空对弹出窗口的引用，防止内存泄漏。
        """
        self.icon_popup = None

    def add_table_row(self, table, key, value):
        """
        向指定表格添加一行数据。
        
        Args:
            table: QTableWidget表格控件
            key: 第一列的键名
            value: 第二列的值
        """
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem(key))
        table.setItem(row, 1, QTableWidgetItem(str(value)))
        table.resizeRowToContents(row)
        table.horizontalHeader().setStretchLastSection(True)

    def clear_ui(self):
        """
        清空UI显示并释放内存。
        
        在解析新APK前调用，清空图标、签名信息、文件信息和表格内容。
        """
        # 清空图标弹出窗口
        if hasattr(self, 'icon_popup') and self.icon_popup:
            try:
                self.icon_popup.cleanup()
                self.icon_popup.deleteLater()
            except Exception:
                pass
            self.icon_popup = None
        
        # 清空图标数据
        self.icon_data = None
        
        # 清空图标、签名信息、文件信息
        self.icon_label.clear()
        self.icon_label.setOriginalPixmap(None)  # 清空原图和点击功能
        self.icon_size_label.setText("")
        self.sig_info_text.setText("")
        self.file_info_text.setText("")
        
        # 清空表格
        self.app_info_table.setRowCount(0)
        self.permission_table.setRowCount(0)

    def disable_main_controls(self):
        """
        禁用主界面的按钮和复选框。
        
        在APK解析过程中调用，防止用户重复操作。
        """
        self.select_button.setEnabled(False)    # 选择APK文件按钮
        self.association_setting_button.setEnabled(False)    # 设置关联APK按钮
        self.about_button.setEnabled(False)    # 关于按钮
        self.always_on_top_checkbox.setEnabled(False)    # 窗体置顶复选框
        self.copy_info_button.setEnabled(False)    # 复制所有信息按钮
        self.save_info_button.setEnabled(False)    # 保存所有信息按钮
        self.save_icon_button.setEnabled(False)    # 保存应用图标按钮
        self.show_signature_details_btn.setEnabled(False)    # 签名详情按钮

    def enable_main_controls(self):
        """
        启用主界面的按钮和复选框。
        
        在APK解析完成后调用，恢复用户操作。
        注意：复制、保存等按钮需要解析成功后单独启用。
        """
        self.select_button.setEnabled(True)    # 选择APK文件按钮
        self.association_setting_button.setEnabled(True)    # 设置关联APK按钮
        self.about_button.setEnabled(True)    # 关于按钮
        self.always_on_top_checkbox.setEnabled(True)    # 窗体置顶复选框

    def select_apk_file(self):
        """
        选择APK文件并解析。
        
        打开文件选择对话框，选择APK文件后调用解析方法。
        """
        file_path, _ = QFileDialog.getOpenFileName(self, "选择APK文件", "", "APK 文件 (*.apk);;所有文件 (*)")
        if file_path:
            self.get_apk_info(file_path)

    def get_all_info_text(self):
        """
        获取所有应用信息的文本内容。
        
        将应用基本信息、权限信息、签名信息、文件信息整合为文本格式。
        
        Returns:
            str: 包含所有信息的文本字符串
        """
        all_info = ""
        
        # 应用基本信息
        all_info += "=== 应用基本信息 ===\n"
        for row in range(self.app_info_table.rowCount()):
            key_item = self.app_info_table.item(row, 0)
            value_item = self.app_info_table.item(row, 1)
            if key_item and value_item:
                all_info += f"{key_item.text()}: {value_item.text()}\n"
        
        # 权限信息
        all_info += "\n=== 应用权限信息 ===\n"
        for row in range(self.permission_table.rowCount()):
            key_item = self.permission_table.item(row, 0)
            value_item = self.permission_table.item(row, 1)
            if key_item and value_item:
                all_info += f"{key_item.text()}: {value_item.text()}\n"
        
        # 签名信息
        all_info += "\n=== 签名信息 ===\n"
        all_info += self.sig_info_text.toPlainText() + "\n"
        
        # 文件信息
        all_info += "\n=== 文件信息 ===\n"
        all_info += self.file_info_text.toPlainText() + "\n"
        
        return all_info

    def copy_all_info(self):
        """
        复制所有应用信息到剪贴板。
        
        将应用基本信息、权限信息、签名信息、文件信息整合后复制到系统剪贴板。
        """
        # 实现复制功能
        all_info = self.get_all_info_text()
        
        # 复制到剪贴板
        clipboard = QApplication.clipboard()
        clipboard.setText(all_info)
        
        # 提示复制成功
        QMessageBox.information(self, "提示", "所有信息已复制到剪贴板，\n可以粘贴使用。")

    def save_all_info(self):
        """
        保存所有应用信息到文本文件。
        
        打开保存文件对话框，将所有信息保存为UTF-8编码的文本文件。
        默认文件名格式：应用名(包名)-版本号.txt
        """
        # 收集所有信息
        all_info = self.get_all_info_text()
        
        # 确定默认文件名（优先顺序：中文应用名 > 默认应用名 > apk_info）
        if self.apk_info['chinese_app_name'] != '':
            default_name = self.apk_info['chinese_app_name']
        elif self.apk_info['app_name'] != '':
            default_name = self.apk_info['app_name']
        
        default_name += f"({self.apk_info['package_name']})" if self.apk_info['package_name'] else ''
        default_name += f"-{self.apk_info['version_name']}" if self.apk_info['version_name'] else ''

        # 打开保存文件对话框
        save_path, _ = QFileDialog.getSaveFileName(
            self, "保存所有信息", f"{default_name}.txt", "文本文件 (*.txt);;所有文件 (*)"
        )
        
        if save_path:
            try:
                # 保存为UTF-8编码
                with open(save_path, 'w', encoding='utf-8') as f:
                    f.write(all_info)
                QMessageBox.information(self, "成功", f"已保存到：\n{save_path}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存失败：\n{str(e)}")

    def save_app_icon(self):
        """
        保存应用图标到本地文件。
        
        打开保存文件对话框，将图标保存为PNG格式。
        默认文件名格式：应用名.png，如果是推测的图标会添加"(推测)"后缀。
        """
        # 实现保存图标功能，保存的图标文件名优先顺序：中文应用名 > 默认应用名 > app_icon
        if hasattr(self, 'icon_data') and self.icon_data:
            if self.apk_info['chinese_app_name'] != '':
                png_name = self.apk_info['chinese_app_name']
            elif  self.apk_info['app_name'] != '':
                png_name = self.apk_info['app_name']
            else:
                png_name = "app_icon"

            png_name += f"({self.apk_info['package_name']})" if self.apk_info['package_name'] else ''
            png_name += f"-{self.apk_info['version_name']}" if self.apk_info['version_name'] else ''
            if not self.apk_icon_info['icon_sure']:
                png_name += "(推测)"
            save_path, _ = QFileDialog.getSaveFileName(
                self, "保存应用图标", f"{png_name}", "PNG 文件 (*.png);;所有文件 (*)"
            )
            if save_path:
                try:
                    with open(save_path, 'wb') as f:
                        f.write(self.icon_data)
                except Exception as e:
                    app_logger.error(f"保存图标失败: {str(e)}")
        else:
            app_logger.warning("没有可保存的图标")

    def open_association_settings(self):
        """
        打开APK文件关联设置对话框。
        
        显示AssociationSettingsDialog对话框，用于设置或取消APK文件与本程序的关联。
        """
        dialog = AssociationSettingsDialog(self)
        dialog.exec_()
    
    def reg_apk(self):
        """
        执行关联APK脚本。
        
        调用外部批处理脚本注册APK文件关联，使双击APK文件时使用本程序打开。
        需要管理员权限执行。
        """
        # 解决32位python程序无法调用64位system32目录下的程序
        custom_env = os.environ.copy()
        x64_system_path=os.path.expandvars(r"%windir%\sysnative")
        custom_env["PATH"] = custom_env["PATH"] + f";{x64_system_path}"

        global BASE_DIR
        script_path = os.path.join(BASE_DIR, "☆reg_apk.bat")
        if os.path.exists(script_path):
            try:
                result = subprocess.run([script_path], shell=True, capture_output=True, text=True, env=custom_env, timeout=20)
                # app_logger.debug(f"{script_path} 注册apk文件关联脚本执行结果: {result}")
                if result.returncode == 0:
                    QMessageBox.information(self, "成功", "关联APK成功！")
                else:
                    QMessageBox.critical(self, "错误", f"执行失败:\n{result.stderr}\n\n注册可能已经成功完成")
            except subprocess.TimeoutExpired:
                QMessageBox.critical(self, "错误", "执行操作超时！")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"发生错误:\n{str(e)}\n\n注册可能已经成功完成")
        else:
            QMessageBox.critical(self, "错误", f"关联APK脚本文件不存在:\n{script_path}")
    
    def unreg_apk(self):
        """
        执行取消关联APK脚本。
        
        调用外部批处理脚本取消APK文件与本程序的关联。
        需要管理员权限执行。
        """
        # 解决32位python程序无法调用64位system32目录下的程序
        custom_env = os.environ.copy()
        x64_system_path=os.path.expandvars(r"%windir%\sysnative")
        custom_env["PATH"] = custom_env["PATH"] + f";{x64_system_path}"

        global BASE_DIR
        script_path = os.path.join(BASE_DIR, "☆unreg_apk.bat")
        if os.path.exists(script_path):
            try:
                result = subprocess.run([script_path], shell=True, capture_output=True, text=True, env=custom_env, timeout=20)
                # app_logger.debug(f"{script_path} 取消apk文件关联脚本执行结果: {result}")
                if result.returncode == 0:
                    QMessageBox.information(self, "成功", "取消关联APK成功！")
                else:
                    QMessageBox.critical(self, "错误", f"执行失败:\n{result.stderr}\n\n取消注册可能已经成功完成")
            except subprocess.TimeoutExpired:
                QMessageBox.critical(self, "错误", "执行操作超时！")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"发生错误:\n{str(e)}\n\n取消注册可能已经成功完成")
        else:
            QMessageBox.critical(self, "错误", f"取消关联APK脚本文件不存在:\n{script_path}")
    
    def show_about(self):
        """显示关于对话框"""
        dialog = QDialog(self)
        dialog.setWindowTitle("关于")
        dialog.setMinimumWidth(260)
        
        layout = QVBoxLayout(dialog)
        
        about_text = f"APK文件信息解析工具-APK Helper\n\n" + \
                     f"版本: {b_ver}\n" + \
                     f"日期: {b_date}\n" + \
                     f"作者: {b_auth}\n\n" + \
                     f"    使用androguard库分析安卓应用APK文件，\n显示一些基本信息。\n\n" + \
                     f"功能: \n" + \
                     f"- 查看应用图标和基本信息\n" + \
                     f"- 查看应用权限\n" + \
                     f"- 查看签名信息\n" + \
                     f"- 复制应用信息\n" + \
                     f"- 保存应用信息\n" + \
                     f"- 保存应用图标\n" + \
                     f"- 比较签名证书哈希值\n" + \
                     f"- 支持拖拽APK文件到窗口\n"
        
        text_label = QLabel(about_text)
        layout.addWidget(text_label)
        
        # 日志管理设置
        log_manage_group = QGroupBox("日志管理")
        log_manage_layout = QHBoxLayout(log_manage_group)
        
        log_level_label = QLabel("日志级别:")
        log_level_label.setToolTip("修改日志级别后，后续日志将按新级别生成")
        log_manage_layout.addWidget(log_level_label)
        
        log_level_combo = QComboBox()
        log_level_combo.setToolTip("修改日志级别后，后续日志将按新级别生成")
        log_levels = ["DEBUG", "INFO", "WARNING", "ERROR"]
        log_level_combo.addItems(log_levels)
        
        global CURRENT_LOG_LEVEL
        if CURRENT_LOG_LEVEL in log_levels:
            log_level_combo.setCurrentText(CURRENT_LOG_LEVEL)
        else:
            log_level_combo.setCurrentText(DEFAULT_LOG_LEVEL)
        
        log_manage_layout.addWidget(log_level_combo)
        log_manage_layout.addStretch()
        
        save_log_btn = QPushButton("保存日志")
        save_log_btn.setToolTip(f"将缓存的日志信息保存到文件，\n当前缓存大小限制: {LOG_CACHE_MAX_SIZE // 1024}KB")
        log_manage_layout.addWidget(save_log_btn)
        
        def save_log_to_file():
            """保存日志到文件"""
            if memory_log_handler is None:
                QMessageBox.warning(dialog, "警告", "日志处理器未初始化！")
                return
            
            logs = memory_log_handler.get_logs()
            if not logs:
                QMessageBox.information(dialog, "提示", "当前没有缓存的日志记录。")
                return
            
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            default_filename = f"apk_helper_log_{timestamp}.txt"
            
            file_path, _ = QFileDialog.getSaveFileName(
                dialog,
                "保存日志文件",
                default_filename,
                "文本文件 (*.txt);;所有文件 (*.*)"
            )
            
            if file_path:
                try:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(f"APK Helper {b_ver}-{b_date} 日志输出\n")
                        f.write(f"导出时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                        # f.write(f"日志级别: {CURRENT_LOG_LEVEL}\n")
                        f.write("=" * 50 + "\n\n")
                        f.write(logs)
                    QMessageBox.information(dialog, "成功", f"日志已保存到:\n{file_path}")
                except Exception as e:
                    QMessageBox.critical(dialog, "错误", f"保存日志失败:\n{str(e)}")
        
        save_log_btn.clicked.connect(save_log_to_file)
        layout.addWidget(log_manage_group)
        
        # 按钮区域
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.button(QDialogButtonBox.Ok).setText("确定")
        button_box.button(QDialogButtonBox.Cancel).setText("取消")
        layout.addWidget(button_box)
        
        def on_ok():
            selected_level = log_level_combo.currentText()
            set_log_level(selected_level)
            app_logger.info(f"日志级别已设置为: {selected_level}")
            dialog.accept()
        
        button_box.accepted.connect(on_ok)
        button_box.rejected.connect(dialog.reject)
        
        dialog.exec_()
    
    def toggle_always_on_top(self, state):
        """
        切换取窗体置顶状态
        :param state: 复选框状态，2表示选中，0表示未选中
        """
        if state == 2:  # Qt.Checked
            # 设置窗口标志为置顶
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
            self.show()
        else:  # Qt.Unchecked
            # 移除置顶标志
            flags = self.windowFlags()
            if flags & Qt.WindowStaysOnTopHint:
                self.setWindowFlags(flags ^ Qt.WindowStaysOnTopHint)
            self.show()
    
    def dragEnterEvent(self, event):
        """处理拖拽进入事件"""
        # 检查拖拽的文件是否为本地文件
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    event.acceptProposedAction()
                    return
        event.ignore()
    
    def dragMoveEvent(self, event):
        """处理拖拽移动事件"""
        # 检查拖拽的文件是否为本地文件
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    event.acceptProposedAction()
                    return
        event.ignore()
    
    def dropEvent(self, event):
        """处理拖拽释放事件"""
        # 处理拖拽的APK文件
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    file_path = url.toLocalFile()
                    self.get_apk_info(file_path)
                    break
        event.acceptProposedAction()

    def get_apk_info(self, apk_path):
        """获取APK信息核心处理部分，后台线程进行文件解析处理"""
        # 禁用主界面控件
        self.disable_main_controls()
        # 处理新apk前，先清空UI
        self.clear_ui()
        self.certs = None
        # 显示正在解析的状态
        self.show_parsing_status("正在解析应用信息...")
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        app_logger.info(f"[{current_time}] ==== 开始解析文件：{apk_path}", extra={"show_func": False})
        
        # 简单验证文件是否为合规的apk格式文件
        validation_result, validation_msg = self.validate_apk_file(apk_path)
        if not validation_result:
            self.show_error_message(validation_msg)
            app_logger.error(f"{validation_msg}")
            self.enable_main_controls()
            return
        
        # 设置当前APK路径
        self.current_apk_path = apk_path
        # 调用后台线程，设置回调函数
        self.worker = ApkWorker(apk_path)
        self.worker.app_info_finished.connect(self.on_app_info_finished)
        self.worker.signature_info_finished.connect(self.on_signature_info_finished)
        self.worker.file_info_finished.connect(self.on_file_info_finished)
        self.worker.icon_finished.connect(self.on_icon_finished)
        self.worker.progress_update.connect(self.show_parsing_status)
        # 初始化线程中的任务运行状态是否结束
        self.apk_info_status = False
        self.signature_info_status = False
        self.file_info_status = False
        self.icon_info_status = False
        # 启动后台线程
        self.worker_thread = self.worker
        self.worker_thread.start()
    
    def validate_apk_file(self, apk_path):
        """验证APK文件是否有效（检查是否为ZIP格式并包含AndroidManifest.xml）"""
        try:
            with zipfile.ZipFile(apk_path, 'r') as zip_file:
                # 1.检查是否为有效的ZIP文件
                file_list = zip_file.namelist()
                # 2.检查ZIP文件内根目录下是否存在AndroidManifest.xml
                has_manifest = any(name == 'AndroidManifest.xml' for name in file_list)
                if not has_manifest:
                    return False, f"解析失败，不是一个有效的APK文件(缺少AndroidManifest.xml文件)：\n{apk_path}"
                
                return True, "验证通过"
        except zipfile.BadZipFile:
            return False, f"解析失败，不是一个有效的APK文件(不是有效的ZIP格式)：\n{apk_path}"
        except FileNotFoundError:
            return False, f"解析失败，文件不存在：\n{apk_path}"
        except PermissionError:
            return False, f"解析失败，没有权限访问文件：\n{apk_path}"
        except Exception as e:
            return False, f"解析失败，验证APK文件时发生错误：\n{str(e)}"
    
    def cancel_parsing(self):
        """取消当前解析操作"""
        if self.worker and self.worker_thread:
            self.worker.stop()
            self.enable_main_controls()
            self.show_error_message("解析操作已被取消")
    
    def on_app_info_finished(self, apk_info, error_message, done):
        """处理应用信息解析完成的回调"""
        # 保存应用信息
        self.apk_info = apk_info
        self.apk_info_status = done
        
        if not done:    # 如果任务没有执行完成，则不会显示最后的信息
            return
        
        # 检查是否有错误
        if error_message:
            app_logger.error(f"应用信息解析失败: {error_message}")
            self.show_error_message(f"应用信息解析失败: {error_message}")
        else:
            # 显示应用信息
            self.display_app_info()
            self.display_permissions()
        
        # 检查是否所有信息都已获取，如果是则启用主控件
        self.check_all_info_completed()
    
    def on_icon_finished(self, icon_data, error_message, apk_icon_info, done):
        """处理图标解析完成的回调"""
        # 保存图标信息
        self.apk_icon_info = apk_icon_info
        self.icon_info_status = done
        
        if not done:    # 如果任务没有执行完成，则不会显示最后的信息
            self.icon_label.setText("正在\n解析中")
            self.icon_size_label.setText("")
            return
        
        # 检查是否有错误
        if error_message:
            app_logger.error(f"图标解析失败: {error_message}")
            self.icon_label.setText("图标\n解析\n失败")
            self.icon_label.setOriginalPixmap(None)
            self.icon_size_label.setText("")
        else:
            # 显示图标
            self.display_app_icon_from_data(icon_data, self.apk_icon_info['icon_sure'])
        
        # 检查是否所有信息都已获取，如果是则启用主控件
        self.check_all_info_completed()
    
    def on_signature_info_finished(self, signature_info, certs, error_message, done):
        """处理签名信息解析完成的回调"""
        # 保存签名信息
        self.signature_info = signature_info
        self.certs = certs
        self.signature_info_status = done
        
        # 检查是否有错误
        if error_message:
            app_logger.error(f"签名信息解析失败：{error_message}")
            self.sig_info_text.setText(f"签名信息解析失败：\n{error_message}")
        else:
            # 显示签名信息，或正在处理的提示信息
            self.sig_info_text.setText(self.signature_info)
            if done:    # 如果处理完成了，才显示按钮
                self.show_signature_details_btn.setEnabled(True)
        QApplication.processEvents()  # 强制更新UI
        
        # 检查是否所有信息都已获取，如果是则启用主控件
        self.check_all_info_completed()
    
    def on_file_info_finished(self, file_info, error_message, done):
        """处理文件信息解析完成的回调"""
        # 保存文件信息
        self.file_info = file_info
        self.file_info_status = done
        
        # 检查是否有错误
        if error_message:
            app_logger.error(f"文件信息解析失败: {error_message}")
            self.file_info_text.setText(f"文件信息解析失败：\n{error_message}")
        else:
            # 显示文件信息
            self.file_info_text.setText(self.file_info)
        QApplication.processEvents()  # 强制更新UI
        
        # 检查是否所有信息都已获取，如果是则启用主控件
        self.check_all_info_completed()
    
    def check_all_info_completed(self):
        """检查是否所有信息都已完成解析，如果是则启用主控件"""
        # 全部解析完成（包括解析失败也算是完成）
        if (self.apk_info_status and self.signature_info_status and self.file_info_status and self.icon_info_status):
            # 添加解析完成的日志
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            app_logger.info(f"[{current_time}] ==== 完成解析", extra={"show_func": False})
            
            # 启用主界面控件
            self.enable_main_controls()
            self.copy_info_button.setEnabled(True)
            self.save_info_button.setEnabled(True)
            
            # 清理线程资源
            if self.worker_thread:
                self.worker_thread.quit()
                self.worker_thread.wait()
                self.worker_thread = None
            self.worker = None


# 设置apk关联小窗口
class AssociationSettingsDialog(QDialog):
    """
    APK文件关联设置对话框。
    
    用于设置或取消APK文件与本程序的关联，关联后双击APK文件
    会自动使用本程序打开。
    
    Attributes:
        status_label: 显示当前关联状态的标签
        reg_button: 关联APK按钮
        unreg_button: 取消关联APK按钮
    """
    
    def __init__(self, parent=None):
        """
        初始化关联设置对话框。
        
        Args:
            parent: 父窗口，通常是ApkHelper主窗口
        """
        super().__init__(parent)
        self.setWindowTitle("APK关联设置")
        self.setModal(True)
        self.resize(350, 200)  # 增加窗口大小以容纳更多信息
        
        layout = QVBoxLayout()
        
        # 状态显示标签
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignCenter)
        self.update_status()
        layout.addWidget(self.status_label)
        
        # 提示信息标签
        hint_label = QLabel("关联APK是指将APK文件与本程序进行绑定，\n双击APK文件时会自动使用本程序打开。")
        hint_label.setAlignment(Qt.AlignCenter)
        hint_label.setWordWrap(True)  # 允许文字换行
        hint_label.setStyleSheet("color: gray; font-size: 12px;")  # 设置样式
        layout.addWidget(hint_label)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        
        # 关联APK按钮
        self.reg_button = QPushButton("关联APK")
        self.reg_button.setFixedWidth(100)  # 设置固定宽度
        self.reg_button.setToolTip("将APK文件与本程序进行关联，双击APK文件时会自动使用本程序打开")
        self.reg_button.clicked.connect(self.reg_apk)
        button_layout.addWidget(self.reg_button)
        
        button_layout.setSpacing(20)  # 按钮间距
        
        # 取消关联APK按钮
        self.unreg_button = QPushButton("取消关联APK")
        self.unreg_button.setFixedWidth(100)  # 设置固定宽度
        self.unreg_button.setToolTip("取消APK文件与本程序的关联")
        self.unreg_button.clicked.connect(self.unreg_apk)
        button_layout.addWidget(self.unreg_button)
        
        layout.addLayout(button_layout)
        layout.addSpacing(15)  # 在两个按钮组之间增加垂直间距
        
        # 添加关闭按钮
        close_button = QPushButton("关闭")
        close_button.setMaximumWidth(100)  # 限制最大宽度
        close_button.clicked.connect(self.close)
        # 创建一个水平布局并将关闭按钮居中放置
        close_layout = QHBoxLayout()
        close_layout.addStretch()  # 左侧弹性空间
        close_layout.addWidget(close_button)  # 居中的关闭按钮
        close_layout.addStretch()  # 右侧弹性空间
        layout.addLayout(close_layout)
        
        self.setLayout(layout)
        
        # 默认聚焦到关闭按钮
        close_button.setFocus()
    
    def update_status(self):
        """
        更新关联状态显示。
        
        检查注册表中的APK文件关联状态，并更新状态标签显示。
        """
        # 检查APK文件是否已关联到此程序（通过检查注册表）
        is_associated = self.check_apk_association()
        if is_associated:
            status_text = "APK文件关联状态: 已关联"
        else:
            status_text = "APK文件关联状态: 未关联"
            
        self.status_label.setText(status_text)
    
    def check_apk_association(self):
        """
        检查APK文件是否已关联到当前程序。
        
        通过检查Windows注册表中的相关键值来判断关联状态：
        - HKCR\ApkFile.apkhelper
        - HKCU\...\FileExts\.apk\OpenWithProgids\ApkFile.apkhelper
        
        Returns:
            bool: 已关联返回True，否则返回False
        """
        try:
            # 检查HKCR\ApkFile.apkhelper是否存在
            hkcr_condition = False
            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "ApkFile.apkhelper", 0, winreg.KEY_READ):
                    hkcr_condition = True
                    app_logger.debug("找到 HKCR\\ApkFile.apkhelper 注册表项")
            except OSError as e:
                app_logger.debug(f"未找到 HKCR\\ApkFile.apkhelper 注册表项: {e}")
            
            # 检查HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.apk\OpenWithProgids中是否存在ApkFile.apkhelper
            hkcu_condition = False
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.apk\OpenWithProgids", 0, winreg.KEY_READ) as key:
                    try:
                        val, val_type = winreg.QueryValueEx(key, "ApkFile.apkhelper")
                        if val is not None:
                            hkcu_condition = True
                            app_logger.debug(f"找到 OpenWithProgids 中的 ApkFile.apkhelper: {val}")
                    except OSError as e:
                        app_logger.debug(f"OpenWithProgids 中无 ApkFile.apkhelper 项: {e}")
            except OSError as e:
                app_logger.debug(f"无法打开 OpenWithProgids 注册表项: {e}")
            
            # 两个条件都满足才算已关联
            result = hkcr_condition and hkcu_condition
            app_logger.debug(f"检查结果: hkcr={hkcr_condition}, hkcu={hkcu_condition}, 关联状态={result}")
            return result
        except ImportError:
            app_logger.info("非Windows系统")
            return False
        except Exception as e:
            app_logger.warning(f"检查APK关联状态时出错: {e}")
            return False
    
    def reg_apk(self):
        """
        执行关联APK操作。
        
        调用父窗口的reg_apk方法执行关联，然后更新状态显示。
        """
        self.parent().reg_apk()
        self.update_status()
    
    def unreg_apk(self):
        """
        执行取消关联APK操作。
        
        调用父窗口的unreg_apk方法取消关联，然后更新状态显示。
        """
        self.parent().unreg_apk()
        self.update_status()


# 签名详情小窗口
class SignatureDetailsDialog(QDialog):
    """
    APK签名详情对话框。
    
    显示APK签名的完整信息，并支持证书哈希值比较功能。
    可用于验证APK是否使用特定证书签名。
    
    Attributes:
        signature_text: 签名信息文本框
        hash_input: 哈希值输入框
        compare_hash_btn: 比较按钮
        hash_result_label: 比较结果显示标签
        certs: 证书数据列表
        certs_hash: 证书哈希值列表
    """
    
    def __init__(self, signature_text, parent):
        """
        初始化签名详情对话框。
        
        Args:
            signature_text: 签名信息文本
            parent: 父窗口，用于获取证书数据
        """
        super().__init__(parent)
        self.setWindowTitle("签名详情")
        self.setModal(True)
        self.resize(600, 500)  # 设置默认大小
        
        layout = QVBoxLayout()
        
        # 创建只读文本框显示签名信息
        self.signature_text = QTextEdit()
        self.signature_text.setReadOnly(True)  # 设置为只读，允许选择复制
        self.signature_text.setText(signature_text)
        layout.addWidget(self.signature_text)
        
        # 证书哈希值比较区域
        hash_compare_group = QGroupBox("证书哈希值比较(MD5/SHA1/SHA256/SHA512)")
        hash_layout = QVBoxLayout(hash_compare_group)
        
        # 哈希值输入框
        input_layout = QHBoxLayout()
        input_layout.addWidget(QLabel("请输入证书哈希值:"))
        self.hash_input = QLineEdit()
        input_layout.addWidget(self.hash_input)
        
        # 哈希值比较按钮
        self.compare_hash_btn = QPushButton("比较哈希值")
        self.compare_hash_btn.setToolTip("比较输入的哈希值与APK证书的哈希值是否一致")
        self.compare_hash_btn.clicked.connect(self.compare_hash)
        input_layout.addWidget(self.compare_hash_btn)
        
        hash_layout.addLayout(input_layout)
        
        # 哈希比较结果显示
        self.hash_result_label = QLabel()
        hash_layout.addWidget(self.hash_result_label)
        self.hash_result_label.setText(" ")
        self.hash_result_label.setStyleSheet("color: blue; font-weight: bold;")
        
        layout.addWidget(hash_compare_group)
        
        # 关闭按钮布局
        close_layout = QHBoxLayout()
        close_layout.addStretch()  # 左侧弹性空间
        
        self.close_button = QPushButton("关闭")
        self.close_button.setMaximumWidth(100)  # 限制最大宽度
        self.close_button.clicked.connect(self.close)
        close_layout.addWidget(self.close_button)
        
        close_layout.addStretch()  # 右侧弹性空间
        layout.addLayout(close_layout)
        
        self.setLayout(layout)
        
        # 默认聚焦到关闭按钮
        self.close_button.setFocus()
        
        self.certs = parent.certs
        self.has_hash = False
        self.certs_hash = []
        self.check_certs(self.certs)
    
    def check_certs(self, certs):
        """
        检查签名信息中是否包含证书，并计算证书哈希值。
        
        遍历证书列表，计算每个证书的MD5、SHA1、SHA256、SHA512哈希值。
        根据是否有证书决定是否启用哈希比较功能。
        
        Args:
            certs: 证书二进制数据列表
        """
        if certs:
            for cert in certs:
                try:
                    self.certs_hash.append({"MD5":f"{hashlib.md5(cert).hexdigest().upper()}",
                                            "SHA1":f"{hashlib.sha1(cert).hexdigest().upper()}",
                                            "SHA256":f"{hashlib.sha256(cert).hexdigest().upper()}",
                                            "SHA512":f"{hashlib.sha512(cert).hexdigest().upper()}",
                                            })
                except Exception as e:
                    self.hash_result_label.setText(f"[check_certs] 出错: {e}")
                    self.hash_result_label.setStyleSheet("color: red; font-weight: bold;")
        # app_logger.debug(f"certs_hash: {self.certs_hash}")
        if self.certs_hash and len(self.certs_hash) > 0:
            self.has_hash = True
        else:
            self.hash_input.setPlaceholderText("当前APK文件无证书信息，无法进行证书哈希值比较！")
            self.has_hash = False

        self.hash_input.setEnabled(self.has_hash)
        self.compare_hash_btn.setEnabled(self.has_hash)
        
    def compare_hash(self):
        """
        比较输入的哈希值与APK证书的哈希值。
        
        根据输入哈希值的长度自动识别哈希类型（MD5/SHA1/SHA256/SHA512），
        然后与APK证书的对应哈希值进行比较，显示匹配结果。
        """
        if not self.has_hash:    # 没有证书hash，直接不比较
            self.hash_input.setPlaceholderText("当前APK文件无证书信息，无法进行证书哈希值比较！")
            self.hash_result_label.setText(" ")
            self.hash_result_label.setStyleSheet("color: blue; font-weight: bold;")
            return
        
        input_hash = self.hash_input.text().strip()
        if not input_hash:
            self.hash_result_label.setText("请输入要比较的证书哈希值(MD5/SHA1/SHA256/SHA512)...")
            self.hash_result_label.setStyleSheet("color: blue; font-weight: bold;")
            return
        
        # 移除输入的哈希值中的空格和转换为大写
        input_hash = input_hash.replace(" ", "").upper()
        
        # 根据输入长度判断哈希类型
        hash_type = self.identify_hash_type(input_hash)
        if not hash_type:
            self.hash_result_label.setText("输入有误，不是一个有效的证书哈希值(MD5/SHA1/SHA256/SHA512)！")
            self.hash_result_label.setStyleSheet("color: red; font-weight: bold;")
            return

        match_found = False
        # 遍历所有证书hash，检查是否有匹配
        for cert_hash in self.certs_hash:
            if cert_hash[hash_type] == input_hash:
                match_found = True
                break
        
        # 显示比较结果
        if match_found:
            self.hash_result_label.setText(f"{hash_type}哈希值匹配成功，证书一致！")
            self.hash_result_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.hash_result_label.setText(f"{hash_type}哈希值不匹配，证书不一致！")
            self.hash_result_label.setStyleSheet("color: red; font-weight: bold;")
    
    def identify_hash_type(self, hash_value):
        """
        根据哈希值长度识别哈希类型。
        
        Args:
            hash_value: 哈希值字符串（不含空格的大写形式）
            
        Returns:
            str: 哈希类型名称（'MD5', 'SHA1', 'SHA256', 'SHA512'）
            None: 无法识别的哈希长度时返回None
        """
        length = len(hash_value)
        if length == 32:
            return 'MD5'
        elif length == 40:
            return 'SHA1'
        elif length == 64:
            return 'SHA256'
        elif length == 128:
            return 'SHA512'
        else:
            return None


class ChineseHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """
    自定义帮助信息格式化器，将标题翻译为中文
    
    继承 RawDescriptionHelpFormatter 以保留 epilog 中的原始格式
    """
    def __init__(self, prog, indent_increment=2, max_help_position=24, width=None):
        super().__init__(prog, indent_increment, max_help_position, width)
    
    def start_section(self, heading):
        # 翻译标题
        heading_map = {
            'positional arguments': '位置参数',
            'optional arguments': '可选参数',
            'options': '选项',
        }
        heading = heading_map.get(heading, heading)
        super().start_section(heading)


# ============================================================================
# 主程序入口
# ============================================================================

def main():
    """主函数"""
    setup_logger()    # 初始化日志输出

    global BASE_DIR, PRO_DIR
    # 获取当前脚本或可执行文件的目录
    if getattr(sys, 'frozen', False):
        # 当在exe中运行时
        if getattr(sys, '_MEIPASS', False):
            BASE_DIR = sys._MEIPASS
        else:
            BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
        PRO_DIR = os.path.dirname(os.path.abspath(sys.executable))
    else:
        # 当在脚本中运行时
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        PRO_DIR = BASE_DIR
    
    # 解析命令行参数，支持 -h, --help
    parser = argparse.ArgumentParser(
        description=f'APK文件信息解析工具 {b_ver}-{b_date}',
        formatter_class=ChineseHelpFormatter)
    parser.add_argument('apk_file', nargs='?', help='要解析的APK文件路径')
    parser.add_argument('-l', '--log-level', 
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'D', 'I', 'W', 'E'],
                       default='INFO', 
                       help='设置日志级别 (默认: INFO)。支持简写: D=DEBUG, I=INFO, W=WARNING, E=ERROR')
    args = parser.parse_args()
    
    # 日志级别简写映射
    log_level_map = {
        'D': 'DEBUG',
        'I': 'INFO',
        'W': 'WARNING',
        'E': 'ERROR'
    }
    
    # 设置日志级别（支持简写和全拼）
    log_level = args.log_level
    if log_level in log_level_map:
        log_level = log_level_map[log_level]
    if log_level != "INFO":
        set_log_level(log_level)
    
    # 如果提供了APK文件路径参数，传递给主程序进行处理，这里不做文件路径检测。
    apk_file_path = args.apk_file
    if args.apk_file:
        if os.path.isfile(args.apk_file):
            apk_file_path = os.path.abspath(args.apk_file)
    
    # 启用高 DPI 缩放、启用高 DPI 位图支持
    QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    
    # 全局禁用 Windows 窗口标题栏上的“上下文帮助按钮”（也就是那个问号按钮）
    QCoreApplication.setAttribute(Qt.AA_DisableWindowContextHelpButton)
    
    app = QApplication(sys.argv)
    
    # 加载应用程序自定义的中文翻译文件
    translators = []  # 保持引用，防止被垃圾回收
    qm_file = os.path.join(BASE_DIR, "translations", "qt5_all_zh_CN.qm")
    translator = QTranslator()
    if translator.load(qm_file):
        app_logger.debug(f"成功加载应用程序翻译文件: {qm_file}")
        app.installTranslator(translator)
        translators.append(translator)  # 保存引用
    else:
        app_logger.error(f"无法加载应用程序翻译文件: {qm_file}")
    
    # 加载程序图标
    icon_path = os.path.join(BASE_DIR, "1.ico")
    pixmap = QPixmap()
    if pixmap.load(icon_path):
        app.setWindowIcon(QIcon(pixmap))
        app_logger.debug(f"成功加载程序图标: {icon_path}")
    else:
        app_logger.error(f"无法加载程序图标: {icon_path}")
    
    # 继续运行程序
    set_log("WARNING")  # 设置androguard日志级别，建议至少是 WARNING 或 ERROR
    window = ApkHelper()
    
    # 如果提供了APK文件路径，在主窗口显示后立即解析该文件
    if apk_file_path:
        # 使用QTimer确保UI完全加载后再处理文件
        def load_apk_file():
            window.get_apk_info(apk_file_path)
        
        QTimer.singleShot(100, load_apk_file)
    
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    print('')  # 先输出一个空行，为了适应 nuitka 打包成GUI程序后，在控制台输出内容
    main()
