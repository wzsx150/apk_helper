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
import json
import struct
import time
from io import BytesIO
from PIL import Image, ImageDraw

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QHeaderView, QDesktopWidget,
    QPushButton, QFileDialog, QTextEdit, QLabel, QGroupBox, QSizePolicy, QMessageBox, QLineEdit,
    QTableWidget, QTableWidgetItem, QGridLayout, QSplitter, QStackedWidget, QDialog, QCheckBox,
    QComboBox, QTabWidget, QMenu
)
from PyQt5.QtGui import QPixmap, QIcon, QTextOption, QCursor, QFontMetrics
from PyQt5.QtCore import Qt, QSize, QTimer, QTranslator, QCoreApplication, QThread, pyqtSignal


## APK文件信息解析工具-APK Helper，方便查看 apk 的主要信息。

# 使用 nuitka 打包成32位exe的命令：
# py3.8_32 -m nuitka --standalone --assume-yes-for-downloads --windows-console-mode=disable --output-dir=dist --enable-plugin=pyqt5 --windows-icon-from-ico=1.ico --include-data-files=1.ico=./ --include-data-files=aapt2.exe=./ --include-data-files=*.bat=./ --include-raw-dir=translations=translations apk_helper.py
# 控制台模式说明（--windows-console-mode=disable）：打包成GUI程序（无控制台窗口），命令行执行时也不会输出内容，但可以使用 > 和 >> 重定向输出。
# 看似 attach 模式更合适，但是会有其他问题，比如运行cmd命令会报句柄错误。
# 所以最终采用 disable 模式 + 代码输出到控制台的方案。

# aapt2 版本：2.19 (build-tools_r33.0.3内置的版本)，是32位exe程序。aapt2.exe从2.20开始，默认是64位exe程序。解析出来的部分字段名称也不一样。
# 本程序均基于该版本的 aapt2 输出的内容，进行解析得到的结果。

# ============================================================================
# 全局变量和常量定义
# ============================================================================

b_ver = "5.0"
b_date = "20260321"
b_auth = "wzsx150"
is_arch_64bit = True    # 暂时没用，主要是用于不同位数系统时不同处理方式
BASE_DIR = ""    # 基目录，可能会在临时目录
PRO_DIR = ""     # 程序或者脚本实际所在目录
USE_NATIVE_AXML_PARSER = True    # 是否使用python代码解析AXML，如果选否，则会使用aapt2解析AXML
MAX_RECURSION_DEPTH = 6    # 资源引用递归深度限制
WINDOWS_BUILD_VERSION = 0    # Windows系统build版本号，用于判断是否为Win11及以上版本

# MSIX包在注册表中的完整子键名称，格式: <Name>_<Version>_<Arch>__<PublisherHash>
# 同一个MSIX包在不同Win11电脑上的此名称完全一致，由包名、版本、架构和发布者哈希值决定
# 用于快速检测MSIX是否已安装，直接检查该子键是否存在即可，无需遍历所有包
# 安装MSIX后，可在以下注册表路径下找到此子键：
#   HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Appx\AppxAllUserStore\Applications
#   HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages
MSIX_PACKAGE_REG_NAME = "ApkHelperContextMenu_1.0.0.0_neutral__fzjcw6gemqd32"

# 表格控件样式表，包含表格整体、单元格、表头的字体和布局设置。
# 如果只修改字体，应使用父选择器(QTableWidget、QHeaderView)而非子选择器，以保留 Qt 默认的绘制效果（悬停、选中、边框等）。
# padding: 上 右 下 左;
TABLE_WIDGET_STYLE = """
    QTableWidget {
        font-family: "SimSun", "Microsoft YaHei", "SimHei", sans-serif;
        font-size: 9pt;
    }
    QTableWidget::item {
        padding: 0px 0px 0px 0px;
    }
    QHeaderView {
        font-family: "SimSun", "Microsoft YaHei", "SimHei", sans-serif;
        font-size: 9pt;
    }
    QHeaderView::section {
        font-weight: normal;
        background-color: #f0f0f0;
        border-bottom: 1px solid #a0a0a0;
        border-right: 1px solid #a0a0a0;
        padding: 0px 0px 0px 0px;
    }
    QHeaderView::section:hover {
        background-color: #d9ebf9;
    }
"""

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


def get_long_path(short_path):
    """
    将短路径格式转换为长路径格式。
    
    Args:
        short_path: 短路径格式的文件或目录路径
        
    Returns:
        str: 长路径格式的路径，如果转换失败则返回原路径
    """
    if not short_path:
        return short_path
    try:
        buffer_size = ctypes.windll.kernel32.GetLongPathNameW(short_path, None, 0)
        if buffer_size > 0:
            buffer = ctypes.create_unicode_buffer(buffer_size)
            ctypes.windll.kernel32.GetLongPathNameW(short_path, buffer, buffer_size)
            return buffer.value
    except Exception as e:
        app_logger.debug(f"转换长路径失败: {e}")
    return short_path


def refresh_file_association_icon():
    """
    刷新Windows文件关联图标。
    
    在修改文件关联注册表后调用此函数，可以立即刷新资源管理器中
    相关文件的图标显示，使图标变化立即生效。
    
    实现原理：
    调用 SHChangeNotify API 通知系统文件关联已更改，
    系统会自动刷新图标显示，无需重启资源管理器。
    
    Returns:
        bool: 刷新成功返回True，失败返回False
    
    Note:
        此函数仅适用于Windows系统，在其他系统上会直接返回False
    """
    try:
        shell32 = ctypes.windll.shell32
        
        SHCNE_ASSOCCHANGED = 0x08000000
        SHCNF_IDLIST = 0x0000
        SHCNF_FLUSH = 0x1000
        
        shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST | SHCNF_FLUSH, None, None)
        
        app_logger.debug("已发送文件关联刷新通知 (SHChangeNotify)")
        return True
    except AttributeError:
        app_logger.warning("当前系统不支持 SHChangeNotify API")
        return False
    except Exception as e:
        app_logger.warning(f"刷新文件关联图标失败: {e}")
        return False


RES_XML_TYPE = 0x0003
RES_STRING_POOL_TYPE = 0x0001
RES_XML_RESOURCE_MAP_TYPE = 0x0180
RES_XML_START_NAMESPACE_TYPE = 0x0100
RES_XML_END_NAMESPACE_TYPE = 0x0101
RES_XML_START_ELEMENT_TYPE = 0x0102
RES_XML_END_ELEMENT_TYPE = 0x0103
RES_XML_CDATA_TYPE = 0x0104

TYPE_NULL = 0x00
TYPE_REFERENCE = 0x01
TYPE_ATTRIBUTE = 0x02
TYPE_STRING = 0x03
TYPE_FLOAT = 0x04
TYPE_DIMENSION = 0x05
TYPE_FRACTION = 0x06
TYPE_INT_DEC = 0x10
TYPE_INT_HEX = 0x11
TYPE_INT_BOOLEAN = 0x12
TYPE_INT_COLOR_ARGB8 = 0x1c
TYPE_INT_COLOR_RGB8 = 0x1d
TYPE_INT_COLOR_ARGB4 = 0x1e
TYPE_INT_COLOR_RGB4 = 0x1f
UTF8_FLAG = 1 << 8

# 密度数值到名称的映射（参考 Android 源码 ResourceTypes.cpp 和 ResourceTypes.h）
DENSITY_NAME_MAP = {
    120: 'ldpi',        # DENSITY_LOW
    160: 'mdpi',        # DENSITY_MEDIUM
    213: 'tvdpi',       # DENSITY_TV
    240: 'hdpi',        # DENSITY_HIGH
    320: 'xhdpi',       # DENSITY_XHIGH
    480: 'xxhdpi',      # DENSITY_XXHIGH
    640: 'xxxhdpi',     # DENSITY_XXXHIGH
    65534: 'anydpi',    # DENSITY_ANY = 0xfffe (65534)
    65535: 'nodpi',     # DENSITY_NONE = 0xffff (65535)
}

# 语言代码到中文名称的映射字典
# 包含 ISO 639-1 语言代码和 ISO 639-1 + ISO 3166-1 地区代码
# 参考：https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes
LOCALE_NAME_MAP = {
    # =========================================================================
    # 特殊语言代码
    # =========================================================================
    '--_--': ('默认语言', 'Default'),
    
    # =========================================================================
    # ISO 639-1 语言代码（按字母顺序排列）
    # =========================================================================
    'aa': ('阿法尔语', 'Afar'),
    'ab': ('阿布哈兹语', 'Abkhazian'),
    'af': ('南非荷兰语', 'Afrikaans'),
    'ak': ('阿坎语', 'Akan'),
    'am': ('阿姆哈拉语', 'Amharic'),
    'an': ('阿拉贡语', 'Aragonese'),
    'ar': ('阿拉伯语', 'Arabic'),
    'as': ('阿萨姆语', 'Assamese'),
    'av': ('阿瓦尔语', 'Avaric'),
    'ae': ('阿维斯陀语', 'Avestan'),
    'ay': ('艾马拉语', 'Aymara'),
    'az': ('阿塞拜疆语', 'Azerbaijani'),
    'ba': ('巴什基尔语', 'Bashkir'),
    'be': ('白俄罗斯语', 'Belarusian'),
    'bg': ('保加利亚语', 'Bulgarian'),
    'bh': ('比哈尔语', 'Bihari'),
    'bi': ('比斯拉马语', 'Bislama'),
    'bm': ('班巴拉语', 'Bambara'),
    'bn': ('孟加拉语', 'Bengali'),
    'bo': ('藏语', 'Tibetan'),
    'br': ('布列塔尼语', 'Breton'),
    'bs': ('波斯尼亚语', 'Bosnian'),
    'ca': ('加泰罗尼亚语', 'Catalan'),
    'ce': ('车臣语', 'Chechen'),
    'ch': ('查莫罗语', 'Chamorro'),
    'co': ('科西嘉语', 'Corsican'),
    'cr': ('克里语', 'Cree'),
    'cs': ('捷克语', 'Czech'),
    'cu': ('古教会斯拉夫语', 'Old Church Slavonic'),
    'cv': ('楚瓦什语', 'Chuvash'),
    'cy': ('威尔士语', 'Welsh'),
    'da': ('丹麦语', 'Danish'),
    'de': ('德语', 'German'),
    'dv': ('迪维希语', 'Dhivehi'),
    'dz': ('不丹语（宗卡语）', 'Dzongkha'),
    'ee': ('埃维语', 'Ewe'),
    'el': ('希腊语', 'Greek'),
    'en': ('英语', 'English'),
    'eo': ('世界语', 'Esperanto'),
    'es': ('西班牙语', 'Spanish'),
    'et': ('爱沙尼亚语', 'Estonian'),
    'eu': ('巴斯克语', 'Basque'),
    'fa': ('波斯语', 'Persian'),
    'ff': ('富拉语', 'Fulah'),
    'fi': ('芬兰语', 'Finnish'),
    'fj': ('斐济语', 'Fijian'),
    'fo': ('法罗语', 'Faroese'),
    'fr': ('法语', 'French'),
    'fy': ('西弗里西亚语', 'Western Frisian'),
    'ga': ('爱尔兰语', 'Irish'),
    'gd': ('苏格兰盖尔语', 'Scottish Gaelic'),
    'gl': ('加利西亚语', 'Galician'),
    'gn': ('瓜拉尼语', 'Guarani'),
    'gu': ('古吉拉特语', 'Gujarati'),
    'gv': ('马恩语', 'Manx'),
    'ha': ('豪萨语', 'Hausa'),
    'he': ('希伯来语', 'Hebrew'),
    'hi': ('印地语', 'Hindi'),
    'ho': ('希里莫图语', 'Hiri Motu'),
    'hr': ('克罗地亚语', 'Croatian'),
    'ht': ('海地克里奥尔语', 'Haitian'),
    'hu': ('匈牙利语', 'Hungarian'),
    'hy': ('亚美尼亚语', 'Armenian'),
    'hz': ('赫雷罗语', 'Herero'),
    'ia': ('国际语', 'Interlingua'),
    'id': ('印尼语', 'Indonesian'),
    'ie': ('国际语E', 'Interlingue'),
    'ig': ('伊博语', 'Igbo'),
    'ii': ('四川彝语', 'Sichuan Yi'),
    'ik': ('伊努皮克语', 'Inupiaq'),
    'io': ('伊多语', 'Ido'),
    'is': ('冰岛语', 'Icelandic'),
    'it': ('意大利语', 'Italian'),
    'iu': ('因纽特语', 'Inuktitut'),
    'ja': ('日语', 'Japanese'),
    'jv': ('爪哇语', 'Javanese'),
    'ka': ('格鲁吉亚语', 'Georgian'),
    'kg': ('刚果语', 'Kongo'),
    'ki': ('基库尤语', 'Kikuyu'),
    'kj': ('宽亚玛语', 'Kuanyama'),
    'kk': ('哈萨克语', 'Kazakh'),
    'kl': ('格陵兰语', 'Kalaallisut'),
    'km': ('高棉语', 'Khmer'),
    'kn': ('卡纳达语', 'Kannada'),
    'ko': ('韩语', 'Korean'),
    'kr': ('卡努里语', 'Kanuri'),
    'ks': ('克什米尔语', 'Kashmiri'),
    'ku': ('库尔德语', 'Kurdish'),
    'kv': ('科米语', 'Komi'),
    'kw': ('康沃尔语', 'Cornish'),
    'ky': ('吉尔吉斯语', 'Kyrgyz'),
    'la': ('拉丁语', 'Latin'),
    'lb': ('卢森堡语', 'Luxembourgish'),
    'lg': ('干达语', 'Ganda'),
    'li': ('林堡语', 'Limburgan'),
    'ln': ('林加拉语', 'Lingala'),
    'lo': ('老挝语', 'Lao'),
    'lt': ('立陶宛语', 'Lithuanian'),
    'lu': ('卢巴-加丹加语', 'Luba-Katanga'),
    'lv': ('拉脱维亚语', 'Latvian'),
    'mg': ('马达加斯加语', 'Malagasy'),
    'mh': ('马绍尔语', 'Marshallese'),
    'mi': ('毛利语', 'Maori'),
    'mk': ('马其顿语', 'Macedonian'),
    'ml': ('马拉雅拉姆语', 'Malayalam'),
    'mn': ('蒙古语', 'Mongolian'),
    'mo': ('摩尔达维亚语', 'Moldovan'),  # ISO 639-1 代码（已弃用，现为 ro 的变体）
    'mr': ('马拉地语', 'Marathi'),
    'ms': ('马来语', 'Malay'),
    'mt': ('马耳他语', 'Maltese'),
    'my': ('缅甸语', 'Burmese'),
    'na': ('瑙鲁语', 'Nauru'),
    'nb': ('挪威博克马尔语', 'Norwegian Bokmål'),
    'nd': ('北恩德贝莱语', 'North Ndebele'),
    'ne': ('尼泊尔语', 'Nepali'),
    'ng': ('恩敦加语', 'Ndonga'),
    'nl': ('荷兰语', 'Dutch'),
    'nn': ('挪威尼诺斯克语', 'Norwegian Nynorsk'),
    'no': ('挪威语', 'Norwegian'),
    'nr': ('南恩德贝莱语', 'South Ndebele'),
    'nv': ('纳瓦霍语', 'Navajo'),
    'ny': ('尼扬贾语', 'Chichewa'),
    'oc': ('奥克语', 'Occitan'),
    'oj': ('奥吉布瓦语', 'Ojibwa'),
    'om': ('奥罗莫语', 'Oromo'),
    'or': ('奥里亚语', 'Oriya'),
    'os': ('奥塞梯语', 'Ossetian'),
    'pa': ('旁遮普语', 'Punjabi'),
    'pi': ('巴利语', 'Pali'),
    'pl': ('波兰语', 'Polish'),
    'ps': ('普什图语', 'Pushto'),
    'pt': ('葡萄牙语', 'Portuguese'),
    'qu': ('克丘亚语', 'Quechua'),
    'rm': ('罗曼什语', 'Romansh'),
    'rn': ('基隆迪语', 'Rundi'),
    'ro': ('罗马尼亚语', 'Romanian'),
    'ru': ('俄语', 'Russian'),
    'rw': ('基尼亚卢旺达语', 'Kinyarwanda'),
    'sa': ('梵语', 'Sanskrit'),
    'sc': ('撒丁语', 'Sardinian'),
    'sd': ('信德语', 'Sindhi'),
    'se': ('北萨米语', 'Northern Sami'),
    'sg': ('桑戈语', 'Sango'),
    'sh': ('塞尔维亚-克罗地亚语', 'Serbo-Croatian'),  # ISO 639-1 代码（已弃用，但仍使用）
    'si': ('僧伽罗语', 'Sinhala'),
    'sk': ('斯洛伐克语', 'Slovak'),
    'sl': ('斯洛文尼亚语', 'Slovenian'),
    'sm': ('萨摩亚语', 'Samoan'),
    'sn': ('绍纳语', 'Shona'),
    'so': ('索马里语', 'Somali'),
    'sq': ('阿尔巴尼亚语', 'Albanian'),
    'sr': ('塞尔维亚语', 'Serbian'),
    'ss': ('斯瓦蒂语', 'Swati'),
    'st': ('南索托语', 'Southern Sotho'),
    'su': ('巽他语', 'Sundanese'),
    'sv': ('瑞典语', 'Swedish'),
    'sw': ('斯瓦希里语', 'Swahili'),
    'ta': ('泰米尔语', 'Tamil'),
    'te': ('泰卢固语', 'Telugu'),
    'tg': ('塔吉克语', 'Tajik'),
    'th': ('泰语', 'Thai'),
    'ti': ('提格里尼亚语', 'Tigrinya'),
    'tk': ('土库曼语', 'Turkmen'),
    'tl': ('他加禄语', 'Tagalog'),  # 他加禄语（菲律宾主要语言之一）
    'tn': ('茨瓦纳语', 'Tswana'),
    'to': ('汤加语', 'Tonga'),
    'tr': ('土耳其语', 'Turkish'),
    'ts': ('宗加语', 'Tsonga'),
    'tt': ('鞑靼语', 'Tatar'),
    'tw': ('特威语', 'Twi'),
    'ty': ('塔希提语', 'Tahitian'),
    'ug': ('维吾尔语', 'Uighur'),
    'uk': ('乌克兰语', 'Ukrainian'),
    'ur': ('乌尔都语', 'Urdu'),
    'uz': ('乌兹别克语', 'Uzbek'),
    've': ('文达语', 'Venda'),
    'vi': ('越南语', 'Vietnamese'),
    'vo': ('沃拉普克语', 'Volapük'),
    'wa': ('瓦龙语', 'Walloon'),
    'wo': ('沃洛夫语', 'Wolof'),
    'xh': ('科萨语', 'Xhosa'),
    'yi': ('意第绪语', 'Yiddish'),
    'yo': ('约鲁巴语', 'Yoruba'),
    'za': ('壮语', 'Zhuang'),
    'zh': ('中文', 'Chinese'),
    'zu': ('祖鲁语', 'Zulu'),
    
    # =========================================================================
    # 带地区代码的语言（按语言代码分组）
    # =========================================================================
    # 阿拉伯语地区变体
    'ar-AE': ('阿拉伯语（阿联酋）', 'Arabic (United Arab Emirates)'),
    'ar-BH': ('阿拉伯语（巴林）', 'Arabic (Bahrain)'),
    'ar-DZ': ('阿拉伯语（阿尔及利亚）', 'Arabic (Algeria)'),
    'ar-EG': ('阿拉伯语（埃及）', 'Arabic (Egypt)'),
    'ar-KW': ('阿拉伯语（科威特）', 'Arabic (Kuwait)'),
    'ar-MA': ('阿拉伯语（摩洛哥）', 'Arabic (Morocco)'),
    'ar-QA': ('阿拉伯语（卡塔尔）', 'Arabic (Qatar)'),
    'ar-SA': ('阿拉伯语（沙特）', 'Arabic (Saudi Arabia)'),
    'ar-SY': ('阿拉伯语（叙利亚）', 'Arabic (Syria)'),
    'ar-TN': ('阿拉伯语（突尼斯）', 'Arabic (Tunisia)'),
    'ar-XB': ('伪阿拉伯语（双向）', 'Arabic (Pseudo-Bidi)'),  # Android 伪语言，用于测试 RTL 布局
    
    # 中文地区变体
    'zh-CN': ('简体中文（中国）', 'Simplified Chinese (China)'),
    'zh-Hans': ('简体中文', 'Simplified Chinese'),
    'zh-Hans-CN': ('简体中文（中国）', 'Simplified Chinese (China)'),
    'zh-Hans-SG': ('简体中文（新加坡）', 'Simplified Chinese (Singapore)'),
    'zh-HK': ('繁体中文（香港）', 'Traditional Chinese (Hong Kong)'),
    'zh-MO': ('繁体中文（澳门）', 'Traditional Chinese (Macau)'),
    'zh-SG': ('简体中文（新加坡）', 'Simplified Chinese (Singapore)'),
    'zh-TW': ('繁体中文（台湾）', 'Traditional Chinese (Taiwan)'),
    'zh-Hant': ('繁体中文', 'Traditional Chinese'),
    'zh-Hant-HK': ('繁体中文（香港）', 'Traditional Chinese (Hong Kong)'),
    'zh-Hant-TW': ('繁体中文（台湾）', 'Traditional Chinese (Taiwan)'),
    
    # 英语地区变体
    'en-AU': ('英语（澳大利亚）', 'English (Australia)'),
    'en-CA': ('英语（加拿大）', 'English (Canada)'),
    'en-GB': ('英语（英国）', 'English (United Kingdom)'),
    'en-IE': ('英语（爱尔兰）', 'English (Ireland)'),
    'en-IN': ('英语（印度）', 'English (India)'),
    'en-NZ': ('英语（新西兰）', 'English (New Zealand)'),
    'en-PH': ('英语（菲律宾）', 'English (Philippines)'),
    'en-SG': ('英语（新加坡）', 'English (Singapore)'),
    'en-US': ('英语（美国）', 'English (United States)'),
    'en-XA': ('伪英语（重音）', 'English (Pseudo-Accents)'),  # Android 伪语言，用于测试 LTR 布局
    'en-XC': ('伪英语（构建测试）', 'English (Pseudo-Build)'),  # Android 构建系统测试用伪语言
    'en-ZA': ('英语（南非）', 'English (South Africa)'),
    
    # 西班牙语地区变体
    'es-419': ('西班牙语（拉丁美洲）', 'Spanish (Latin America)'),
    'es-AR': ('西班牙语（阿根廷）', 'Spanish (Argentina)'),
    'es-CL': ('西班牙语（智利）', 'Spanish (Chile)'),
    'es-CO': ('西班牙语（哥伦比亚）', 'Spanish (Colombia)'),
    'es-ES': ('西班牙语（西班牙）', 'Spanish (Spain)'),
    'es-MX': ('西班牙语（墨西哥）', 'Spanish (Mexico)'),
    'es-PE': ('西班牙语（秘鲁）', 'Spanish (Peru)'),
    'es-US': ('西班牙语（美国）', 'Spanish (United States)'),
    'es-VE': ('西班牙语（委内瑞拉）', 'Spanish (Venezuela)'),
    
    # 法语地区变体
    'fr-BE': ('法语（比利时）', 'French (Belgium)'),
    'fr-CA': ('法语（加拿大）', 'French (Canada)'),
    'fr-CH': ('法语（瑞士）', 'French (Switzerland)'),
    'fr-FR': ('法语（法国）', 'French (France)'),
    
    # 德语地区变体
    'de-AT': ('德语（奥地利）', 'German (Austria)'),
    'de-CH': ('德语（瑞士）', 'German (Switzerland)'),
    'de-DE': ('德语（德国）', 'German (Germany)'),
    
    # 意大利语地区变体
    'it-CH': ('意大利语（瑞士）', 'Italian (Switzerland)'),
    'it-IT': ('意大利语（意大利）', 'Italian (Italy)'),
    
    # 葡萄牙语地区变体
    'pt-BR': ('葡萄牙语（巴西）', 'Portuguese (Brazil)'),
    'pt-PT': ('葡萄牙语（葡萄牙）', 'Portuguese (Portugal)'),
    
    # 俄语地区变体
    'ru-RU': ('俄语（俄罗斯）', 'Russian (Russia)'),
    
    # 日语、韩语地区变体
    'ja-JP': ('日语（日本）', 'Japanese (Japan)'),
    'ko-KP': ('韩语（朝鲜）', 'Korean (North Korea)'),
    'ko-KR': ('韩语（韩国）', 'Korean (South Korea)'),
    
    # 其他亚洲语言地区变体
    'as-IN': ('阿萨姆语（印度）', 'Assamese (India)'),
    'bn-BD': ('孟加拉语（孟加拉）', 'Bengali (Bangladesh)'),
    'bn-IN': ('孟加拉语（印度）', 'Bengali (India)'),
    'fa-AE': ('波斯语（阿联酋）', 'Persian (UAE)'),
    'fa-AF': ('波斯语（阿富汗）', 'Persian (Afghanistan)'),
    'fa-IR': ('波斯语（伊朗）', 'Persian (Iran)'),
    'gu-IN': ('古吉拉特语（印度）', 'Gujarati (India)'),
    'hi-IN': ('印地语（印度）', 'Hindi (India)'),
    'id-ID': ('印尼语（印尼）', 'Indonesian (Indonesia)'),
    'kn-IN': ('卡纳达语（印度）', 'Kannada (India)'),
    'mai-IN': ('迈蒂利语（印度）', 'Maithili (India)'),
    'ml-IN': ('马拉雅拉姆语（印度）', 'Malayalam (India)'),
    'mr-IN': ('马拉地语（印度）', 'Marathi (India)'),
    'ms-BN': ('马来语（文莱）', 'Malay (Brunei)'),
    'ms-MY': ('马来语（马来西亚）', 'Malay (Malaysia)'),
    'ne-IN': ('尼泊尔语（印度）', 'Nepali (India)'),
    'ne-NP': ('尼泊尔语（尼泊尔）', 'Nepali (Nepal)'),
    'or-IN': ('奥里亚语（印度）', 'Odia (India)'),
    'pa-IN': ('旁遮普语（印度）', 'Punjabi (India)'),
    'pa-PK': ('旁遮普语（巴基斯坦）', 'Punjabi (Pakistan)'),
    'ta-IN': ('泰米尔语（印度）', 'Tamil (India)'),
    'ta-LK': ('泰米尔语（斯里兰卡）', 'Tamil (Sri Lanka)'),
    'ta-MY': ('泰米尔语（马来西亚）', 'Tamil (Malaysia)'),
    'ta-SG': ('泰米尔语（新加坡）', 'Tamil (Singapore)'),
    'te-IN': ('泰卢固语（印度）', 'Telugu (India)'),
    'th-TH': ('泰语（泰国）', 'Thai (Thailand)'),
    'tr-TR': ('土耳其语（土耳其）', 'Turkish (Turkey)'),
    'ur-IN': ('乌尔都语（印度）', 'Urdu (India)'),
    'ur-PK': ('乌尔都语（巴基斯坦）', 'Urdu (Pakistan)'),
    'vi-VN': ('越南语（越南）', 'Vietnamese (Vietnam)'),
    
    # 欧洲语言地区变体
    'af-ZA': ('南非荷兰语（南非）', 'Afrikaans (South Africa)'),
    'am-ET': ('阿姆哈拉语（埃塞俄比亚）', 'Amharic (Ethiopia)'),
    'az-AZ': ('阿塞拜疆语（阿塞拜疆）', 'Azerbaijani (Azerbaijan)'),
    'be-BY': ('白俄罗斯语（白俄罗斯）', 'Belarusian (Belarus)'),
    'bg-BG': ('保加利亚语（保加利亚）', 'Bulgarian (Bulgaria)'),
    'bs-BA': ('波斯尼亚语（波黑）', 'Bosnian (Bosnia)'),
    'ca-AD': ('加泰罗尼亚语（安道尔）', 'Catalan (Andorra)'),
    'ca-ES': ('加泰罗尼亚语（西班牙）', 'Catalan (Spain)'),
    'ca-FR': ('加泰罗尼亚语（法国）', 'Catalan (France)'),
    'ca-IT': ('加泰罗尼亚语（意大利）', 'Catalan (Italy)'),
    'cs-CZ': ('捷克语（捷克）', 'Czech (Czech Republic)'),
    'cy-GB': ('威尔士语（英国）', 'Welsh (United Kingdom)'),
    'da-DK': ('丹麦语（丹麦）', 'Danish (Denmark)'),
    'el-GR': ('希腊语（希腊）', 'Greek (Greece)'),
    'et-EE': ('爱沙尼亚语（爱沙尼亚）', 'Estonian (Estonia)'),
    'eu-ES': ('巴斯克语（西班牙）', 'Basque (Spain)'),
    'eu-FR': ('巴斯克语（法国）', 'Basque (France)'),
    'fi-FI': ('芬兰语（芬兰）', 'Finnish (Finland)'),
    'ga-IE': ('爱尔兰语（爱尔兰）', 'Irish (Ireland)'),
    'gd-GB': ('苏格兰盖尔语（英国）', 'Scottish Gaelic (United Kingdom)'),
    'gl-ES': ('加利西亚语（西班牙）', 'Galician (Spain)'),
    'gl-PT': ('加利西亚语（葡萄牙）', 'Galician (Portugal)'),
    'he-IL': ('希伯来语（以色列）', 'Hebrew (Israel)'),
    'hr-HR': ('克罗地亚语（克罗地亚）', 'Croatian (Croatia)'),
    'hu-HU': ('匈牙利语（匈牙利）', 'Hungarian (Hungary)'),
    'hy-AM': ('亚美尼亚语（亚美尼亚）', 'Armenian (Armenia)'),
    'is-IS': ('冰岛语（冰岛）', 'Icelandic (Iceland)'),
    'ka-GE': ('格鲁吉亚语（格鲁吉亚）', 'Georgian (Georgia)'),
    'kk-KZ': ('哈萨克语（哈萨克斯坦）', 'Kazakh (Kazakhstan)'),
    'km-KH': ('高棉语（柬埔寨）', 'Khmer (Cambodia)'),
    'ku-TR': ('库尔德语（土耳其）', 'Kurdish (Turkey)'),
    'ky-KG': ('吉尔吉斯语（吉尔吉斯斯坦）', 'Kirghiz (Kyrgyzstan)'),
    'ky-KZ': ('吉尔吉斯语（哈萨克斯坦）', 'Kirghiz (Kazakhstan)'),
    'lo-LA': ('老挝语（老挝）', 'Lao (Laos)'),
    'lt-LT': ('立陶宛语（立陶宛）', 'Lithuanian (Lithuania)'),
    'lv-LV': ('拉脱维亚语（拉脱维亚）', 'Latvian (Latvia)'),
    'mk-MK': ('马其顿语（马其顿）', 'Macedonian (Macedonia)'),
    'mn-MN': ('蒙古语（蒙古）', 'Mongolian (Mongolia)'),
    'mt-MT': ('马耳他语（马耳他）', 'Maltese (Malta)'),
    'my-MM': ('缅甸语（缅甸）', 'Burmese (Myanmar)'),
    'nb-NO': ('挪威博克马尔语（挪威）', 'Norwegian Bokmål (Norway)'),
    'nl-BE': ('荷兰语（比利时）', 'Dutch (Belgium)'),
    'nl-NL': ('荷兰语（荷兰）', 'Dutch (Netherlands)'),
    'nn-NO': ('挪威尼诺斯克语（挪威）', 'Norwegian Nynorsk (Norway)'),
    'no-NO': ('挪威语（挪威）', 'Norwegian (Norway)'),
    'oc-FR': ('奥克语（法国）', 'Occitan (France)'),
    'pl-PL': ('波兰语（波兰）', 'Polish (Poland)'),
    'ro-RO': ('罗马尼亚语（罗马尼亚）', 'Romanian (Romania)'),
    'si-LK': ('僧伽罗语（斯里兰卡）', 'Sinhala (Sri Lanka)'),
    'sk-SK': ('斯洛伐克语（斯洛伐克）', 'Slovak (Slovakia)'),
    'sl-SI': ('斯洛文尼亚语（斯洛文尼亚）', 'Slovenian (Slovenia)'),
    'sq-AL': ('阿尔巴尼亚语（阿尔巴尼亚）', 'Albanian (Albania)'),
    'sq-MK': ('阿尔巴尼亚语（马其顿）', 'Albanian (Macedonia)'),
    'sr-BA': ('塞尔维亚语（波黑）', 'Serbian (Bosnia)'),
    'sr-Latn': ('塞尔维亚语（拉丁字母）', 'Serbian (Latin)'),
    'sr-Latn-BA': ('塞尔维亚语拉丁字母（波黑）', 'Serbian Latin (Bosnia)'),
    'sr-Latn-ME': ('塞尔维亚语拉丁字母（黑山）', 'Serbian Latin (Montenegro)'),
    'sr-Latn-RS': ('塞尔维亚语拉丁字母（塞尔维亚）', 'Serbian Latin (Serbia)'),
    'sr-ME': ('塞尔维亚语（黑山）', 'Serbian (Montenegro)'),
    'sr-RS': ('塞尔维亚语（塞尔维亚）', 'Serbian (Serbia)'),
    'sr-SP': ('塞尔维亚语（塞尔维亚）', 'Serbian (Serbia)'),  # 旧代码（SP 非标准，应为 RS）
    'sv-FI': ('瑞典语（芬兰）', 'Swedish (Finland)'),
    'sv-SE': ('瑞典语（瑞典）', 'Swedish (Sweden)'),
    'sw-KE': ('斯瓦希里语（肯尼亚）', 'Swahili (Kenya)'),
    'sw-TZ': ('斯瓦希里语（坦桑尼亚）', 'Swahili (Tanzania)'),
    'tg-TJ': ('塔吉克语（塔吉克斯坦）', 'Tajik (Tajikistan)'),
    'tk-TM': ('土库曼语（土库曼斯坦）', 'Turkmen (Turkmenistan)'),
    'tl-PH': ('菲律宾语（菲律宾）', 'Filipino (Philippines)'),
    'uk-UA': ('乌克兰语（乌克兰）', 'Ukrainian (Ukraine)'),
    'uz-UZ': ('乌兹别克语（乌兹别克斯坦）', 'Uzbek (Uzbekistan)'),
    
    # 其他地区变体
    'bo-CN': ('藏语（中国）', 'Tibetan (China)'),
    'br-FR': ('布列塔尼语（法国）', 'Breton (France)'),
    'ia-CN': ('国际语（中国）', 'Interlingua (China)'),  # 非标准组合
    'ug-CN': ('维吾尔语（中国）', 'Uighur (China)'),
    
    # =========================================================================
    # Android 特殊语言代码和别名
    # =========================================================================
    'fil': ('菲律宾语', 'Filipino'),  # 菲律宾语的另一种代码（pilipino）
    'gr': ('希腊语', 'Greek'),  # Android 旧代码/错误代码（ISO 639-1 正式代码为 el）
    'in': ('印尼语', 'Indonesian'),  # Android 旧代码（ISO 639-1 正式代码为 id）
    'in-ID': ('印尼语（印尼）', 'Indonesian (Indonesia)'),  # Android 旧代码
    'iw': ('希伯来语', 'Hebrew'),  # Android 旧代码（ISO 639-1 正式代码为 he）
    'iw-IL': ('希伯来语（以色列）', 'Hebrew (Israel)'),  # 旧代码
    'ji': ('意第绪语', 'Yiddish'),  # Android 旧代码（ISO 639-1 正式代码为 yi）
    'jp': ('日语', 'Japanese'),  # Android 旧代码/错误代码（ISO 639-1 正式代码为 ja）
    'jv-Latn': ('爪哇语（拉丁字母）', 'Javanese (Latin)'),  # 非标准组合
    'jw': ('爪哇语', 'Javanese'),  # Android 旧代码（ISO 639-1 正式代码为 jv）
    'kmr': ('北库尔德语', 'Northern Kurdish'),  # ISO 639-3 代码（库尔德语方言）
    'bqi-IR': ('北库尔德语（伊朗）', 'Northern Kurdish (Iran)'),  # ISO 639-3 代码
    'mai': ('迈蒂利语', 'Maithili'),  # ISO 639-3 代码（印度语言）
}

# Android 系统颜色资源 ID 查找颜色值的方法
# - 1、查资源名称 ：在 public-final.xml 中根据资源 ID 找到对应的资源名称
# - 2、查直接定义 ：在 colors.xml 或 colors_holo.xml 中搜索 <color name="资源名称"> ，找到则结束
# - 3、查状态列表 ：若步骤 2 未找到，去 color/资源名称.xml 中找颜色状态列表，取最后一个无状态限制的 <item> 的颜色值
# - 4、追踪引用 ：若颜色值是引用（如 @android:color/xxx ），回到步骤 2 递归查找直到得到最终颜色值
ANDROID_SYSTEM_COLORS = {
    0x01060000: ("#FFAAAAAA", "darker_gray"),           # 灰色
    0x01060001: ("#FFFFFFFF", "primary_text_dark"),     # 白色（深色主题主要文本）
    0x01060002: ("#FFFFFFFF", "primary_text_dark_nodisable"),  # 白色（深色主题主要文本，不禁用）
    0x01060003: ("#FF000000", "primary_text_light"),    # 黑色（浅色主题主要文本）
    0x01060004: ("#FF000000", "primary_text_light_nodisable"),  # 黑色（浅色主题主要文本，不禁用）
    0x01060005: ("#FFBEBEBE", "secondary_text_dark"),   # 浅灰色（深色主题次要文本）
    0x01060006: ("#FFBEBEBE", "secondary_text_dark_nodisable"),  # 浅灰色（深色主题次要文本，不禁用）
    0x01060007: ("#FF323232", "secondary_text_light"),  # 深灰色（浅色主题次要文本）
    0x01060008: ("#FFBEBEBE", "secondary_text_light_nodisable"),  # 浅灰色（浅色主题次要文本，不禁用）
    0x01060009: ("#FF808080", "tab_indicator_text"),    # 灰色（标签指示器文本）
    0x0106000A: ("#FF000000", "widget_edittext_dark"),  # 黑色（深色编辑框）
    0x0106000B: ("#FFFFFFFF", "white"),                 # 白色
    0x0106000C: ("#FF000000", "black"),                 # 黑色
    0x0106000D: ("#00000000", "transparent"),           # 透明
    0x0106000E: ("#FF000000", "background_dark"),       # 黑色（深色背景）
    0x0106000F: ("#FFFFFFFF", "background_light"),      # 白色（浅色背景）
    0x01060010: ("#FF808080", "tertiary_text_dark"),    # 灰色（深色主题第三级文本）
    0x01060011: ("#FF808080", "tertiary_text_light"),   # 灰色（浅色主题第三级文本）
    0x01060012: ("#FF33B5E5", "holo_blue_light"),       # Holo蓝色（亮）
    0x01060013: ("#FF0099CC", "holo_blue_dark"),        # Holo蓝色（暗）
    0x01060014: ("#FF99CC00", "holo_green_light"),      # Holo绿色（亮）
    0x01060015: ("#FF669900", "holo_green_dark"),       # Holo绿色（暗）
    0x01060016: ("#FFFF4444", "holo_red_light"),        # Holo红色（亮）
    0x01060017: ("#FFCC0000", "holo_red_dark"),         # Holo红色（暗）
    0x01060018: ("#FFFFBB33", "holo_orange_light"),     # Holo橙色（亮）
    0x01060019: ("#FFFF8800", "holo_orange_dark"),      # Holo橙色（暗）
    0x0106001A: ("#FFAA66CC", "holo_purple"),           # Holo紫色
    0x0106001B: ("#FF00DDFF", "holo_blue_bright"),      # Holo蓝色（亮）
}

ANDROID_SYSTEM_COLORS_BY_NAME = {name: (color, res_id) for res_id, (color, name) in ANDROID_SYSTEM_COLORS.items()}


# ============================================================================
# 配置文件相关
# ============================================================================
CONFIG_FILE_NAME = "apk_helper_config.json"
CONFIG_APPDATA_DIR = "apk_helper"
LOCAL_CONFIG_FILE = "LOCAL_CONFIG"  # 本地配置模式标志文件名，存在此文件表示配置保存在程序目录

DEFAULT_CONFIG = {
    "log_level": "INFO",
    "row_separator": "\\n",
    "col_separator": "\\t",
    "copy_custom_format": "{app_name}({package_name})-{version_name}",
    "copy_custom_no_popup": False,  # 复制自定义信息后是否不弹框提示
    "rename_format": "{app_name}_{version_name}",
    "rename_include_subdir": False,
    "rename_auto_number": False,  # 重复文件名自动添加编号
    "enable_win11_new_menu": False
}

config = {}


def is_local_config_mode():
    """
    检查是否使用本地配置模式（配置文件保存在程序目录）。
    
    通过检查程序目录下是否存在 LOCAL_CONFIG 标志文件来判断。
    
    Returns:
        bool: True 表示使用本地配置模式，False 表示使用 AppData 配置模式
    """
    if 'PRO_DIR' not in globals() or not PRO_DIR:
        return False
    
    local_config_flag = os.path.join(PRO_DIR, LOCAL_CONFIG_FILE)
    # 确保路径是绝对路径
    if not os.path.isabs(local_config_flag):
        return False
    
    return os.path.isfile(local_config_flag)


def get_config_file_path():
    """
    获取配置文件路径。
    
    如果程序目录下存在 LOCAL_CONFIG 文件，则返回程序目录下的配置文件路径。
    否则返回 AppData 目录下的配置文件路径。
    
    Returns:
        tuple: (配置文件路径, 是否为本地配置模式)
               本地配置模式为 True，AppData 配置模式为 False
               如果无法确定路径，返回 ("", False)
    """
    program_path = ""
    if 'PRO_DIR' in globals() and PRO_DIR:
        program_path = os.path.join(PRO_DIR, CONFIG_FILE_NAME)
    
    appdata_path = os.path.join(os.environ.get('APPDATA', ''), CONFIG_APPDATA_DIR, CONFIG_FILE_NAME)
    
    # 检查是否使用本地配置模式
    if is_local_config_mode():
        app_logger.debug(f"检测到本地配置模式，配置文件路径: {program_path}")
        return program_path, True
    
    # 使用 AppData 配置模式
    if appdata_path and os.path.exists(os.path.dirname(appdata_path)):
        return appdata_path, False
    
    if appdata_path:
        try:
            os.makedirs(os.path.dirname(appdata_path), exist_ok=True)
            return appdata_path, False
        except Exception as e:
            app_logger.warning(f"创建 AppData 配置目录失败: {e}")
    
    # 如果 AppData 不可用，回退到程序目录
    if program_path:
        app_logger.warning("AppData 目录不可用，回退到程序目录")
        return program_path, True
    
    # 如果都不可用，返回空路径
    app_logger.error("无法确定配置文件路径")
    return "", False


def escape_separator(sep):
    """
    将分隔符转换为可存储的转义字符串格式。
    
    Args:
        sep: 分隔符字符串
        
    Returns:
        str: 转义后的字符串
    """
    if not sep:
        return ""
    result = sep.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")
    return result


def unescape_separator(sep_str):
    """
    将转义字符串格式的分隔符还原为实际分隔符。
    
    Args:
        sep_str: 转义字符串格式的分隔符
        
    Returns:
        str: 实际分隔符
    """
    if not sep_str:
        return ""
    result = sep_str.replace("\\r", "\r").replace("\\t", "\t").replace("\\n", "\n").replace("\\\\", "\\")
    return result


def validate_config(config_data):
    """
    验证配置数据是否有效。
    
    Args:
        config_data: 配置字典
        
    Returns:
        tuple: (是否有效, 错误信息列表)
    """
    app_logger.debug("开始验证配置数据...")
    errors = []
    
    if not isinstance(config_data, dict):
        app_logger.warning("配置验证失败: 配置文件格式错误，不是有效的字典类型")
        return False, ["配置文件格式错误"]
    
    valid_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR"]
    if "log_level" in config_data:
        if not isinstance(config_data["log_level"], str):
            errors.append("日志级别必须是字符串")
            app_logger.debug(f"配置项验证 - log_level: 类型错误")
        elif config_data["log_level"] not in valid_log_levels:
            errors.append(f"日志级别无效: {config_data['log_level']}")
            app_logger.debug(f"配置项验证 - log_level: 值无效 ({config_data['log_level']})")
        else:
            app_logger.debug(f"配置项验证 - log_level: 有效 ({config_data['log_level']})")
    
    if "row_separator" in config_data:
        if not isinstance(config_data["row_separator"], str):
            errors.append("行间分隔符必须是字符串")
            app_logger.debug("配置项验证 - row_separator: 类型错误")
        else:
            sep = unescape_separator(config_data["row_separator"])
            if len(sep) > 10:
                errors.append("行间分隔符长度超过10个字符")
                app_logger.debug(f"配置项验证 - row_separator: 长度超限 ({len(sep)}字符)")
            else:
                for char in sep:
                    code = ord(char)
                    if code not in (9, 10, 13) and (code < 32 or code > 126):
                        errors.append("行间分隔符包含无效控制字符")
                        app_logger.debug(f"配置项验证 - row_separator: 包含无效控制字符 (ASCII {code})")
                        break
                else:
                    app_logger.debug(f"配置项验证 - row_separator: 有效")
    
    if "col_separator" in config_data:
        if not isinstance(config_data["col_separator"], str):
            errors.append("列间隔符必须是字符串")
            app_logger.debug("配置项验证 - col_separator: 类型错误")
        else:
            sep = unescape_separator(config_data["col_separator"])
            if len(sep) > 10:
                errors.append("列间隔符长度超过10个字符")
                app_logger.debug(f"配置项验证 - col_separator: 长度超限 ({len(sep)}字符)")
            else:
                for char in sep:
                    code = ord(char)
                    if code not in (9, 10, 13) and (code < 32 or code > 126):
                        errors.append("列间隔符包含无效控制字符")
                        app_logger.debug(f"配置项验证 - col_separator: 包含无效控制字符 (ASCII {code})")
                        break
                else:
                    app_logger.debug("配置项验证 - col_separator: 有效")
    
    if "copy_custom_format" in config_data:
        if not isinstance(config_data["copy_custom_format"], str):
            errors.append("复制自定义格式必须是字符串")
            app_logger.debug("配置项验证 - copy_custom_format: 类型错误")
        elif len(config_data["copy_custom_format"]) > 200:
            errors.append("复制自定义格式长度超过200个字符")
            app_logger.debug(f"配置项验证 - copy_custom_format: 长度超限 ({len(config_data['copy_custom_format'])}字符)")
        else:
            app_logger.debug(f"配置项验证 - copy_custom_format: 有效")
    
    if "copy_custom_no_popup" in config_data:
        if not isinstance(config_data["copy_custom_no_popup"], bool):
            errors.append("复制后不弹框提示选项必须是布尔值")
            app_logger.debug("配置项验证 - copy_custom_no_popup: 类型错误")
        else:
            app_logger.debug(f"配置项验证 - copy_custom_no_popup: 有效 ({config_data['copy_custom_no_popup']})")
    
    if "rename_format" in config_data:
        if not isinstance(config_data["rename_format"], str):
            errors.append("重命名格式必须是字符串")
            app_logger.debug("配置项验证 - rename_format: 类型错误")
        elif len(config_data["rename_format"]) > 200:
            errors.append("重命名格式长度超过200个字符")
            app_logger.debug(f"配置项验证 - rename_format: 长度超限 ({len(config_data['rename_format'])}字符)")
        else:
            app_logger.debug(f"配置项验证 - rename_format: 有效")
    
    if "rename_include_subdir" in config_data:
        if not isinstance(config_data["rename_include_subdir"], bool):
            errors.append("包含子目录选项必须是布尔值")
            app_logger.debug("配置项验证 - rename_include_subdir: 类型错误")
        else:
            app_logger.debug(f"配置项验证 - rename_include_subdir: 有效 ({config_data['rename_include_subdir']})")
    
    if "rename_auto_number" in config_data:
        if not isinstance(config_data["rename_auto_number"], bool):
            errors.append("重复文件名自动添加编号选项必须是布尔值")
            app_logger.debug("配置项验证 - rename_auto_number: 类型错误")
        else:
            app_logger.debug(f"配置项验证 - rename_auto_number: 有效 ({config_data['rename_auto_number']})")
    
    if "enable_win11_new_menu" in config_data:
        if not isinstance(config_data["enable_win11_new_menu"], bool):
            errors.append("Win11新版右键菜单选项必须是布尔值")
            app_logger.debug("配置项验证 - enable_win11_new_menu: 类型错误")
        else:
            app_logger.debug(f"配置项验证 - enable_win11_new_menu: 有效 ({config_data['enable_win11_new_menu']})")
    
    is_valid = len(errors) == 0
    if is_valid:
        app_logger.debug("配置验证结果: 通过")
    else:
        app_logger.warning(f"配置验证失败，共 {len(errors)} 个错误: {errors}")
    
    return is_valid, errors


def load_config():
    """
    加载配置文件。
    
    根据 LOCAL_CONFIG 标志文件决定从哪个目录加载配置文件。
    如果配置文件不存在，返回默认配置。
    
    Returns:
        dict: 配置字典
    """
    global config
    
    app_logger.debug("开始加载配置文件...")
    config = DEFAULT_CONFIG.copy()
    
    # 获取配置文件路径
    config_path, is_local = get_config_file_path()
    
    if not config_path:
        app_logger.warning("无法确定配置文件路径，使用默认配置")
        return config
    
    mode_str = "本地配置模式" if is_local else "AppData配置模式"
    app_logger.info(f"当前配置模式: {mode_str}")
    app_logger.debug(f"配置文件路径: {config_path}")
    
    loaded_count = 0
    if os.path.isfile(config_path):
        app_logger.debug(f"发现配置文件: {config_path}")
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            app_logger.debug(f"成功读取配置文件内容，共 {len(config_data)} 个配置项")
            
            valid, errors = validate_config(config_data)
            app_logger.debug(f"配置验证结果: {'通过' if valid else '失败'}")
            if valid:
                for key, value in config_data.items():
                    config[key] = value
                    app_logger.debug(f"加载配置项: {key} = {value}")
                    loaded_count += 1
            else:
                app_logger.warning(f"配置文件验证失败: {config_path}, 错误: {errors}")
        except json.JSONDecodeError as e:
            app_logger.warning(f"配置文件JSON解析失败: {config_path}, 错误: {e}")
        except Exception as e:
            app_logger.warning(f"读取配置文件失败: {config_path}, 错误: {e}")
    
    if loaded_count > 0:
        app_logger.info(f"配置文件加载完成，共加载 {loaded_count} 个配置项，来源: {config_path}")
    else:
        app_logger.debug("未找到有效配置文件，使用默认配置")
    
    return config


def save_config():
    """
    保存配置到文件。
    
    根据 LOCAL_CONFIG 标志文件决定保存到哪个目录。
    
    Returns:
        bool: 是否保存成功
    """
    global config
    
    app_logger.debug("开始保存配置...")
    
    config_data = {
        "log_level": CURRENT_LOG_LEVEL,
        "row_separator": escape_separator(CustomTableWidget.row_separator),
        "col_separator": escape_separator(CustomTableWidget.col_separator),
        "copy_custom_format": config.get("copy_custom_format", DEFAULT_CONFIG["copy_custom_format"]),
        "copy_custom_no_popup": config.get("copy_custom_no_popup", DEFAULT_CONFIG["copy_custom_no_popup"]),
        "rename_format": config.get("rename_format", DEFAULT_CONFIG["rename_format"]),
        "rename_include_subdir": config.get("rename_include_subdir", DEFAULT_CONFIG["rename_include_subdir"]),
        "rename_auto_number": config.get("rename_auto_number", DEFAULT_CONFIG["rename_auto_number"]),
        "enable_win11_new_menu": config.get("enable_win11_new_menu", DEFAULT_CONFIG["enable_win11_new_menu"])
    }
    
    app_logger.debug(f"准备保存的配置数据: {config_data}")
    
    valid, errors = validate_config(config_data)
    app_logger.debug(f"配置数据验证结果: {'通过' if valid else '失败'}")
    if not valid:
        app_logger.warning(f"配置数据验证失败，无法保存: {errors}")
        return False
    
    # 获取配置文件路径
    config_path, is_local = get_config_file_path()
    
    if not config_path:
        app_logger.warning("无法确定配置文件路径，保存失败")
        return False
    
    mode_str = "本地配置模式" if is_local else "AppData配置模式"
    app_logger.debug(f"当前配置模式: {mode_str}, 配置保存路径: {config_path}")
    
    saved = False
    
    # 确保目录存在
    config_dir = os.path.dirname(config_path)
    if config_dir and not os.path.exists(config_dir):
        try:
            os.makedirs(config_dir, exist_ok=True)
            app_logger.debug(f"创建配置目录: {config_dir}")
        except Exception as e:
            app_logger.warning(f"创建配置目录失败: {e}")
            return False
    
    # 保存配置文件
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)
        config = config_data
        saved = True
        app_logger.info(f"配置保存成功，保存路径: {config_path}")
    except Exception as e:
        app_logger.warning(f"保存配置文件失败: {config_path}, 错误: {e}")
    
    return saved


# ============================================================================
# NativeAXMLParser - 原生Android二进制XML解析器
# ============================================================================

class NativeAXMLParser:
    """原生Android二进制XML解析器"""
    
    def __init__(self, data):
        self.data = data
        self.namespaces = {}
        self._ns_prefix_map = {}
        self._string_count = 0
        self._strings_data_start = 0
        self._is_utf8 = False
        self._string_offsets = []
        self.resource_ids = []
        
    def _read_uint16(self, offset):
        if offset + 2 > len(self.data):
            raise ValueError(f"读取uint16越界: offset={offset}, data_len={len(self.data)}")
        return struct.unpack('<H', self.data[offset:offset+2])[0]
    
    def _read_uint32(self, offset):
        if offset + 4 > len(self.data):
            raise ValueError(f"读取uint32越界: offset={offset}, data_len={len(self.data)}")
        return struct.unpack('<I', self.data[offset:offset+4])[0]
    
    def _get_string(self, index):
        if index >= self._string_count or index < 0:
            return ''
        
        off = self._string_offsets[index]
        pos = self._strings_data_start + off
        
        if self._is_utf8:
            first = self.data[pos]
            if (first & 0x80) == 0:
                pos += 1
            else:
                pos += 2
            
            first = self.data[pos]
            if (first & 0x80) == 0:
                byte_len = first
                pos += 1
            else:
                second = self.data[pos+1]
                byte_len = ((first & 0x7F) << 8) | second
                pos += 2
            
            str_bytes = self.data[pos:pos+byte_len]
            try:
                return str_bytes.decode('utf-8')
            except:
                return str_bytes.decode('utf-8', errors='replace')
        else:
            str_len = self._read_uint16(pos)
            str_bytes = self.data[pos+2:pos+2+str_len*2]
            try:
                return str_bytes.decode('utf-16-le')
            except:
                return str_bytes.decode('utf-16-le', errors='replace')
    
    def parse(self):
        """
        解析Android二进制XML文件
        
        返回:
            dict: 包含解析结果的字典，结构为：
                {
                    'elements': [元素列表],
                    'namespaces': [命名空间列表],
                    'ns_nodes': [命名空间节点列表]
                }
        """
        result = {'elements': [], 'namespaces': []}
        
        if len(self.data) < 8:
            return result
        
        chunk_type = self._read_uint16(0)
        header_size = self._read_uint16(2)
        
        if chunk_type != RES_XML_TYPE:
            return result
        
        sp_offset = header_size
        sp_type = self._read_uint16(sp_offset)
        sp_header_size = self._read_uint16(sp_offset+2)
        sp_size = self._read_uint32(sp_offset+4)
        
        if sp_type != RES_STRING_POOL_TYPE:
            raise ValueError(f"字符串池类型错误: 0x{sp_type:04X}")
        
        self._string_count = self._read_uint32(sp_offset+8)
        flags = self._read_uint32(sp_offset+16)
        strings_start = self._read_uint32(sp_offset+20)
        
        self._is_utf8 = bool(flags & UTF8_FLAG)
        self._strings_data_start = sp_offset + strings_start
        
        string_offsets_offset = sp_offset + sp_header_size
        self._string_offsets = []
        for i in range(self._string_count):
            self._string_offsets.append(self._read_uint32(string_offsets_offset + i*4))
        
        offset = sp_offset + sp_size
        
        if offset < len(self.data):
            res_map_type = self._read_uint16(offset)
            if res_map_type == RES_XML_RESOURCE_MAP_TYPE:
                res_map_size = self._read_uint32(offset+4)
                res_count = (res_map_size - 8) // 4
                self.resource_ids = []
                for i in range(res_count):
                    self.resource_ids.append(self._read_uint32(offset + 8 + i*4))
                offset += res_map_size
        
        element_stack = []
        ns_stack = []
        all_namespaces = []
        ns_nodes = []
        
        while offset < len(self.data) - 8:
            node_type = self._read_uint16(offset)
            node_header_size = self._read_uint16(offset+2)
            node_size = self._read_uint32(offset+4)
            
            if node_size == 0:
                break
            
            if node_type == RES_XML_START_NAMESPACE_TYPE:
                line_number = self._read_uint32(offset+8)
                prefix = self._read_uint32(offset+16)
                uri = self._read_uint32(offset+20)
                prefix_str = self._get_string(prefix)
                uri_str = self._get_string(uri)
                ns_info = {'prefix': prefix_str, 'uri': uri_str, 'line': line_number}
                self.namespaces[prefix] = ns_info
                self._ns_prefix_map[uri_str] = prefix_str
                ns_stack.append(ns_info)
                all_namespaces.append(ns_info)
                ns_nodes.append({'type': 'start', 'ns': ns_info, 'depth': len(element_stack)})
            
            elif node_type == RES_XML_END_NAMESPACE_TYPE:
                if ns_stack:
                    ns_info = ns_stack.pop()
                    ns_nodes.append({'type': 'end', 'ns': ns_info, 'depth': len(element_stack)})
            
            elif node_type == RES_XML_START_ELEMENT_TYPE:
                line_number = self._read_uint32(offset+8)
                ns = self._read_uint32(offset+16)
                name = self._read_uint32(offset+20)
                attr_start = self._read_uint16(offset+24)
                attr_size = self._read_uint16(offset+26)
                attr_count = self._read_uint16(offset+28)
                
                name_str = self._get_string(name)
                
                element = {
                    'name': name_str, 
                    'attrs': [], 
                    'children': [], 
                    'line': line_number
                }
                
                for i in range(attr_count):
                    attr_offset = offset + node_header_size + attr_start + i * attr_size
                    attr_ns = self._read_uint32(attr_offset)
                    attr_name = self._read_uint32(attr_offset+4)
                    value_string_idx = self._read_uint32(attr_offset+8)
                    value_type = self.data[attr_offset+15]
                    value_data = self._read_uint32(attr_offset+16)
                    
                    attr_name_str = self._get_string(attr_name)
                    attr_ns_str = self._get_string(attr_ns) if attr_ns != 0xFFFFFFFF else ''
                    attr_ns_prefix = self._ns_prefix_map.get(attr_ns_str, '')
                    
                    attr_res_id = 0
                    if attr_name < len(self.resource_ids):
                        attr_res_id = self.resource_ids[attr_name]
                    
                    value = self._parse_value(value_type, value_data)
                    raw_value = self._get_string(value_string_idx) if value_string_idx != 0xFFFFFFFF else ''
                    
                    element['attrs'].append({
                        'name': attr_name_str,
                        'ns': attr_ns_str,
                        'ns_prefix': attr_ns_prefix,
                        'value': value,
                        'value_type': value_type,
                        'value_data': value_data,
                        'attr_res_id': attr_res_id,
                        'raw_value': raw_value
                    })
                
                if element_stack:
                    element_stack[-1]['children'].append(element)
                else:
                    result['elements'].append(element)
                element_stack.append(element)
            
            elif node_type == RES_XML_END_ELEMENT_TYPE:
                if element_stack:
                    element_stack.pop()
            
            elif node_type == RES_XML_CDATA_TYPE:
                line_number = self._read_uint32(offset+8)
                data_index = self._read_uint32(offset+16)
                text = self._get_string(data_index)
                
                text_node = {
                    'type': 'text',
                    'text': text,
                    'line': line_number
                }
                
                if element_stack:
                    element_stack[-1]['children'].append(text_node)
            
            offset += node_size
        
        result['namespaces'] = list(self.namespaces.values())
        result['ns_nodes'] = ns_nodes
        return result
    
    def _parse_value(self, value_type, value_data):
        if value_type == TYPE_NULL:
            return None
        elif value_type == TYPE_REFERENCE:
            if value_data == 0:
                return "@null"
            return f"@0x{value_data:08x}"
        elif value_type == TYPE_ATTRIBUTE:
            return f"?0x{value_data:08x}"
        elif value_type == TYPE_STRING:
            return self._get_string(value_data)
        elif value_type == TYPE_FLOAT:
            return struct.unpack('<f', struct.pack('<I', value_data))[0]
        elif value_type == TYPE_DIMENSION:
            unit = value_data & 0xF
            radix = (value_data >> 4) & 0x3
            mantissa = (value_data >> 8) & 0xFFFFFF
            
            if radix == 0:
                float_val = float(mantissa)
            elif radix == 1:
                float_val = mantissa * (1.0 / 128)
            elif radix == 2:
                float_val = mantissa * (1.0 / 32768)
            elif radix == 3:
                float_val = mantissa * (1.0 / 8388608)
            else:
                float_val = 0.0
            
            units = {0: 'px', 1: 'dp', 2: 'sp', 3: 'pt', 4: 'in', 5: 'mm'}
            return f"{float_val:.6f}{units.get(unit, '')}"
        elif value_type == TYPE_FRACTION:
            type_val = value_data & 0xF
            radix = (value_data >> 4) & 0x3
            mantissa = (value_data >> 8) & 0xFFFFFF
            
            if radix == 0:
                float_val = float(mantissa)
            elif radix == 1:
                float_val = mantissa * (1.0 / 128)
            elif radix == 2:
                float_val = mantissa * (1.0 / 32768)
            elif radix == 3:
                float_val = mantissa * (1.0 / 8388608)
            else:
                float_val = 0.0
            
            return f"{float_val:.6f}%{'p' if type_val == 1 else ''}"
        elif value_type == TYPE_INT_DEC:
            if value_data & 0x80000000:
                return str(value_data - 0x100000000)
            return str(value_data)
        elif value_type == TYPE_INT_HEX:
            return f"0x{value_data:08x}"
        elif value_type == TYPE_INT_BOOLEAN:
            return "true" if value_data else "false"
        elif value_type in (TYPE_INT_COLOR_ARGB8, TYPE_INT_COLOR_RGB8, TYPE_INT_COLOR_ARGB4, TYPE_INT_COLOR_RGB4):
            return f"#{value_data:08x}"
        else:
            return f"0x{value_data:08x}"


# ============================================================================
# APKParser - APK解析器核心类
# ============================================================================

class APKParser:
    """
    APK解析器类，使用aapt2工具解析APK文件
    带缓存机制避免重复执行aapt2命令
    """
    
    def __init__(self, apk_path):
        """
        初始化APK解析器
        
        参数:
            apk_path: APK文件路径
        """
        global BASE_DIR, PRO_DIR
        self.apk_path = apk_path
        self.AAPT2_PATH = os.path.join(BASE_DIR, 'aapt2.exe')
        self._aapt2_call_count = 0
        self._lock = threading.Lock()
        
        self._badging_parsed = None
        self._xmltree_raw = {}
        self._manifest_parsed = None
        self._resources_raw = None
        self._resources_parsed = {}
        self._zip_file = None
        self._files_list = None
        self._color_cache = {}
        self._color_resource_cache = {}
        
        self._init_basic_info()
    
    def _init_basic_info(self):
        """初始化时获取基本信息"""
        try:
            self._ensure_badging()
            app_logger.debug(f"初始化完成，获取基本信息")
        except Exception as e:
            app_logger.error(f"初始化失败: {e}")
    
    def _log_command(self, cmd_type, cmd_args):
        """记录执行的命令"""
        self._aapt2_call_count += 1
        app_logger.debug(f"[aapt2 #{self._aapt2_call_count}] {cmd_type}")
    
    def run_aapt2(self, args, apk_path, timeout=60):
        """
        运行aapt2命令并返回输出
        
        参数:
            args: aapt2命令参数列表
            apk_path: APK文件路径
            timeout: 超时时间（秒）
        
        返回:
            tuple: (stdout, stderr, returncode)
        """
        # 构建命令行字符串，用双引号包裹路径以保护特殊字符
        args_str = ' '.join(args)
        cmd_str = f'"{self.AAPT2_PATH}" {args_str} "{apk_path}"'
        try:
            result = subprocess.run(
                cmd_str,
                shell=True,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                timeout=timeout
            )
            return result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            return "", "命令超时", -1
        except Exception as e:
            return "", str(e), -1

    def _run_aapt2(self, args, timeout=60):
        """运行aapt2命令"""
        self._log_command(' '.join(args), args)
        return self.run_aapt2(args, self.apk_path, timeout)

    def native_axml_to_xmltree(self, data):
        """将AXML数据转换为xmltree格式输出（兼容aapt2格式）
        
        缩进规则：
        1. N和下一级缩进差2，不管下一级是N还是E还是A
        2. E和自己的属性A缩进差2，E和下一级E缩进差4
        3. 如果E内部有N，N的缩进取决于E是否有属性：
           - E没有属性：N缩进 = E缩进 + 4
           - E有属性：N缩进 = 最后一个A的缩进 + 2
        """
        parser = NativeAXMLParser(data)
        result = parser.parse()
        
        lines = []
        ns_nodes = result.get('ns_nodes', [])
        ns_index = [0]
        indent_level = [0]
        
        def get_indent():
            return '  ' * indent_level[0]
        
        def format_multiline_string(s, base_indent):
            """格式化多行字符串，在换行后添加缩进"""
            if '\n' not in s:
                return s
            lines = s.split('\n')
            result = [lines[0]]
            for line in lines[1:]:
                result.append(base_indent + line)
            return '\n'.join(result)
        
        def output_namespaces(element_line):
            """输出元素之前的命名空间，返回命名空间数量"""
            count = 0
            while ns_index[0] < len(ns_nodes):
                node = ns_nodes[ns_index[0]]
                if node['type'] == 'start':
                    ns_info = node['ns']
                    ns_line = ns_info.get('line', 0)
                    if ns_line <= element_line:
                        lines.append(f"{get_indent()}N: {ns_info['prefix']}={ns_info['uri']} (line={ns_line})")
                        indent_level[0] += 1
                        ns_index[0] += 1
                        count += 1
                        continue
                else:
                    ns_index[0] += 1
                    continue
                break
            return count
        
        def build_element(element):
            """递归构建元素及其子元素
            
            参数:
                element: 元素对象
            """
            line_num = element.get('line', 0)
            
            ns_count = output_namespaces(line_num)
            
            lines.append(f"{get_indent()}E: {element['name']} (line={line_num})")
            indent_level[0] += 1
            
            for attr in element['attrs']:
                name = attr['name']
                ns_uri = attr.get('ns', '')
                attr_res_id = attr.get('attr_res_id', 0)
                value = attr['value']
                value_type = attr['value_type']
                raw_value = attr.get('raw_value', '')
                
                if ns_uri:
                    attr_name = f"{ns_uri}:{name}"
                else:
                    attr_name = name
                
                if attr_res_id:
                    attr_name_with_id = f"{attr_name}(0x{attr_res_id:08x})"
                else:
                    attr_name_with_id = attr_name
                
                if value_type == TYPE_INT_DEC:
                    attr_line = f"{get_indent()}A: {attr_name_with_id}={value}"
                elif value_type == TYPE_INT_BOOLEAN:
                    attr_line = f"{get_indent()}A: {attr_name_with_id}={value}"
                elif value_type == TYPE_FLOAT:
                    float_val = float(value) if value else 0.0
                    if float_val == int(float_val):
                        attr_line = f"{get_indent()}A: {attr_name_with_id}={int(float_val)}"
                    else:
                        attr_line = f"{get_indent()}A: {attr_name_with_id}={float_val:g}"
                elif value_type == TYPE_INT_COLOR_ARGB8:
                    attr_line = f"{get_indent()}A: {attr_name_with_id}={value}"
                elif value_type == TYPE_INT_COLOR_RGB8:
                    attr_line = f"{get_indent()}A: {attr_name_with_id}={value}"
                elif value_type == TYPE_STRING:
                    if value:
                        formatted_value = format_multiline_string(value, get_indent())
                        attr_line = f"{get_indent()}A: {attr_name_with_id}=\"{formatted_value}\""
                    else:
                        attr_line = f"{get_indent()}A: {attr_name_with_id}=\"\""
                elif value_type == TYPE_REFERENCE:
                    attr_line = f"{get_indent()}A: {attr_name_with_id}={value}"
                elif value_type == TYPE_DIMENSION:
                    attr_line = f"{get_indent()}A: {attr_name_with_id}={value}"
                else:
                    attr_line = f"{get_indent()}A: {attr_name_with_id}={value}"
                
                if raw_value:
                    attr_line += f" (Raw: \"{raw_value}\")"
                
                lines.append(attr_line)
            
            indent_level[0] += 1
            
            for child in element.get('children', []):
                if child.get('type') == 'text':
                    text = child.get('text', '')
                    line_num = child.get('line', 0)
                    formatted_text = format_multiline_string(text, get_indent())
                    lines.append(f"{get_indent()}T: '{formatted_text}'")
                else:
                    build_element(child)
            
            indent_level[0] -= 1
            indent_level[0] -= 1
            indent_level[0] -= ns_count
        
        for element in result['elements']:
            build_element(element)
        
        return '\n'.join(lines)

    def _run_aapt2_xmltree(self, xml_path):
        """
        运行aapt2 dump xmltree命令或使用原生解析器
        
        参数:
            xml_path: XML文件在APK中的路径
        
        返回:
            tuple: (xml_content, error_message)
                - xml_content: 解析成功时返回XML内容字符串，失败时返回空字符串
                - error_message: 错误信息字符串，无错误时返回空字符串
        
        注意:
            - 原生解析器成功时返回 ("内容", "")
            - aapt2解析时可能返回 ("内容", "警告信息")，此时内容仍然有效
            - 解析失败时返回 ("", "错误信息")
        """
        if USE_NATIVE_AXML_PARSER:
            # 使用内置原生解析器
            try:
                zf = self.get_zip_file()
                data = zf.read(xml_path)
                return self.native_axml_to_xmltree(data), ""
            except Exception as e:
                return "", f"AXML解析失败: {e}"
        else:
            # 使用aapt2
            self._log_command(f'dump xmltree --file {xml_path}', ['dump', 'xmltree', '--file', xml_path])
            stdout_str = ""
            stderr_str = ""
            try:
                # 构建命令行字符串，用双引号包裹路径以保护特殊字符
                cmd_str = f'"{self.AAPT2_PATH}" dump xmltree --file "{xml_path}" "{self.apk_path}"'
                result = subprocess.run(
                    cmd_str,
                    shell=True,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='ignore',
                    timeout=30
                )
                stdout_str = result.stdout
                if result.stderr:
                    stderr_str = result.stderr
                return stdout_str, stderr_str
            except Exception as e:
                return stdout_str, f"使用aapt2解析AXML失败: {e}"
    
    def get_zip_file(self):
        """获取ZipFile实例（懒加载）"""
        if self._zip_file is None:
            self._zip_file = zipfile.ZipFile(self.apk_path, 'r')
        return self._zip_file
    
    def get_files_list(self):
        """获取APK中的文件列表"""
        if self._files_list is None:
            self._files_list = self.get_zip_file().namelist()
        return self._files_list
    
    def close(self):
        """关闭所有打开的资源，释放大对象"""
        if self._zip_file is not None:
            self._zip_file.close()
            self._zip_file = None
        self._files_list = None
        self._resources_raw = None
        self._resources_parsed.clear()
        self._xmltree_raw.clear()
        self._badging_parsed = None
        self._manifest_parsed = None
        self._color_cache.clear()
        self._color_resource_cache.clear()
    
    def __enter__(self):
        """支持with语句"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """支持with语句，自动关闭资源"""
        self.close()
    
    def _ensure_badging(self):
        """确保badging信息已获取（线程安全）"""
        if self._badging_parsed is not None:
            return self._badging_parsed
        
        with self._lock:
            if self._badging_parsed is not None:
                return self._badging_parsed
            
            stdout, stderr, returncode = self._run_aapt2(['dump', 'badging'])
            
            info = {
                'package_name': '',
                'version_name': '',
                'version_code': '',
                'sdk_version': '',
                'target_sdk_version': '',
                'compile_sdk_version': '',
                'platform_build_version_code': '',
                'application_label': '',
                'application_label_zh': '',
                'application_icon': [],
                'permissions': [],
                'locales': [],
                'densities': [],
                'native_code': [],
                'launchable_activity': '',
                'supports_screens': [],
                'features': []
            }
            
            zh_labels = {}
            
            if len(stdout) < 20:
                app_logger.error(f"获取badging信息失败：{stderr}")
                raise ValueError(f"获取badging信息失败：{stderr}")

            for line in stdout.split('\n'):
                line = line.strip()
                
                if line.startswith('package:'):
                    match = re.search(r"name='([^']+)'", line)
                    if match:
                        info['package_name'] = match.group(1)
                    match = re.search(r"versionName='([^']+)'", line)
                    if match:
                        info['version_name'] = match.group(1)
                    match = re.search(r"versionCode='([^']+)'", line)
                    if match:
                        info['version_code'] = match.group(1)
                    match = re.search(r"compileSdkVersion='([^']+)'", line)
                    if match:
                        info['compile_sdk_version'] = match.group(1)
                    match = re.search(r"platformBuildVersionCode='([^']+)'", line)
                    if match:
                        info['platform_build_version_code'] = match.group(1)
                
                elif line.startswith('sdkVersion:'):
                    info['sdk_version'] = line.split("'")[1]
                
                elif line.startswith('targetSdkVersion:'):
                    info['target_sdk_version'] = line.split("'")[1]
                
                elif line.startswith('application:'):
                    match = re.search(r"label='([^']*)'", line)
                    if match:
                        info['application_label'] = match.group(1)
                
                elif line.startswith('application-label:'):
                    match = re.search(r"'([^']*)'", line)
                    if match:
                        info['application_label'] = match.group(1)
                
                elif line.startswith('application-label-zh-CN:'):
                    match = re.search(r"'([^']*)'", line)
                    if match:
                        zh_labels['zh-CN'] = match.group(1)
                
                elif line.startswith('application-label-zh-HK:'):
                    match = re.search(r"'([^']*)'", line)
                    if match:
                        zh_labels['zh-HK'] = match.group(1)
                
                elif line.startswith('application-label-zh-TW:'):
                    match = re.search(r"'([^']*)'", line)
                    if match:
                        zh_labels['zh-TW'] = match.group(1)
                
                elif line.startswith('application-label-zh:'):
                    match = re.search(r"'([^']*)'", line)
                    if match:
                        zh_labels['zh'] = match.group(1)
                
                elif line.startswith('application-icon-'):
                    match = re.search(r"application-icon-(\d+):'([^']+)'", line)
                    if match:
                        density = match.group(1)
                        icon_path = match.group(2)
                        info['application_icon'].append({
                            'density': int(density),
                            'path': icon_path
                        })
                
                elif line.startswith('uses-permission:'):
                    match = re.search(r"name='([^']+)'", line)
                    if match:
                        info['permissions'].append(match.group(1))
                
                elif line.startswith('launchable-activity:'):
                    match = re.search(r"name='([^']+)'", line)
                    if match:
                        info['launchable_activity'] = match.group(1)
                
                elif line.startswith('locales:'):
                    # 解析语言列表，格式: locales: 'en-US' 'zh-CN' 'ja' ...
                    matches = re.findall(r"'([^']+)'", line)
                    if matches:
                        info['locales'] = matches
                        app_logger.debug(f"从badging获取到 {len(matches)} 个语言: {matches}")
                
                elif line.startswith('native-code:') or line.startswith('alt-native-code:'):
                    matches = re.findall(r"'([^']+)'", line)
                    if matches:
                        info['native_code'].extend(matches)
            
            zh_priority = ['zh-CN', 'zh', 'zh-HK', 'zh-TW']
            for locale in zh_priority:
                if locale in zh_labels and zh_labels[locale]:
                    info['application_label_zh'] = zh_labels[locale]
                    break
            
            if not info['compile_sdk_version']:
                platform_build = info.get('platform_build_version_code')
                if platform_build:
                    info['compile_sdk_version'] = platform_build
            
            self._badging_parsed = info
        
        return self._badging_parsed
    
    def _parse_manifest_xmltree(self, xml_content):
        """
        解析aapt2 dump xmltree输出的AndroidManifest.xml内容
        
        参数:
            xml_content: aapt2 dump xmltree的输出字符串
        
        返回:
            解析后的结构化数据
        """
        result = {
            'application': {},
            'application_icon': None,
            'activities': [],
            'activity_aliases': [],
            'launch_activities': [],
            'launch_aliases': []
        }
        
        lines = xml_content.split('\n')
        
        element_stack = []
        current_element = None
        
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            
            indent = len(line) - len(line.lstrip())
            
            while element_stack and element_stack[-1]['indent'] >= indent:
                element_stack.pop()
            
            if stripped.startswith('E: '):
                element_name = stripped[3:].split()[0] if ' ' in stripped[3:] else stripped[3:]
                element = {
                    'name': element_name,
                    'attrs': {},
                    'children': [],
                    'indent': indent,
                }
                
                if element_stack:
                    element_stack[-1]['children'].append(element)
                
                element_stack.append(element)
                current_element = element
                
                if element_name == 'application':
                    result['application'] = element
                elif element_name == 'activity':
                    result['activities'].append(element)
                elif element_name == 'activity-alias':
                    result['activity_aliases'].append(element)
            
            elif stripped.startswith('A: '):
                if current_element is None:
                    continue
                
                attr_line = stripped[3:]
                
                attr_name = None
                attr_value = None
                
                if 'android:icon' in attr_line or '(0x01010002)=' in attr_line:
                    if '@0x' in attr_line:
                        idx = attr_line.find('@0x')
                        attr_value = attr_line[idx+1:idx+11].lower()
                        attr_name = 'icon'
                elif 'android:name' in attr_line or '(0x01010003)=' in attr_line:
                    idx = attr_line.find(')="')
                    if idx > 0:
                        rest = attr_line[idx+3:]
                        end_idx = rest.find('"')
                        if end_idx > 0:
                            attr_value = rest[:end_idx]
                        attr_name = 'name'
                elif 'android:targetActivity' in attr_line or '(0x01010202)=' in attr_line:
                    idx = attr_line.find(')="')
                    if idx > 0:
                        rest = attr_line[idx+3:]
                        end_idx = rest.find('"')
                        if end_idx > 0:
                            attr_value = rest[:end_idx]
                        attr_name = 'targetActivity'
                elif 'android:label' in attr_line or '(0x01010001)=' in attr_line:
                    idx = attr_line.find(')="')
                    if idx > 0:
                        rest = attr_line[idx+3:]
                        end_idx = rest.find('"')
                        if end_idx > 0:
                            attr_value = rest[:end_idx]
                        attr_name = 'label'
                elif 'android:enabled' in attr_line or '(0x0101000e)=' in attr_line:
                    if '=false' in attr_line.lower():
                        # 格式: A: android:enabled(0x0101000e)=false
                        attr_value = False
                        attr_name = 'enabled'
                    elif '=true' in attr_line.lower():
                        # 格式: A: android:enabled(0x0101000e)=true
                        attr_value = True
                        attr_name = 'enabled'
                    elif '="true"' in attr_line.lower() or '="false"' in attr_line.lower():
                        attr_value = 'true' in attr_line.lower()
                        attr_name = 'enabled'
                    elif '=@0x' in attr_line.lower():
                        # 格式: A: android:enabled(0x0101000e)=@0x7f134a00
                        # 资源引用，需要后续从资源中解析布尔值
                        idx = attr_line.find('=@0x')
                        if idx > 0:
                            attr_value = attr_line[idx+1:idx+11].lower()
                            attr_name = 'enabled_ref'
                    elif '=0x' in attr_line:
                        # 格式: A: android:enabled(0x0101000e)=(type 0x12)0xffffffff
                        # 0xffffffff = true, 0x0 = false
                        idx = attr_line.find(')0x')
                        if idx > 0:
                            val = attr_line[idx+3:idx+11]
                            attr_value = val != '00000000'
                            attr_name = 'enabled'
                elif 'android:order' in attr_line or '(0x010101ea)=' in attr_line:
                    # 格式: A: http://schemas.android.com/apk/res/android:order(0x010101ea)=10
                    # order 用于应用内多个 intent-filter 的排序，数值越高优先级越高
                    # 参考 Android 源码: "The value is a single integer, with higher numbers considered to be better."
                    # 默认值: 0 (If not specified, the default order is 0.)
                    # app_logger.debug(f"发现 android:order 属性: {attr_line}")
                    idx = attr_line.find(')=')
                    if idx > 0:
                        try:
                            rest = attr_line[idx+2:].strip()
                            # 尝试解析十进制数值
                            attr_value = int(rest)
                            attr_name = 'order'
                        except:
                            app_logger.debug(f"解析 android:order 属性失败: {attr_line}")
                
                if attr_name and attr_value is not None:
                    current_element['attrs'][attr_name] = attr_value
                    
                    if current_element['name'] == 'application' and attr_name == 'icon':
                        result['application_icon'] = attr_value
                    
                    if current_element['name'] == 'action' and attr_value == 'android.intent.action.MAIN':
                        for elem in element_stack:
                            if elem['name'] == 'intent-filter':
                                elem['_main_action'] = True
                                break
                    
                    if current_element['name'] == 'category' and attr_value == 'android.intent.category.LAUNCHER':
                        for elem in element_stack:
                            if elem['name'] == 'intent-filter':
                                elem['_launcher_category'] = True
                                break
                    
                    # 记录 intent-filter 的图标（仅限 activity/activity-alias 下的 intent-filter）
                    # 后续处理时只取启动器 intent-filter 的图标
                    if attr_name == 'icon':
                        for elem in element_stack:
                            if elem['name'] == 'intent-filter':
                                # 检查这个 intent-filter 是否属于 activity 或 activity-alias
                                for parent in element_stack:
                                    if parent['name'] in ['activity', 'activity-alias']:
                                        elem['_filter_icon'] = attr_value
                                        break
                                break
        
        # 获取 application 的 enabled 状态（默认为 true）
        app_enabled = self._resolve_enabled_value(result.get('application', {}).get('attrs', {}), True)
        
        # 如果 application.enabled = false，所有组件都禁用
        if not app_enabled:
            return result
        
        # 构建 activity 名称到 enabled 状态的映射
        activity_enabled_map = {}
        for activity in result['activities']:
            activity_name = activity['attrs'].get('name', '')
            activity_enabled = self._resolve_enabled_value(activity['attrs'], True)
            activity_enabled_map[activity_name] = activity_enabled
        
        declaration_index = 0  # 声明顺序索引
        
        for activity in result['activities']:
            activity_name = activity['attrs'].get('name', '')
            # 使用已构建的 activity_enabled_map，避免重复解析
            enabled = activity_enabled_map.get(activity_name, True)
            
            # app_logger.debug(f"解析 activity: name='{activity_name}', enabled={enabled}")
            
            if not enabled:
                continue
            
            # 查找启动器 intent-filter（同时有 MAIN action 和 LAUNCHER category）
            # 只从启动器 intent-filter 获取图标和 order
            filter_icon = None
            order = None  # 未设置时为 None
            has_launcher_filter = False
            
            for child in activity.get('children', []):
                if child.get('name') == 'intent-filter':
                    # 检查是否为启动器 intent-filter
                    if child.get('_main_action') and child.get('_launcher_category'):
                        has_launcher_filter = True
                        # 只从启动器 intent-filter 获取图标
                        if child.get('_filter_icon'):
                            filter_icon = child['_filter_icon']
                        # 获取 order（数值越高优先级越高）
                        child_order = child.get('attrs', {}).get('order')
                        if child_order is not None:
                            if order is None:
                                order = int(child_order)
                            else:
                                order = max(order, int(child_order))
            
            if has_launcher_filter:
                # app_logger.debug(f"  -> 启动器入口: activity='{activity_name}', enabled={enabled}, order={order}")
                result['launch_activities'].append({
                    'name': activity_name,
                    'icon': activity['attrs'].get('icon', None),
                    'filter_icon': filter_icon,
                    'label': activity['attrs'].get('label', None),
                    'enabled': enabled,
                    'order': order,
                    '_index': declaration_index  # 记录声明顺序
                })
                declaration_index += 1
        
        for alias in result['activity_aliases']:
            alias_name = alias['attrs'].get('name', '')
            target_activity = alias['attrs'].get('targetActivity', '')
            alias_enabled = self._resolve_enabled_value(alias['attrs'], True)
            
            # app_logger.debug(f"解析 activity-alias: name='{alias_name}', targetActivity='{target_activity}', enabled={alias_enabled}")
            
            if not alias_enabled:
                continue
            
            # 检查 targetActivity 是否 enabled
            # 注意：targetActivity 是必须属性，必须存在于当前 APK 中且启用
            if not target_activity:
                # app_logger.debug(f"  -> 跳过: activity-alias 缺少 targetActivity 属性")
                continue
            
            if target_activity not in activity_enabled_map:
                # app_logger.debug(f"  -> 跳过: targetActivity '{target_activity}' 不存在于当前APK")
                continue
            
            if not activity_enabled_map[target_activity]:
                # app_logger.debug(f"  -> 跳过: targetActivity '{target_activity}' 未启用")
                continue
            
            # 查找启动器 intent-filter（同时有 MAIN action 和 LAUNCHER category）
            # 只从启动器 intent-filter 获取图标和 order
            filter_icon = None
            order = None  # 未设置时为 None
            has_launcher_filter = False
            
            for child in alias.get('children', []):
                if child.get('name') == 'intent-filter':
                    # 检查是否为启动器 intent-filter
                    if child.get('_main_action') and child.get('_launcher_category'):
                        has_launcher_filter = True
                        # 只从启动器 intent-filter 获取图标
                        if child.get('_filter_icon'):
                            filter_icon = child['_filter_icon']
                        # 获取 order（数值越高优先级越高）
                        child_order = child.get('attrs', {}).get('order')
                        if child_order is not None:
                            if order is None:
                                order = int(child_order)
                            else:
                                order = max(order, int(child_order))
            
            if has_launcher_filter:
                # app_logger.debug(f"  -> 启动器入口: alias='{alias_name}', targetActivity='{target_activity}', enabled={alias_enabled}, order={order}")
                result['launch_aliases'].append({
                    'name': alias_name,
                    'icon': alias['attrs'].get('icon', None),
                    'filter_icon': filter_icon,
                    'targetActivity': target_activity,
                    'label': alias['attrs'].get('label', None),
                    'enabled': alias_enabled,
                    'order': order,
                    '_index': declaration_index  # 记录声明顺序
                })
                declaration_index += 1
        
        # 按照 Android 官方规则排序: 有 order 的优先（降序）> 无 order 的按声明顺序
        # order 数值越高优先级越高，没有 order 的排在后面，按声明顺序排序
        # 排序后列表第一个元素为默认启动入口
        def sort_key(x):
            order = x.get('order')
            # order 为 None 时排在后面（True > False），否则按 order 降序
            return (order is None, -order if order is not None else 0, x.get('_index', 0))
        
        result['launch_activities'].sort(key=sort_key)
        result['launch_aliases'].sort(key=sort_key)
        
        return result
    
    def _resolve_enabled_value(self, attrs, default=True):
        """
        解析 enabled 属性值，支持布尔值和资源引用
        
        参数:
            attrs: 元素属性字典
            default: 默认值（当没有指定 enabled 时）
        
        返回:
            bool: enabled 状态
        """
        # 直接布尔值
        enabled = attrs.get('enabled')
        if enabled is not None:
            if isinstance(enabled, bool):
                return enabled
            if enabled == 'false' or enabled == False or enabled == '0x0':
                return False
            return True
        
        # 资源引用
        enabled_ref = attrs.get('enabled_ref')
        if enabled_ref:
            try:
                res_info = self.get_resource_by_id(enabled_ref)
                if res_info:
                    # 尝试从资源值解析布尔值
                    res_value = res_info.get('value', '')
                    if isinstance(res_value, bool):
                        return res_value
                    if isinstance(res_value, str):
                        if res_value.lower() == 'true' or res_value == '0xffffffff':
                            return True
                        if res_value.lower() == 'false' or res_value == '0x0':
                            return False
                    # 尝试从资源类型判断
                    res_type = res_info.get('type', '')
                    if res_type == 'bool':
                        # bool 资源类型
                        val = res_info.get('value', '')
                        if isinstance(val, bool):
                            return val
                        if isinstance(val, str):
                            return val.lower() != 'false'
            except Exception:
                pass
        
        return default
    
    def _ensure_manifest(self):
        """确保AndroidManifest.xml已解析"""
        if self._manifest_parsed is None:
            if 'AndroidManifest.xml' not in self._xmltree_raw:
                self._xmltree_raw['AndroidManifest.xml'], err = self._run_aapt2_xmltree('AndroidManifest.xml')  # 解析失败，可能会返回空字符串
                if not self._xmltree_raw['AndroidManifest.xml']:
                    app_logger.error(f"获取AndroidManifest.xml原始内容失败: {err}")
            self._manifest_parsed = self._parse_manifest_xmltree(self._xmltree_raw['AndroidManifest.xml'])
        
        return self._manifest_parsed
    
    def _ensure_resources_raw(self):
        """确保资源原始数据已获取"""
        if self._resources_raw is None:
            stdout, stderr, returncode = self._run_aapt2(['dump', 'resources'], timeout=120)
            if len(stdout) < 20:
                if stderr and len(stderr) > 500:
                    stderr_preview = stderr[:500] + "..."
                else:
                    stderr_preview = stderr
                app_logger.error(f"获取resources信息失败：{stderr_preview}")
                raise ValueError(f"获取resources信息失败：{stderr_preview}")

            if stdout:
                resource_count = stdout.count('resource ')
                if resource_count < 6:
                    app_logger.warning(f"资源数量异常少: {resource_count} 个资源")
            self._resources_raw = stdout
        return self._resources_raw
    
    def _parse_single_resource(self, res_id_str):
        """
        从原始数据中解析单个资源ID的信息
        
        参数:
            res_id_str: 资源ID字符串，如 '0x7f0f0000'
        
        返回:
            资源信息字典，或None
        """
        raw = self._ensure_resources_raw()
        if not raw:
            return None
        
        lines = raw.split('\n')
        
        for i, line in enumerate(lines):
            line = line.strip()
            
            if line.startswith(f'resource {res_id_str} '):
                match = re.match(rf'resource {res_id_str} ([\w]+)/([\w.$_]+)', line)
                if match:
                    res_type = match.group(1)
                    res_name = match.group(2)
                    
                    configs = []
                    color_value = None
                    dimen_value = None
                    
                    for j in range(i + 1, len(lines)):
                        config_line = lines[j].strip()
                        
                        if config_line.startswith('resource ') or config_line.startswith('type '):
                            break
                        
                        if config_line:
                            config = None
                            path = None
                            file_type = None
                            res_type_from_config = None
                            reference = None
                            
                            config_match = re.match(r'\(([^)]*)\)\s+\(([^)]*)\)\s+(\S+)\s+type=(\w+)', config_line)
                            if config_match:
                                config = config_match.group(1).strip()
                                file_type = config_match.group(2).strip()
                                path = config_match.group(3).strip()
                                res_type_from_config = config_match.group(4).strip()
                            else:
                                config_match = re.match(r'\(([^)]*)\)\s+\(([^)]*)\)\s+(\S+)$', config_line)
                                if config_match:
                                    config = config_match.group(1).strip()
                                    file_type = config_match.group(2).strip()
                                    path = config_match.group(3).strip()
                                    if path.endswith('.png'):
                                        res_type_from_config = 'PNG'
                                    elif path.endswith('.jpg') or path.endswith('.jpeg'):
                                        res_type_from_config = 'JPEG'
                                    elif path.endswith('.xml'):
                                        res_type_from_config = 'XML'
                                    elif path.endswith('.webp'):
                                        res_type_from_config = 'WebP'
                                    else:
                                        res_type_from_config = 'file'
                                else:
                                    config_match = re.match(r'\(([^)]*)\)\s+"([^"]+)"', config_line)
                                    if config_match:
                                        config = config_match.group(1).strip()
                                        path = config_match.group(2).strip()
                                        file_type = 'file'
                                        if path.endswith('.png'):
                                            res_type_from_config = 'PNG'
                                        elif path.endswith('.jpg') or path.endswith('.jpeg'):
                                            res_type_from_config = 'JPEG'
                                        elif path.endswith('.xml'):
                                            res_type_from_config = 'XML'
                                        elif path.endswith('.webp'):
                                            res_type_from_config = 'WebP'
                                        else:
                                            res_type_from_config = 'file'
                                    else:
                                        ref_match = re.match(r'\(([^)]*)\)\s+(@[\w/]+)', config_line)
                                        if ref_match:
                                            config = ref_match.group(1).strip()
                                            reference = ref_match.group(2).strip()
                                            file_type = 'reference'
                                            res_type_from_config = 'reference'
                                        else:
                                            color_match = re.match(r'\([^)]*\)\s+(#[0-9a-fA-F]+)', config_line)
                                            if color_match:
                                                color_value = color_match.group(1)
                                                config = None
                                        dimen_match = re.match(r'\([^)]*\)\s+([\d.]+(?:[dp]x?|%)?)', config_line)
                                        if dimen_match:
                                            dimen_value = dimen_match.group(1)
                                            config = None
                            
                            if config is not None:
                                configs.append({
                                    'config': config,
                                    'path': path,
                                    'type': file_type,
                                    'res_type': res_type_from_config,
                                    'reference': reference
                                })
                    
                    return {
                        'id': res_id_str,
                        'type': res_type,
                        'name': res_name,
                        'configs': configs,
                        'color_value': color_value,
                        'dimen_value': dimen_value
                    }
        
        return None
    
    def get_resource_by_id(self, resource_id):
        """
        根据资源ID获取资源信息（按需解析并缓存）
        
        参数:
            resource_id: 资源ID（可以是十六进制字符串如'0x7f0f0000'或整数）
        
        返回:
            资源信息字典
        """
        if isinstance(resource_id, int):
            res_id_str = f"0x{resource_id:08x}"
        else:
            res_id_str = resource_id if resource_id.startswith('0x') else f"0x{int(resource_id, 16):08x}"
        
        if res_id_str in self._resources_parsed:
            return self._resources_parsed[res_id_str]
        
        result = self._parse_single_resource(res_id_str)
        if result:
            self._resources_parsed[res_id_str] = result
        
        return result
    
    def get_resource_by_name(self, resource_name):
        """
        根据资源名称获取资源信息
        
        参数:
            resource_name: 资源名称，如 '@mipmap/ic_launcher' 或 'mipmap/ic_launcher'
        
        返回:
            资源信息字典，或None
        """
        if resource_name.startswith('@'):
            resource_name = resource_name[1:]
        
        parts = resource_name.split('/')
        if len(parts) != 2:
            return None
        
        res_type = parts[0]
        res_name = parts[1]
        
        raw = self._ensure_resources_raw()
        if not raw:
            return None
        
        lines = raw.split('\n')
        
        for i, line in enumerate(lines):
            line = line.strip()
            
            pattern = rf'resource (0x[0-9a-fA-F]+) {re.escape(res_type)}/{re.escape(res_name)}'
            match = re.match(pattern, line)
            if match:
                res_id = match.group(1)
                return self.get_resource_by_id(res_id)
        
        return None
    
    def get_basic_info(self):
        """获取APK基本信息"""
        return self._ensure_badging()
    
    def get_native_code(self):
        """
        获取APK支持的CPU架构列表
        
        返回:
            list: 支持的ABI架构列表，如 ['arm64-v8a', 'armeabi-v7a']
                  如果是纯Java应用则返回空列表
        """
        info = self._ensure_badging()
        return info.get('native_code', [])
    
    def analyze_arch_support(self):
        """
        分析APK支持的CPU架构，生成友好的显示文本
        
        根据native_code列表分析支持的架构类型，按ARM、x86、MIPS、RISC-V等系列分类，
        判断每个系列支持的位数（32位、64位、或两者都支持）。
        对于无法识别的架构，在日志中输出warning警告。
        
        返回:
            dict: 包含以下字段:
                - is_pure_java: bool, 是否为纯Java应用（无native库）
                - native_codes: list, 原始ABI列表
                - arm_support: str or None, ARM系列支持情况 ('32位', '64位', '32+64位')
                - x86_support: str or None, x86系列支持情况 ('32位', '64位', '32+64位')
                - mips_support: str or None, MIPS系列支持情况 ('32位', '64位', '32+64位')
                - riscv_support: str or None, RISC-V系列支持情况 ('64位')
                - other_archs: list, 其他无法识别的架构
                - display_text: str, 友好的显示文本
        """
        native_codes = self.get_native_code()
        
        result = {
            'is_pure_java': len(native_codes) == 0,
            'native_codes': native_codes,
            'arm_support': None,
            'x86_support': None,
            'mips_support': None,
            'riscv_support': None,
            'other_archs': [],
            'display_text': ''
        }
        
        if not native_codes:
            result['display_text'] = '纯应用'
            return result
        
        known_abis = {
            'armeabi', 'armeabi-v7a', 'arm64-v8a',
            'x86', 'x86_64',
            'mips', 'mips64',
            'riscv64'
        }
        
        arm_32 = any(abi in native_codes for abi in ['armeabi', 'armeabi-v7a'])
        arm_64 = 'arm64-v8a' in native_codes
        x86_32 = 'x86' in native_codes
        x86_64 = 'x86_64' in native_codes
        mips_32 = 'mips' in native_codes
        mips_64 = 'mips64' in native_codes
        riscv_64 = 'riscv64' in native_codes
        
        for abi in native_codes:
            if abi not in known_abis:
                result['other_archs'].append(abi)
                app_logger.warning(f"发现未知CPU架构: {abi}")
        
        if arm_32 and arm_64:
            result['arm_support'] = '32+64位'
        elif arm_64:
            result['arm_support'] = '64位'
        elif arm_32:
            result['arm_support'] = '32位'
        
        if x86_32 and x86_64:
            result['x86_support'] = '32+64位'
        elif x86_64:
            result['x86_support'] = '64位'
        elif x86_32:
            result['x86_support'] = '32位'
        
        if mips_32 and mips_64:
            result['mips_support'] = '32+64位'
        elif mips_64:
            result['mips_support'] = '64位'
        elif mips_32:
            result['mips_support'] = '32位'
        
        if riscv_64:
            result['riscv_support'] = '64位'
        
        display_parts = []
        if result['arm_support']:
            display_parts.append(f"{result['arm_support']}ARM")
        if result['x86_support']:
            display_parts.append(f"{result['x86_support']}x86")
        if result['mips_support']:
            display_parts.append(f"{result['mips_support']}MIPS")
        if result['riscv_support']:
            display_parts.append(f"{result['riscv_support']}RISC-V")
        
        if display_parts:
            result['display_text'] = ', '.join(display_parts)
        elif result['other_archs']:
            result['display_text'] = '未知'
        
        return result
    
    def get_permissions(self):
        """获取权限列表（从badging中获取）"""
        info = self._ensure_badging()
        return info.get('permissions', [])
    
    def get_launch_activities(self):
        """获取启动Activity列表"""
        parsed = self._ensure_manifest()
        return parsed.get('launch_activities', [])
    
    def get_launch_aliases(self):
        """获取启动Activity-alias列表"""
        parsed = self._ensure_manifest()
        return parsed.get('launch_aliases', [])
    
    def get_application_icon_id(self):
        """
        获取应用的默认图标资源ID，按照 Android 官方优先级顺序查找
        
        选择逻辑：
            1. 合并 launch_aliases 和 launch_activities，统一按 order 降序排序
               （Android PackageManager.queryIntentActivities() 的行为）
            2. 选择排序后的第一个入口作为默认启动入口
            3. 按优先级获取该入口的图标：
               - intent-filter 的 icon（最高优先级）
               - activity-alias/activity 的 icon
               - application 的 icon（默认值）
        
        注意：
            - order 数值越高优先级越高
            - activity 和 activity-alias 在 Android 中没有固有优先级差异
            - 统一按 order 排序后，第一个元素是优先级最高的启动入口
        
        返回:
            str: 资源ID字符串，如 '0x7f0f0000'，如果没有则返回 None
        """
        app_logger.debug("开始获取应用默认图标ID")
        parsed = self._ensure_manifest()
        
        launch_aliases = parsed.get('launch_aliases', [])
        launch_activities = parsed.get('launch_activities', [])
        
        app_logger.debug(f"启动入口数量: aliases={len(launch_aliases)}, activities={len(launch_activities)}")
        
        # 合并所有启动入口，统一按 order 排序
        # Android PackageManager.queryIntentActivities() 的行为：
        # 返回所有匹配的组件（包括 activity 和 activity-alias），按 order 排序
        all_launch_entries = []
        
        for entry in launch_aliases:
            entry_copy = entry.copy()
            entry_copy['_type'] = 'alias'
            all_launch_entries.append(entry_copy)
        
        for entry in launch_activities:
            entry_copy = entry.copy()
            entry_copy['_type'] = 'activity'
            all_launch_entries.append(entry_copy)
        
        # 排序：有 order 的优先（降序）> 无 order 的按声明顺序
        def sort_key(x):
            order = x.get('order')
            return (order is None, -order if order is not None else 0, x.get('_index', 0))
        
        all_launch_entries.sort(key=sort_key)
        
        default_entry = None
        if all_launch_entries:
            default_entry = all_launch_entries[0]
            entry_type = default_entry.get('_type', 'activity')
            entry_name = default_entry.get('name', '')
            entry_order = default_entry.get('order')
            app_logger.debug(f"默认启动入口: {entry_type} '{entry_name}' (order={entry_order})")
        
        if default_entry:
            # 按优先级获取该入口的图标
            # 1. intent-filter 的图标（最高优先级）
            filter_icon = default_entry.get('filter_icon')
            if filter_icon:
                app_logger.debug(f"使用 intent-filter 图标: {filter_icon}")
                return filter_icon
            
            # 2. activity/alias 的图标
            entry_icon = default_entry.get('icon')
            if entry_icon:
                app_logger.debug(f"使用入口图标: {entry_icon}")
                return entry_icon
        
        # 3. application 的图标（默认值）
        app_logger.debug("使用 application 默认图标")
        app_icon = parsed.get('application_icon')
        if app_icon:
            app_logger.debug(f"找到 application 图标: {app_icon}")
            return app_icon
        
        app_logger.warning("未找到任何图标资源ID")
        return None
    
    def get_application_icons(self):
        """
        获取application图标的所有分辨率配置
        
        返回:
            list: 图标配置列表
        """
        icon_id = self.get_application_icon_id()
        if icon_id:
            res_info = self.get_resource_by_id(icon_id)
            if res_info:
                return res_info.get('configs', [])
        return []
    
    def get_signature_info(self):
        """
        获取APK签名信息
        
        返回:
            dict: 签名信息
        """
        result = {
            'v1': False,
            'v2': False,
            'v3': False,
            'certificates': []
        }
        
        try:
            zf = self.get_zip_file()
            meta_inf_files = [f for f in zf.namelist() if f.startswith('META-INF/')]
            has_manifest = any('MANIFEST.MF' in f.upper() for f in meta_inf_files)
            has_sig_file = any(f.endswith('.RSA') or f.endswith('.DSA') or f.endswith('.EC') for f in meta_inf_files)
            result['v1'] = has_manifest and has_sig_file
            
            if result['v1']:
                for f in meta_inf_files:
                    if f.endswith('.RSA') or f.endswith('.DSA') or f.endswith('.EC'):
                        try:
                            cert_data = zf.read(f)
                            cert_info = self._parse_v1_certificate(cert_data)
                            if cert_info:
                                result['certificates'].append(cert_info)
                        except Exception:
                            pass
        except Exception:
            pass
        
        try:
            with open(self.apk_path, 'rb') as f:
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
                            
                            total_block_size = block_size + 32
                            f.seek(central_dir_offset - total_block_size)
                            block_data = f.read(total_block_size)
                            
                            pairs_data = block_data[8:8+block_size]
                            
                            v2_id = struct.pack('<I', 0x7109871a)
                            v3_id = struct.pack('<I', 0xf05368c0)
                            
                            result['v2'] = v2_id in pairs_data
                            result['v3'] = v3_id in pairs_data
                            
                            if result['v2'] or result['v3']:
                                v2_certs = self._extract_v2_certificates(pairs_data)
                                if v2_certs:
                                    result['certificates'].extend(v2_certs)
        except Exception:
            pass
        
        result['certificates'] = self._deduplicate_certificates(result['certificates'])
        
        return result
    
    def _parse_v1_certificate(self, cert_data):
        """解析V1签名中的证书信息"""
        try:
            cert_pattern = re.compile(
                b'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----',
                re.DOTALL
            )
            match = cert_pattern.search(cert_data)
            
            if match:
                import base64
                pem_data = match.group()
                der_data = base64.b64decode(
                    pem_data.replace(b'-----BEGIN CERTIFICATE-----', b'')
                           .replace(b'-----END CERTIFICATE-----', b'')
                           .replace(b'\n', b'')
                )
                
                return self._parse_der_certificate(der_data)
            
            offset = 0
            while offset < len(cert_data) - 100:
                idx = cert_data.find(b'\x30\x82', offset)
                if idx < 0:
                    break
                
                if idx + 4 <= len(cert_data):
                    length_bytes = cert_data[idx+2:idx+4]
                    cert_len = (length_bytes[0] << 8) | length_bytes[1]
                    
                    if idx + 4 + cert_len <= len(cert_data):
                        cert_der = cert_data[idx:idx+4+cert_len]
                        
                        if cert_der[4:4+2] == b'\x30\x82' or (len(cert_der) > 4 and cert_der[4] == 0x30):
                            result = self._parse_der_certificate(cert_der)
                            if result and result.get('subject'):
                                return result
                
                offset = idx + 1
        
        except Exception:
            pass
        
        return None
    
    def _extract_v2_certificates(self, pairs_data):
        """从V2/V3签名块中提取证书信息"""
        certificates = []
        
        try:
            v2_id = struct.pack('<I', 0x7109871a)
            v3_id = struct.pack('<I', 0xf05368c0)
            
            for sig_id in [v2_id, v3_id]:
                idx = pairs_data.find(sig_id)
                
                if idx >= 0 and idx >= 8:
                    length = struct.unpack('<Q', pairs_data[idx-8:idx])[0]
                    
                    if length > 4 and idx + 4 + length - 4 <= len(pairs_data):
                        value_data = pairs_data[idx+4:idx+length]
                        certs = self._parse_signers(value_data)
                        certificates.extend(certs)
        
        except Exception:
            pass
        
        return certificates
    
    def _parse_signers(self, value_data):
        """解析signers序列"""
        certificates = []
        
        try:
            if len(value_data) < 4:
                return certificates
            
            signers_length = struct.unpack('<I', value_data[0:4])[0]
            
            if signers_length == 0 or signers_length > len(value_data) - 4:
                return certificates
            
            signers_data = value_data[4:4+signers_length]
            
            offset = 0
            while offset < len(signers_data) - 4:
                signer_length = struct.unpack('<I', signers_data[offset:offset+4])[0]
                
                if signer_length == 0 or offset + 4 + signer_length > len(signers_data):
                    break
                
                signer_data = signers_data[offset+4:offset+4+signer_length]
                
                certs = self._parse_signer(signer_data)
                certificates.extend(certs)
                
                offset += 4 + signer_length
        
        except Exception:
            pass
        
        return certificates
    
    def _parse_signer(self, signer_data):
        """解析单个signer"""
        certificates = []
        
        try:
            if len(signer_data) < 4:
                return certificates
            
            signed_data_length = struct.unpack('<I', signer_data[0:4])[0]
            
            if signed_data_length == 0 or signed_data_length > len(signer_data) - 4:
                return certificates
            
            signed_data = signer_data[4:4+signed_data_length]
            
            certs = self._parse_signed_data(signed_data)
            certificates.extend(certs)
        
        except Exception:
            pass
        
        return certificates
    
    def _parse_signed_data(self, signed_data):
        """解析signed_data"""
        certificates = []
        
        try:
            if len(signed_data) < 4:
                return certificates
            
            digests_length = struct.unpack('<I', signed_data[0:4])[0]
            
            offset = 4 + digests_length
            
            if offset + 4 > len(signed_data):
                return certificates
            
            certs_length = struct.unpack('<I', signed_data[offset:offset+4])[0]
            
            if certs_length == 0 or offset + 4 + certs_length > len(signed_data):
                return certificates
            
            certs_data = signed_data[offset+4:offset+4+certs_length]
            
            cert_offset = 0
            while cert_offset < len(certs_data) - 4:
                cert_length = struct.unpack('<I', certs_data[cert_offset:cert_offset+4])[0]
                
                if cert_length == 0 or cert_offset + 4 + cert_length > len(certs_data):
                    break
                
                cert_der = certs_data[cert_offset+4:cert_offset+4+cert_length]
                
                if len(cert_der) > 10:
                    cert_info = self._parse_der_certificate(cert_der)
                    if cert_info and cert_info.get('subject'):
                        certificates.append(cert_info)
                
                cert_offset += 4 + cert_length
        
        except Exception:
            pass
        
        return certificates
    
    def _parse_der_certificate(self, der_data):
        """解析DER格式证书，提取基本信息"""
        try:
            cert_info = {
                'serial_number': None,
                'issuer': None,
                'subject': None,
                'not_before': None,
                'not_after': None,
                'signature_algorithm': None,
                'sha256': hashlib.sha256(der_data).hexdigest().upper(),
                'sha1': hashlib.sha1(der_data).hexdigest().upper(),
                'md5': hashlib.md5(der_data).hexdigest().upper(),
                'sha512': hashlib.sha512(der_data).hexdigest().upper(),
                'der_data': der_data,
            }
            
            def parse_length(data, offset):
                if offset >= len(data):
                    return 0, offset
                
                first_byte = data[offset]
                if first_byte < 0x80:
                    return first_byte, offset + 1
                elif first_byte == 0x81:
                    if offset + 1 >= len(data):
                        return 0, offset
                    return data[offset + 1], offset + 2
                elif first_byte == 0x82:
                    if offset + 2 >= len(data):
                        return 0, offset
                    return (data[offset + 1] << 8) | data[offset + 2], offset + 3
                return 0, offset
            
            def extract_string(data, start):
                if start >= len(data):
                    return None
                
                tag = data[start]
                
                if tag in [0x0c, 0x13, 0x14, 0x16, 0x17, 0x18, 0x19]:
                    if start + 1 >= len(data):
                        return None
                    length = data[start + 1]
                    if start + 2 + length > len(data):
                        return None
                    try:
                        return data[start + 2:start + 2 + length].decode('utf-8', errors='ignore')
                    except Exception:
                        return None
                return None
            
            def parse_oid_value(oid_bytes):
                oids = {
                    b'\x55\x04\x03': 'CN',
                    b'\x55\x04\x06': 'C',
                    b'\x55\x04\x07': 'L',
                    b'\x55\x04\x08': 'ST',
                    b'\x55\x04\x0a': 'O',
                    b'\x55\x04\x0b': 'OU',
                    b'\x2a\x86\x48\x86\xf7\x0d\x01\x09\x01': 'E',
                }
                return oids.get(oid_bytes, oid_bytes.hex() if oid_bytes else '')
            
            def format_time(time_str):
                if not time_str:
                    return None
                
                try:
                    time_str = time_str.strip()
                    if time_str.endswith('Z'):
                        time_str = time_str[:-1]
                    
                    if len(time_str) == 12:
                        year = int(time_str[0:2])
                        if year >= 50:
                            year += 1900
                        else:
                            year += 2000
                        month = time_str[2:4]
                        day = time_str[4:6]
                        hour = time_str[6:8]
                        minute = time_str[8:10]
                        second = time_str[10:12]
                        return f"{year}-{month}-{day} {hour}:{minute}:{second}"
                    elif len(time_str) >= 14:
                        year = time_str[0:4]
                        month = time_str[4:6]
                        day = time_str[6:8]
                        hour = time_str[8:10]
                        minute = time_str[10:12]
                        second = time_str[12:14]
                        return f"{year}-{month}-{day} {hour}:{minute}:{second}"
                except Exception:
                    pass
                
                return time_str
            
            def extract_rdn(data, start, length):
                components = {}
                end = start + length
                offset = start
                
                while offset < end - 2:
                    if data[offset] != 0x31:
                        offset += 1
                        continue
                    
                    set_length, next_offset = parse_length(data, offset + 1)
                    if set_length == 0:
                        break
                    
                    set_end = next_offset + set_length
                    if set_end > end:
                        break
                    
                    if next_offset < set_end and data[next_offset] == 0x30:
                        seq_start = next_offset + 1
                        seq_length, seq_data_start = parse_length(data, seq_start)
                        
                        if seq_data_start + seq_length <= set_end:
                            if seq_data_start < set_end and data[seq_data_start] == 0x06:
                                oid_length = data[seq_data_start + 1]
                                oid_bytes = data[seq_data_start + 2:seq_data_start + 2 + oid_length]
                                
                                value_start = seq_data_start + 2 + oid_length
                                if value_start < set_end:
                                    value = extract_string(data, value_start)
                                    if value:
                                        oid_name = parse_oid_value(oid_bytes)
                                        components[oid_name] = value
                    
                    offset = set_end
                
                return components
            
            def format_dn(components):
                if not components:
                    return None
                parts = []
                for key in ['CN', 'OU', 'O', 'L', 'ST', 'C', 'E']:
                    if key in components:
                        parts.append(f"{key}={components[key]}")
                return ', '.join(parts) if parts else str(components)
            
            if len(der_data) < 10:
                return cert_info
            
            cert_start = 0
            if der_data[0] == 0x30:
                outer_len, outer_content = parse_length(der_data, 1)
                
                if outer_content < len(der_data) and der_data[outer_content] == 0x30:
                    tbs_len, tbs_start = parse_length(der_data, outer_content + 1)
                    cert_start = outer_content
                elif outer_content < len(der_data) and der_data[outer_content] == 0x02:
                    cert_start = 0
                else:
                    if outer_content < len(der_data):
                        cert_start = outer_content
            
            offset = cert_start
            
            if offset >= len(der_data):
                return cert_info
            
            if der_data[offset] == 0x30:
                tbs_len, tbs_start = parse_length(der_data, offset + 1)
                offset = tbs_start
            
            if offset < len(der_data) and der_data[offset] == 0xa0:
                skip_len, next_off = parse_length(der_data, offset + 1)
                offset = next_off + skip_len
            
            if offset < len(der_data) and der_data[offset] == 0x02:
                serial_len = der_data[offset + 1]
                serial_bytes = der_data[offset + 2:offset + 2 + serial_len]
                try:
                    cert_info['serial_number'] = hex(int.from_bytes(serial_bytes, 'big'))
                except Exception:
                    pass
                offset += 2 + serial_len
            
            if offset < len(der_data) and der_data[offset] == 0x30:
                sig_seq_len, sig_seq_start = parse_length(der_data, offset + 1)
                if sig_seq_start < len(der_data) and der_data[sig_seq_start] == 0x06:
                    oid_len = der_data[sig_seq_start + 1]
                    oid_bytes = der_data[sig_seq_start + 2:sig_seq_start + 2 + oid_len]
                    
                    sig_oids = {
                        b'\x2a\x86\x48\x86\xf7\x0d\x01\x01\x0b': 'SHA256withRSA',
                        b'\x2a\x86\x48\x86\xf7\x0d\x01\x01\x0c': 'SHA384withRSA',
                        b'\x2a\x86\x48\x86\xf7\x0d\x01\x01\x0d': 'SHA512withRSA',
                        b'\x2a\x86\x48\x86\xf7\x0d\x01\x01\x05': 'SHA1withRSA',
                        b'\x2a\x86\x48\xce\x3d\x04\x03\x02': 'SHA256withECDSA',
                        b'\x2a\x86\x48\xce\x3d\x04\x03\x03': 'SHA384withECDSA',
                    }
                    cert_info['signature_algorithm'] = sig_oids.get(oid_bytes, 'Unknown')
                offset = sig_seq_start + sig_seq_len
            
            if offset < len(der_data) and der_data[offset] == 0x30:
                issuer_len, issuer_start = parse_length(der_data, offset + 1)
                issuer_components = extract_rdn(der_data, issuer_start, issuer_len)
                cert_info['issuer'] = format_dn(issuer_components)
                offset = issuer_start + issuer_len
            
            if offset < len(der_data) and der_data[offset] == 0x30:
                validity_len, validity_start = parse_length(der_data, offset + 1)
                
                if validity_start < len(der_data) and der_data[validity_start] == 0x17:
                    not_before = extract_string(der_data, validity_start)
                    if not_before:
                        cert_info['not_before'] = format_time(not_before)
                
                not_after_offset = validity_start
                if validity_start < len(der_data):
                    if der_data[validity_start] == 0x17:
                        not_after_offset = validity_start + 2 + der_data[validity_start + 1]
                    elif der_data[validity_start] == 0x18:
                        not_after_offset = validity_start + 2 + der_data[validity_start + 1]
                    
                    if not_after_offset < validity_start + validity_len and not_after_offset < len(der_data):
                        not_after = extract_string(der_data, not_after_offset)
                        if not_after:
                            cert_info['not_after'] = format_time(not_after)
                
                offset = validity_start + validity_len
            
            if offset < len(der_data) and der_data[offset] == 0x30:
                subject_len, subject_start = parse_length(der_data, offset + 1)
                subject_components = extract_rdn(der_data, subject_start, subject_len)
                cert_info['subject'] = format_dn(subject_components)
            
            return cert_info
        
        except Exception:
            return None
    
    def _deduplicate_certificates(self, certificates):
        """去重证书列表"""
        seen = set()
        unique = []
        
        for cert in certificates:
            if cert and cert.get('sha256'):
                if cert['sha256'] not in seen:
                    seen.add(cert['sha256'])
                    unique.append(cert)
        
        return unique
    
    def get_file_info(self):
        """获取APK文件信息"""
        result = {
            'path': self.apk_path,
            'size': 0,
            'md5': None,
        }
        
        try:
            if os.path.exists(self.apk_path):
                result['size'] = os.path.getsize(self.apk_path)
                
                md5_hash = hashlib.md5()
                
                with open(self.apk_path, 'rb') as f:
                    while True:
                        chunk = f.read(8192)
                        if not chunk:
                            break
                        md5_hash.update(chunk)
                
                result['md5'] = md5_hash.hexdigest().upper()
        
        except Exception:
            pass
        
        return result
    
    def get_icon_image(self, resource_id=None, size=432):
        """
        获取图标图像数据，支持推测逻辑
        
        参数:
            resource_id: 资源ID，如果为None则使用应用默认图标
            size: 输出尺寸，默认432x432
        
        返回:
            tuple: (icon_data, icon_sure)
                icon_data: PNG图像数据，或None
                icon_sure: True表示确定的图标，False表示推测的图标
        """
        try:
            if resource_id is None:
                app_logger.debug(f"开始获取图标")
            else:
                app_logger.debug(f"开始获取图标, resource_id={resource_id}")
            
            if resource_id is None:
                icon_id = self.get_application_icon_id()
                if icon_id:
                    resource_id = icon_id
                    app_logger.debug(f"从manifest获取图标ID: {icon_id}")
            
            if resource_id is None:
                info = self._ensure_badging()
                icons = info.get('application_icon', [])
                if icons:
                    app_logger.debug(f"从badging获取到 {len(icons)} 个图标路径: {icons}")
                    sorted_icons = self._sort_by_density(icons, 'path')
                    for icon_info in sorted_icons:
                        icon_path = icon_info.get('path', '')
                        density_value = icon_info.get('density', 0)
                        density_name = DENSITY_NAME_MAP.get(density_value, str(density_value) if density_value else '')
                        if icon_path:
                            app_logger.debug(f"尝试加载图标: {icon_path} (density: {density_name})")
                            # 区分XML格式和其他图片格式
                            if icon_path.endswith('.xml'):
                                icon_data = self._render_xml_icon(icon_path, size)
                            else:
                                icon_data = self._load_icon_from_path(icon_path)
                            if icon_data:
                                app_logger.debug(f"成功加载图标: {icon_path} (density: {density_name})")
                                return icon_data, True
                app_logger.warning("未找到图标资源ID，尝试推测图标")
                return self._guess_icon_image()
            
            res_info = self.get_resource_by_id(resource_id)
            if not res_info:
                app_logger.warning(f"未找到资源: {resource_id}，尝试推测图标")
                return self._guess_icon_image()
            
            configs = res_info.get('configs', [])
            app_logger.debug(f"资源 {resource_id} 有 {len(configs)} 个配置")
            
            for config in configs:
                app_logger.debug(f"配置: config={config.get('config', '')}, path={config.get('path')}, type={config.get('type')}, reference={config.get('reference')}")
            
            sorted_configs = self._sort_by_density(configs)
            
            for indx, config in enumerate(sorted_configs):
                app_logger.debug(f"按照优先级排序后，尝试解析图标 #{indx+1}: config={config.get('config', '')}")

                # 1、优先处理资源引用，进一步解析具体图标文件路径
                reference = config.get('reference')
                if reference:
                    app_logger.debug(f"发现引用: {reference}")
                    ref_res_info = self.get_resource_by_name(reference)
                    if ref_res_info:
                        ref_configs = ref_res_info.get('configs', [])
                        sorted_ref_configs = self._sort_by_density(ref_configs)
                        for ref_config in sorted_ref_configs:
                            ref_path = ref_config.get('path', '')
                            if ref_path and ref_path.endswith('.xml'):
                                icon_data = self._render_xml_icon(ref_path, size)
                                if icon_data:
                                    return icon_data, True
                                else:
                                    app_logger.warning(f"XML图标渲染失败，跳过: {ref_path}")
                                    continue
                            elif ref_path:
                                icon_data = self._load_icon_from_path(ref_path)
                                if icon_data:
                                    return icon_data, True
            
                # 2、处理 XML 类型文件、其他图片类型文件
                path = config.get('path', '')
                if path:
                    if path.endswith('.xml'):
                        icon_data = self._render_xml_icon(path, size)
                        if icon_data:
                            return icon_data, True
                        else:
                            app_logger.warning(f"XML图标渲染失败，跳过: {path}")
                            continue
                    else:
                        icon_data = self._load_icon_from_path(path)
                        if icon_data:
                            return icon_data, True
            
            app_logger.warning("所有图标获取方式都失败，尝试推测图标")
            return self._guess_icon_image()
        
        except Exception as e:
            app_logger.error(f"获取图标出错: {e}")
            return None, False
    
    def _guess_icon_image(self):
        """
        推测图标图像数据
        
        当标准方式无法获取图标时，尝试通过以下方式推测:
        1. 根据资源名（@mipmap/ic_launcher、@drawable/ic_launcher）查找资源
        2. 根据文件名进行模糊匹配（ic_launcher等），支持png/webp/xml格式
        
        返回:
            tuple: (icon_data, icon_sure)
                icon_data: PNG图像数据，或None
                icon_sure: 推测的图标总是返回False
        """
        try:
            app_logger.debug("开始推测图标")
            # 1. 先推测是否存在 @mipmap/ic_launcher、@drawable/ic_launcher 两个资源名称
            guess_resource_names = ['@mipmap/ic_launcher', '@drawable/ic_launcher']
            for res_name in guess_resource_names:
                app_logger.debug(f"尝试查找资源: {res_name}")
                res_info = self.get_resource_by_name(res_name)
                if res_info:
                    configs = res_info.get('configs', [])
                    sorted_configs = self._sort_by_density(configs)
                    
                    for config in sorted_configs:
                        path = config.get('path', '')
                        if path:
                            app_logger.debug(f"找到资源路径: {path}")
                            if path.endswith('.xml'):
                                icon_data = self._render_xml_icon(path, 432)
                                if icon_data:
                                    app_logger.debug(f"成功渲染XML图标: {path}")
                                    return icon_data, False
                                else:
                                    app_logger.warning(f"XML图标渲染失败，跳过: {path}")
                                    continue
                            else:
                                icon_data = self._load_icon_from_path(path)
                                if icon_data:
                                    app_logger.debug(f"成功加载图片图标: {path}")
                                    return icon_data, False
            
            files = self.get_files_list()
            guess_icons = ["ic_launcher.png"]
            density_order = ['-xxxhdpi', '-xxhdpi', '-xhdpi', '-hdpi', '-mdpi', '-ldpi', '-tvdpi', '-nodpi', '-anydpi']
            
            new_file_list = []
            for ic_path in guess_icons:
                ic_base_name = os.path.basename(ic_path)
                ic_filename, ic_ext = os.path.splitext(ic_base_name)
                for file_path in files:
                    if f"/{ic_filename}." in file_path and (file_path.startswith('res/mipmap') or file_path.startswith('res/drawable')):
                        root, ext = os.path.splitext(file_path)
                        if ext.lower() in [".png", ".webp", ".xml"]:
                            new_file_list.append(file_path)
            
            if new_file_list:
                new_file_list.sort(key=lambda x: x.endswith('.xml'))
                for density in density_order:
                    for file_path in new_file_list:
                        if density in file_path:
                            app_logger.debug(f"推测图标(模糊匹配): {file_path}")
                            if file_path.endswith('.xml'):
                                icon_data = self._render_xml_icon(file_path, 432)
                                if icon_data:
                                    app_logger.debug(f"成功渲染XML图标: {file_path}")
                                    return icon_data, False
                                else:
                                    app_logger.warning(f"XML图标渲染失败，跳过: {file_path}")
                                    continue
                            else:
                                icon_data = self._load_icon_from_path(file_path)
                                if icon_data:
                                    app_logger.debug(f"成功加载图片图标: {file_path}")
                                    return icon_data, False
            
            app_logger.info("找不到推测图标")
            return None, False
        
        except Exception as e:
            app_logger.warning(f"推测图标失败: {e}")
            return None, False
    
    def _sort_by_density(self, items, key_field='config'):
        """
        按照分辨率密度优先级排序
        
        优先级顺序: anydpi > xxxhdpi > xxhdpi > xhdpi > hdpi > tvdpi > mdpi > nodpi > ldpi
        同密度时，API级别高的优先（v31 > v26 > v21 等）
        
        参考 Android 源码 ResourceTypes.cpp:
        - anydpi (DENSITY_ANY) 具有最高优先级，因为矢量图可无损缩放到任意尺寸
        - 位图密度按从高到低排序，获取最高质量图标
        
        参数:
            items: 待排序列表（配置列表或图标列表）
            key_field: 用于获取密度信息的字段名，'config' 用于配置，'path' 用于图标
        
        返回:
            排序后的列表
        """
        density_priority = {
            'anydpi': 1,    # 矢量图，可无损缩放到任意尺寸（最高优先级）
            'xxxhdpi': 2,   # 640dpi - 最高位图质量
            'xxhdpi': 3,    # 480dpi
            'xhdpi': 4,     # 320dpi
            'hdpi': 5,      # 240dpi
            'tvdpi': 6,     # 213dpi - 电视密度
            'mdpi': 7,      # 160dpi - 基准密度
            'nodpi': 8,     # 不缩放
            'ldpi': 9,      # 120dpi - 最低质量
        }
        
        def get_priority(item):
            value = item.get(key_field, '')
            density_prio = 99
            for density, priority in density_priority.items():
                if density in value.lower():
                    density_prio = priority
                    break
            
            v_match = re.search(r'v(\d+)', value.lower())
            api_level = int(v_match.group(1)) if v_match else 0
            
            return (density_prio, -api_level)
        
        return sorted(items, key=get_priority)
    
    def _load_icon_from_path(self, path):
        """从APK中加载图标文件"""
        try:
            zf = self.get_zip_file()
            if path in zf.namelist():
                return zf.read(path)
        except Exception as e:
            app_logger.debug(f"加载失败: {path}, 错误: {e}")
        return None
    
    def _save_xml_icon(self, icon_data, density=None):
        """
        保存XML图标到cache目录
        
        参数:
            icon_data: 图标二进制数据
            density: 分辨率信息（如mdpi, hdpi等），可选
        """
        try:
            cache_dir = os.path.join(os.getcwd(), 'cache')
            if not os.path.exists(cache_dir):
                os.makedirs(cache_dir, exist_ok=True)
            
            apk_filename = os.path.basename(self.apk_path)
            apk_name_no_ext = os.path.splitext(apk_filename)[0]
            
            if density:
                icon_filename = f"{apk_name_no_ext}_{density}.png"
            else:
                icon_filename = f"{apk_name_no_ext}.png"
            
            icon_path = os.path.join(cache_dir, icon_filename)
            
            with open(icon_path, 'wb') as f:
                f.write(icon_data)
            
            app_logger.info(f"XML图标已保存: {icon_path}")
            return True
        except Exception as e:
            app_logger.error(f"保存失败: {e}")
            return False
    
    def save_all_xml_icons(self):
        """
        收集并保存所有XML格式的图标到cache目录
        
        功能说明:
            1. 从AndroidManifest.xml或badging信息中获取应用图标资源ID
            2. 根据资源ID获取所有配置（不同密度、主题等）
            3. 按照屏幕密度优先级排序配置
            4. 遍历配置，处理资源引用或直接解析XML文件
            5. 将XML图标渲染为PNG格式并保存到cache目录
        
        处理流程:
            - 优先从manifest获取图标ID，失败则从badging获取
            - 支持处理资源引用（reference），递归解析引用的实际资源
            - 仅处理.xml格式的图标文件
            - 调用_render_xml_icon渲染XML为PNG图像
            - 调用_save_xml_icon保存到cache目录
        
        返回:
            int: 成功保存的图标数量，失败时返回已保存的数量
        """
        saved_count = 0
        try:
            app_logger.debug("开始收集所有XML图标")
            
            icon_id = self.get_application_icon_id()
            res_info = None
            if icon_id:
                app_logger.debug(f"从manifest获取图标ID: {icon_id}")
                res_info = self.get_resource_by_id(icon_id)
            else:
                # 无法获取图标ID时，从badging获取图标路径
                info = self._ensure_badging()
                icons = info.get('application_icon', [])
                if not icons:
                    app_logger.warning("未找到图标")
                    return 0
                
                app_logger.debug(f"从badging获取到 {len(icons)} 个图标路径: {icons}")
                # 只处理XML格式的图标文件
                sorted_icons = self._sort_by_density(icons, 'path')
                for icon_info in sorted_icons:
                    icon_path = icon_info.get('path', '')
                    # application_icon 元素结构: {'density': int, 'path': str}
                    density_value = icon_info.get('density', 0)
                    density = DENSITY_NAME_MAP.get(density_value, str(density_value) if density_value else 'default')
                    
                    if icon_path and icon_path.endswith('.xml'):
                        app_logger.debug(f"尝试加载XML图标: {icon_path}")
                        icon_data = self._render_xml_icon(icon_path, 432)
                        if icon_data:
                            app_logger.debug(f"成功渲染XML图标: {icon_path}")
                            if self._save_xml_icon(icon_data, density):
                                saved_count += 1
                        else:
                            app_logger.warning(f"XML图标渲染失败，跳过: {icon_path}")
                
                app_logger.info(f"共保存 {saved_count} 个XML图标")
                return saved_count
            
            if not res_info:
                app_logger.warning("未找到图标资源信息")
                return 0
            
            configs = res_info.get('configs', [])
            app_logger.debug(f"资源 {icon_id} 有 {len(configs)} 个配置")
            
            for config in configs:
                app_logger.debug(f"配置: config={config.get('config')}, path={config.get('path')}, type={config.get('type')}, reference={config.get('reference')}")
            
            sorted_configs = self._sort_by_density(configs)
            
            for indx, config in enumerate(sorted_configs):
                config_name = config.get('config', '')
                path = config.get('path', '')
                reference = config.get('reference')
                
                app_logger.debug(f"按照优先级排序后，尝试解析图标 #{indx+1}: config={config_name}")
                
                density = config_name
                if not density:
                    density = 'default'
                
                # 1、优先处理资源引用，进一步解析具体图标文件路径
                if reference:
                    app_logger.debug(f"发现引用: {reference}")
                    ref_res_info = self.get_resource_by_name(reference)
                    if ref_res_info:
                        ref_configs = ref_res_info.get('configs', [])
                        sorted_ref_configs = self._sort_by_density(ref_configs)
                        for ref_config in sorted_ref_configs:
                            ref_path = ref_config.get('path', '')
                            ref_config_name = ref_config.get('config', '')
                            ref_density = ref_config_name if ref_config_name else density
                            
                            if ref_path and ref_path.endswith('.xml'):
                                app_logger.debug(f"引用资源路径: {ref_path}")
                                icon_data = self._render_xml_icon(ref_path, 432)
                                if icon_data:
                                    app_logger.debug(f"成功渲染XML图标: {ref_path}")
                                    if self._save_xml_icon(icon_data, ref_density):
                                        saved_count += 1
                                else:
                                    app_logger.warning(f"XML图标渲染失败，跳过: {ref_path}")
                
                # 2、处理 XML 类型文件
                elif path and path.endswith('.xml'):
                    app_logger.debug(f"尝试加载XML图标: {path}")
                    icon_data = self._render_xml_icon(path, 432)
                    if icon_data:
                        app_logger.debug(f"成功渲染XML图标: {path}")
                        if self._save_xml_icon(icon_data, density):
                            saved_count += 1
                    else:
                        app_logger.warning(f"XML图标渲染失败，跳过: {path}")
            
            app_logger.info(f"共保存 {saved_count} 个XML图标")
            return saved_count
            
        except Exception as e:
            app_logger.error(f"收集图标出错: {e}")
            return saved_count
    
    def _render_xml_icon(self, xml_path, size=432):
        """
        渲染XML格式的图标
        
        参数:
            xml_path: XML文件在APK中的路径
            size: 输出尺寸
        
        返回:
            bytes: PNG图像数据，或None（解析失败时）
        """
        try:
            app_logger.debug(f"渲染XML图标: {xml_path}")
            xml_content, err = self._run_aapt2_xmltree(xml_path)
            app_logger.debug(f"XML解码原文 ({xml_path}):\n{xml_content}")
            
            if xml_content.strip() == "":
                app_logger.warning(f"获取XML原始内容失败: {xml_path}，{err}")
                return None
            
            parsed = self._parse_xmltree_output(xml_content)
            
            if not parsed or not parsed.get('root_element'):
                app_logger.warning(f"解析XML失败: {xml_path}")
                return None
            
            root = parsed['elements'][0] if parsed['elements'] else {}
            root_name = root.get('name', '')
            app_logger.debug(f"XML根元素: {root_name}")
            
            result = None
            
            if root_name == 'adaptive-icon':
                result = self._render_adaptive_icon(root, size)
            elif root_name == 'vector':
                result = self._render_vector_icon(root, size)
            elif root_name == 'layer-list':
                result = self._render_layer_list_icon(root, size)
            elif root_name == 'selector':
                result = self._render_selector_icon(root, size)
            elif root_name == 'bitmap':
                result = self._render_bitmap_icon(root, size)
            elif root_name == 'shape':
                result = self._render_shape_icon(root, size)
            elif root_name == 'inset':
                result = self._render_inset_icon(root, size)
            else:
                app_logger.warning(f"未知的XML图标类型: {root_name}")
                return None
            
            if result:
                result = self._apply_icon_mask(result, size, root_name)
            
            return result
        
        except Exception as e:
            app_logger.error(f"渲染XML图标失败: {e}")
            import traceback
            app_logger.error(traceback.format_exc())
            return None
    
    def _apply_icon_mask(self, png_data, size, icon_type):
        """
        为图标应用遮罩
        
        参数:
            png_data: PNG图像数据
            size: 图标尺寸
            icon_type: 图标类型（用于日志输出）
        
        返回:
            bytes: 应用遮罩后的PNG图像数据
        """
        try:
            img = Image.open(BytesIO(png_data))
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            
            if img.size != (size, size):
                img = img.resize((size, size), Image.LANCZOS)
            
            mask = self._create_icon_mask(size)
            result_img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            result_img.paste(img, mask=mask)
            
            output = BytesIO()
            result_img.save(output, format='PNG')
            app_logger.debug(f"{icon_type}图标遮罩应用完成")
            return output.getvalue()
            
        except Exception as e:
            app_logger.warning(f"应用遮罩失败: {e}")
            return png_data
    
    def _parse_xmltree_output(self, xml_content):
        """解析aapt2 dump xmltree输出的内容
        
        功能说明:
            将aapt2 dump xmltree命令输出的文本格式解析为结构化的Python字典
            支持解析元素层次结构、属性值、资源引用等
        
        处理流程:
            1. 将输入内容按行分割
            2. 使用栈结构维护元素的嵌套关系
            3. 识别并解析元素(E:)和属性(A:)
            4. 对特殊属性进行专门处理(drawable, color, pathData等)
            5. 构建完整的元素树结构
        
        参数:
            xml_content: aapt2 dump xmltree输出的文本内容
            
        返回:
            dict: 解析结果，包含:
                - root_element: 根元素名称
                - elements: 元素列表，每个元素包含name, attrs, children
        """
        result = {
            'root_element': None,
            'elements': []
        }
        
        def extract_float(value_str):
            """从字符串中提取数值，支持带单位（dp/sp/px等）的值，支持科学计数法"""
            value_str = value_str.strip().rstrip('`').strip()
            match = re.match(r'^(-?\d+\.?\d*([eE][+-]?\d+)?)', value_str)
            if match:
                return float(match.group(1))
            return value_str
        
        def extract_int(value_str):
            """从字符串中提取整数值"""
            value_str = value_str.strip().rstrip('`').strip()
            match = re.match(r'^(-?\d+)', value_str)
            if match:
                return int(match.group(1))
            return value_str
        
        def parse_color_attribute(attr_line, attr_name):
            """解析颜色属性，只接受两种形式：资源引用(@0x...)或颜色值(#...)
            
            Args:
                attr_line: 属性行字符串
                attr_name: 属性名称，用于日志输出
            
            Returns:
                str: 解析后的颜色值，未识别类型返回None并输出警告日志
            """
            attr_value = None
            
            if '=@0x' in attr_line:
                idx = attr_line.find('@0x')
                attr_value = attr_line[idx:idx+11].lower()
            elif '=#' in attr_line:
                idx = attr_line.find('#')
                attr_value = attr_line[idx:idx+9]
            else:
                app_logger.warning(f"未识别的{attr_name}类型: {attr_line}")
            
            return attr_value
        
        def parse_alpha_attribute(attr_line, attr_name):
            """解析透明度属性，接受两种形式：资源引用(@0x...)或浮点数值
            
            Args:
                attr_line: 属性行字符串
                attr_name: 属性名称，用于日志输出
            
            Returns:
                str/float: 解析后的透明度值，资源引用为字符串，浮点数值为float
            """
            attr_value = None
            
            if '=@0x' in attr_line:
                idx = attr_line.find('@0x')
                attr_value = attr_line[idx:idx+11].lower()
            else:
                idx = attr_line.find(')=')
                if idx > 0:
                    temp_value = extract_float(attr_line[idx+2:])
                    if isinstance(temp_value, float):
                        attr_value = temp_value
                    else:
                        app_logger.warning(f"未识别的{attr_name}类型: {attr_line}")
                else:
                    app_logger.warning(f"未识别的{attr_name}类型: {attr_line}")
            
            return attr_value
        
        lines = xml_content.split('\n')
        element_stack = []
        
        # core-res-res-values\public-final.xml 文件中规定了不同类型对应的id号，有些时候解析的结果没有类型名，只有id号。
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            
            indent = len(line) - len(line.lstrip())
            
            while element_stack and element_stack[-1]['indent'] >= indent:
                element_stack.pop()
            
            if stripped.startswith('E: '):
                element_name = stripped[3:].split()[0] if ' ' in stripped[3:] else stripped[3:]
                element = {
                    'name': element_name,
                    'attrs': {},
                    'children': [],
                    'indent': indent
                }
                
                if element_stack:
                    element_stack[-1]['children'].append(element)
                else:
                    result['elements'].append(element)
                    result['root_element'] = element_name
                
                element_stack.append(element)
            
            elif stripped.startswith('A: '):
                if not element_stack:
                    continue
                
                attr_line = stripped[3:]
                attr_name = None
                attr_value = None
                
                # drawable: 0x01010199
                if 'android:drawable' in attr_line  or '(0x01010199)=' in attr_line:
                    if '@0x' in attr_line:
                        idx = attr_line.find('@0x')
                        attr_value = attr_line[idx+1:idx+11].lower()
                        attr_name = 'drawable'
                
                # color: 0x010101a5 (注意：这个color是单独的颜色属性，不是fillColor/strokeColor等)
                elif 'android:color' in attr_line or '(0x010101a5)=' in attr_line:
                    attr_value = parse_color_attribute(attr_line, 'color')
                    attr_name = 'color'
                
                # src: 0x01010119
                elif 'android:src' in attr_line or '(0x01010119)=' in attr_line:
                    if '@0x' in attr_line:
                        idx = attr_line.find('@0x')
                        attr_value = attr_line[idx+1:idx+11].lower()
                    attr_name = 'src'
                
                # fillColor: 0x01010404
                elif 'android:fillColor' in attr_line or '(0x01010404)=' in attr_line:
                    attr_value = parse_color_attribute(attr_line, 'fillColor')
                    attr_name = 'fillColor'
                
                # pathData: 0x01010405
                elif 'android:pathData' in attr_line or '(0x01010405)=' in attr_line:
                    idx = attr_line.find(')="')
                    if idx > 0:
                        rest = attr_line[idx+3:]
                        end_idx = rest.find('"')
                        if end_idx >= 0:
                            attr_value = rest[:end_idx]
                    else:
                        idx = attr_line.find(')=`')
                        if idx > 0:
                            rest = attr_line[idx+3:].strip()
                            if rest.startswith('"'):
                                rest = rest[1:]
                                end_idx = rest.find('"')
                                if end_idx >= 0:
                                    attr_value = rest[:end_idx]
                    attr_name = 'pathData'
                
                # width: 0x01010159
                elif 'android:width' in attr_line or '(0x01010159)=' in attr_line:
                    idx = attr_line.find(')=')
                    if idx > 0:
                        attr_value = extract_float(attr_line[idx+2:])
                    attr_name = 'width'
                
                # height: 0x01010155
                elif 'android:height' in attr_line or '(0x01010155)=' in attr_line:
                    idx = attr_line.find(')=')
                    if idx > 0:
                        attr_value = extract_float(attr_line[idx+2:])
                    attr_name = 'height'
                
                # viewportWidth: 0x01010402
                elif 'android:viewportWidth' in attr_line or '(0x01010402)=' in attr_line:
                    idx = attr_line.find(')=')
                    if idx > 0:
                        attr_value = extract_float(attr_line[idx+2:])
                    attr_name = 'viewportWidth'
                
                # viewportHeight: 0x01010403
                elif 'android:viewportHeight' in attr_line or '(0x01010403)=' in attr_line:
                    idx = attr_line.find(')=')
                    if idx > 0:
                        attr_value = extract_float(attr_line[idx+2:])
                    attr_name = 'viewportHeight'
                
                # translateX: 0x0101045a
                elif 'android:translateX' in attr_line or '(0x0101045a)=' in attr_line:
                    idx = attr_line.find(')=')
                    if idx > 0:
                        attr_value = extract_float(attr_line[idx+2:])
                    attr_name = 'translateX'
                
                # translateY: 0x0101045b
                elif 'android:translateY' in attr_line or '(0x0101045b)=' in attr_line:
                    idx = attr_line.find(')=')
                    if idx > 0:
                        attr_value = extract_float(attr_line[idx+2:])
                    attr_name = 'translateY'
                
                # strokeColor: 0x01010406
                elif 'android:strokeColor' in attr_line or '(0x01010406)=' in attr_line:
                    attr_value = parse_color_attribute(attr_line, 'strokeColor')
                    attr_name = 'strokeColor'
                
                # strokeWidth: 0x01010407
                elif 'android:strokeWidth' in attr_line or '(0x01010407)=' in attr_line:
                    idx = attr_line.find(')=')
                    if idx > 0:
                        attr_value = extract_float(attr_line[idx+2:])
                    attr_name = 'strokeWidth'
                
                # scaleX: 0x01010324
                elif 'android:scaleX' in attr_line or '(0x01010324)=' in attr_line:
                    idx = attr_line.find(')=')
                    if idx > 0:
                        attr_value = extract_float(attr_line[idx+2:])
                    attr_name = 'scaleX'
                
                # scaleY: 0x01010325
                elif 'android:scaleY' in attr_line or '(0x01010325)=' in attr_line:
                    idx = attr_line.find(')=')
                    if idx > 0:
                        attr_value = extract_float(attr_line[idx+2:])
                    attr_name = 'scaleY'
                
                # rotation: 0x01010326
                elif 'android:rotation' in attr_line or '(0x01010326)=' in attr_line:
                    idx = attr_line.find(')=')
                    if idx > 0:
                        attr_value = extract_float(attr_line[idx+2:])
                    attr_name = 'rotation'
                
                # pivotX: 0x010101b5
                elif 'android:pivotX' in attr_line or '(0x010101b5)=' in attr_line:
                    idx = attr_line.find(')=')
                    if idx > 0:
                        attr_value = extract_float(attr_line[idx+2:])
                    attr_name = 'pivotX'
                
                # pivotY: 0x010101b6
                elif 'android:pivotY' in attr_line or '(0x010101b6)=' in attr_line:
                    idx = attr_line.find(')=')
                    if idx > 0:
                        attr_value = extract_float(attr_line[idx+2:])
                    attr_name = 'pivotY'
                
                # fillAlpha: 0x010104cc
                elif 'android:fillAlpha' in attr_line or '(0x010104cc)=' in attr_line:
                    attr_value = parse_alpha_attribute(attr_line, 'fillAlpha')
                    attr_name = 'fillAlpha'
                
                # strokeAlpha: 0x010104cb
                elif 'android:strokeAlpha' in attr_line or '(0x010104cb)=' in attr_line:
                    attr_value = parse_alpha_attribute(attr_line, 'strokeAlpha')
                    attr_name = 'strokeAlpha'
                
                # trimPathStart: 0x01010408
                elif 'android:trimPathStart' in attr_line or '(0x01010408)=' in attr_line:
                    attr_value = parse_alpha_attribute(attr_line, 'trimPathStart')
                    attr_name = 'trimPathStart'
                
                # trimPathEnd: 0x01010409
                elif 'android:trimPathEnd' in attr_line or '(0x01010409)=' in attr_line:
                    attr_value = parse_alpha_attribute(attr_line, 'trimPathEnd')
                    attr_name = 'trimPathEnd'
                
                # trimPathOffset: 0x0101040a
                elif 'android:trimPathOffset' in attr_line or '(0x0101040a)=' in attr_line:
                    attr_value = parse_alpha_attribute(attr_line, 'trimPathOffset')
                    attr_name = 'trimPathOffset'
                
                # fillType: 0x0101051e - Android路径填充规则，0=nonZero(非零环绕), 1=evenOdd(奇偶规则)
                elif 'android:fillType' in attr_line or '(0x0101051e)=' in attr_line:
                    idx = attr_line.find(')=')
                    if idx > 0:
                        attr_value = extract_int(attr_line[idx+2:])
                    attr_name = 'fillType'
                
                # startColor: 0x0101019d
                elif 'android:startColor' in attr_line or '(0x0101019d)=' in attr_line:
                    attr_value = parse_color_attribute(attr_line, 'startColor')
                    attr_name = 'startColor'
                
                # endColor: 0x0101019e
                elif 'android:endColor' in attr_line or '(0x0101019e)=' in attr_line:
                    attr_value = parse_color_attribute(attr_line, 'endColor')
                    attr_name = 'endColor'
                
                # angle: 0x010101a0
                elif 'android:angle' in attr_line or '(0x010101a0)=' in attr_line:
                    idx = attr_line.find(')=')
                    if idx > 0:
                        attr_value = extract_float(attr_line[idx+2:])
                    attr_name = 'angle'
                
                # type: 0x010101a1 (gradient type)
                elif 'android:type' in attr_line or '(0x010101a1)=' in attr_line:
                    idx = attr_line.find(')=')
                    if idx > 0:
                        attr_value = extract_int(attr_line[idx+2:])
                    attr_name = 'type'
                
                # offset: 0x01010514
                elif 'android:offset' in attr_line or '(0x01010514)=' in attr_line:
                    idx = attr_line.find(')=')
                    if idx > 0:
                        attr_value = extract_float(attr_line[idx+2:])
                    attr_name = 'offset'
                
                # startX: 0x01010510
                elif 'android:startX' in attr_line or '(0x01010510)=' in attr_line:
                    idx = attr_line.find(')=')
                    if idx > 0:
                        attr_value = extract_float(attr_line[idx+2:])
                    attr_name = 'startX'
                
                # startY: 0x01010511
                elif 'android:startY' in attr_line or '(0x01010511)=' in attr_line:
                    idx = attr_line.find(')=')
                    if idx > 0:
                        attr_value = extract_float(attr_line[idx+2:])
                    attr_name = 'startY'
                
                # endX: 0x01010512
                elif 'android:endX' in attr_line or '(0x01010512)=' in attr_line:
                    idx = attr_line.find(')=')
                    if idx > 0:
                        attr_value = extract_float(attr_line[idx+2:])
                    attr_name = 'endX'
                
                # endY: 0x01010513
                elif 'android:endY' in attr_line or '(0x01010513)=' in attr_line:
                    idx = attr_line.find(')=')
                    if idx > 0:
                        attr_value = extract_float(attr_line[idx+2:])
                    attr_name = 'endY'
                
                # centerX: 0x010101a2
                elif 'android:centerX' in attr_line or '(0x010101a2)=' in attr_line:
                    idx = attr_line.find(')=')
                    if idx > 0:
                        attr_value = extract_float(attr_line[idx+2:])
                    attr_name = 'centerX'
                
                # centerY: 0x010101a3
                elif 'android:centerY' in attr_line or '(0x010101a3)=' in attr_line:
                    idx = attr_line.find(')=')
                    if idx > 0:
                        attr_value = extract_float(attr_line[idx+2:])
                    attr_name = 'centerY'
                
                # gradientRadius: 0x010101a4
                elif 'android:gradientRadius' in attr_line or '(0x010101a4)=' in attr_line:
                    idx = attr_line.find(')=')
                    if idx > 0:
                        attr_value = extract_float(attr_line[idx+2:])
                    attr_name = 'gradientRadius'
                
                # inset: 0x010104b5
                elif 'android:inset' in attr_line or '(0x010104b5)=' in attr_line:
                    if '@0x' in attr_line:
                        idx = attr_line.find('@0x')
                        attr_value = attr_line[idx+1:idx+11].lower()
                    else:
                        idx = attr_line.find(')=')
                        if idx > 0:
                            rest = attr_line[idx+2:]
                            attr_value = rest.strip()
                    attr_name = 'inset'
                
                # insetLeft: 0x010101b7
                elif 'android:insetLeft' in attr_line or '(0x010101b7)=' in attr_line:
                    if '@0x' in attr_line:
                        idx = attr_line.find('@0x')
                        attr_value = attr_line[idx+1:idx+11].lower()
                    else:
                        idx = attr_line.find(')=')
                        if idx > 0:
                            rest = attr_line[idx+2:]
                            attr_value = rest.strip()
                    attr_name = 'insetLeft'
                
                # insetTop: 0x010101b9
                elif 'android:insetTop' in attr_line or '(0x010101b9)=' in attr_line:
                    if '@0x' in attr_line:
                        idx = attr_line.find('@0x')
                        attr_value = attr_line[idx+1:idx+11].lower()
                    else:
                        idx = attr_line.find(')=')
                        if idx > 0:
                            rest = attr_line[idx+2:]
                            attr_value = rest.strip()
                    attr_name = 'insetTop'
                
                # insetRight: 0x010101b8
                elif 'android:insetRight' in attr_line or '(0x010101b8)=' in attr_line:
                    if '@0x' in attr_line:
                        idx = attr_line.find('@0x')
                        attr_value = attr_line[idx+1:idx+11].lower()
                    else:
                        idx = attr_line.find(')=')
                        if idx > 0:
                            rest = attr_line[idx+2:]
                            attr_value = rest.strip()
                    attr_name = 'insetRight'
                
                # insetBottom: 0x010101ba
                elif 'android:insetBottom' in attr_line or '(0x010101ba)=' in attr_line:
                    if '@0x' in attr_line:
                        idx = attr_line.find('@0x')
                        attr_value = attr_line[idx+1:idx+11].lower()
                    else:
                        idx = attr_line.find(')=')
                        if idx > 0:
                            rest = attr_line[idx+2:]
                            attr_value = rest.strip()
                    attr_name = 'insetBottom'
                
                # name: 0x01010003
                elif 'android:name' in attr_line or '(0x01010003)=' in attr_line:
                    # 解析 name 属性，格式: A: http://schemas.android.com/apk/res/android:name(0x01010003)="Shadow" (Raw: "Shadow")
                    # 注意：后面可能有 (Raw: "xxx") 部分，需要正确提取第一个引号对中的值
                    idx = attr_line.find(')="')
                    if idx > 0:
                        rest = attr_line[idx+3:]
                        end_idx = rest.find('"')
                        if end_idx > 0:
                            attr_value = rest[:end_idx]
                        else:
                            attr_value = rest.strip()
                    else:
                        idx = attr_line.find(')=')
                        if idx > 0:
                            rest = attr_line[idx+2:]
                            attr_value = rest.strip()
                    attr_name = 'name'
                
                if attr_name and attr_value is not None:
                    element_stack[-1]['attrs'][attr_name] = attr_value
                elif attr_name and attr_value is None:
                    pass
                else:
                    app_logger.debug(f"未识别的属性: {stripped}")
            
            elif stripped.startswith('#') and element_stack:
                if element_stack[-1]['name'] == 'path':
                    element_stack[-1]['attrs']['fillColor'] = stripped
        
        for elem in result.get('elements', []):
            self._check_unrecognized(elem)
        
        return result
    
    def _check_unrecognized(self, elem, path=''):
        """递归检查未识别的元素和属性"""
        name = elem.get('name', '')
        attrs = elem.get('attrs', {})
        current_path = f"{path}/{name}" if path else name
        
        recognized_elements = {
            'vector', 'path', 'group', 'clip-path', 'adaptive-icon', 'background', 
            'foreground', 'bitmap', 'layer-list', 'item', 'selector', 'gradient',
            'inset', 'aapt:attr', 'ripple', 'shape', 'corners', 'solid', 'stroke',
            'padding', 'size', 'gradient-item', 'monochrome'
        }
        
        recognized_attrs = {
            'height', 'width', 'viewportWidth', 'viewportHeight',
            'fillColor', 'pathData', 'strokeColor', 'strokeWidth', 'fillType', 'fillAlpha',
            'translateX', 'translateY', 'scaleX', 'scaleY', 'rotation', 'pivotX', 'pivotY',
            'drawable', 'src', 'color', 'offset', 'startX', 'startY', 'endX', 'endY',
            'startColor', 'endColor', 'angle', 'type', 'inset', 'insetLeft', 'insetTop',
            'insetRight', 'insetBottom', 'radius', 'left', 'top', 'right', 'bottom',
            'strokeAlpha', 'strokeWidth', 'dashWidth', 'dashGap', 'trimPathStart', 
            'trimPathEnd', 'trimPathOffset', 'strokeLineCap', 'strokeLineJoin', 'strokeMiterLimit',
            'name', 'centerX', 'centerY', 'gradientRadius'
        }
        
        if name and name not in recognized_elements:
            app_logger.debug(f"未识别的元素: {current_path}")
        
        for attr_name in attrs:
            if attr_name not in recognized_attrs:
                app_logger.debug(f"未识别的属性: {current_path}@{attr_name} = {attrs[attr_name]}")
        
        for child in elem.get('children', []):
            self._check_unrecognized(child, current_path)
    
    def _load_layer_from_element(self, element, size=432, layer_name='', depth=0):
        """从adaptive-icon的子元素加载图层
        
        参数:
            element: foreground或background元素
            size: 图标尺寸
            layer_name: 图层名称（用于日志）
            depth: 递归深度（防止无限循环）
        
        返回:
            PIL.Image对象或None
        """
        if depth > MAX_RECURSION_DEPTH:
            app_logger.warning(f"资源引用递归深度超过限制({depth}层): {layer_name}")
            return None
        
        try:
            attrs = element.get('attrs', {})
            drawable_id = attrs.get('drawable')
            
            if drawable_id:
                app_logger.debug(f"{layer_name} drawable_id: {drawable_id}")
                if not drawable_id.startswith('0x'):
                    drawable_id = '0x' + drawable_id.lstrip('@')
                result = self._load_layer_image(drawable_id, size, depth + 1)
                app_logger.debug(f"{layer_name} 加载结果: {'成功' if result else '失败'}")
                return result
            
            for sub_child in element.get('children', []):
                sub_name = sub_child.get('name', '')
                
                try:
                    if sub_name == 'vector':
                        app_logger.debug(f"{layer_name} 包含内嵌vector元素")
                        data = self._render_vector_icon(sub_child, size)
                        if data:
                            img = Image.open(BytesIO(data))
                            if img.mode != 'RGBA':
                                img = img.convert('RGBA')
                            app_logger.debug(f"{layer_name} 内嵌vector渲染成功")
                            return img
                    
                    elif sub_name == 'bitmap':
                        app_logger.debug(f"{layer_name} 包含内嵌bitmap元素")
                        bitmap_attrs = sub_child.get('attrs', {})
                        src = bitmap_attrs.get('src')
                        if src:
                            if not src.startswith('0x'):
                                src = '0x' + src.lstrip('@')
                            result = self._load_layer_image(src, size, depth + 1)
                            if result:
                                app_logger.debug(f"{layer_name} bitmap加载成功")
                                return result
                    
                    elif sub_name == 'layer-list':
                        app_logger.debug(f"{layer_name} 包含内嵌layer-list元素")
                        data = self._render_layer_list_icon(sub_child, size)
                        if data:
                            img = Image.open(BytesIO(data))
                            if img.mode != 'RGBA':
                                img = img.convert('RGBA')
                            app_logger.debug(f"{layer_name} 内嵌layer-list渲染成功")
                            return img
                    
                    elif sub_name == 'selector':
                        app_logger.debug(f"{layer_name} 包含内嵌selector元素")
                        data = self._render_selector_icon(sub_child, size)
                        if data:
                            img = Image.open(BytesIO(data))
                            if img.mode != 'RGBA':
                                img = img.convert('RGBA')
                            app_logger.debug(f"{layer_name} 内嵌selector渲染成功")
                            return img
                    
                    elif sub_name == 'shape':
                        app_logger.debug(f"{layer_name} 包含内嵌shape元素")
                        data = self._render_shape_icon(sub_child, size)
                        if data:
                            img = Image.open(BytesIO(data))
                            if img.mode != 'RGBA':
                                img = img.convert('RGBA')
                            app_logger.debug(f"{layer_name} 内嵌shape渲染成功")
                            return img
                    
                    elif sub_name == 'inset':
                        app_logger.debug(f"{layer_name} 包含内嵌inset元素")
                        data = self._render_inset_icon(sub_child, size)
                        if data:
                            img = Image.open(BytesIO(data))
                            if img.mode != 'RGBA':
                                img = img.convert('RGBA')
                            app_logger.debug(f"{layer_name} 内嵌inset渲染成功")
                            return img
                    
                    elif sub_name == 'aapt:attr':
                        app_logger.debug(f"{layer_name} 包含aapt:attr元素")
                        for nested_child in sub_child.get('children', []):
                            result = self._load_layer_from_element(nested_child, size, layer_name, depth + 1)
                            if result:
                                return result
                    
                    elif sub_name:
                        app_logger.warning(f"{layer_name} 未知的子元素: {sub_name}")
                
                except Exception as e:
                    app_logger.warning(f"{layer_name} 处理子元素 {sub_name} 失败: {e}")
                    continue
            
            return None
        
        except Exception as e:
            app_logger.error(f"加载图层失败 ({layer_name}): {e}")
            import traceback
            app_logger.error(traceback.format_exc())
            return None
    
    def _render_adaptive_icon(self, element, size=432):
        """渲染自适应图标
        
        Android AdaptiveIcon 规范 (基于 Android 16 源码):
        - MASK_SIZE = 100f (遮罩路径尺寸)
        - EXTRA_INSET_PERCENTAGE = 1/4 (额外边距 25%)
        - DEFAULT_VIEW_PORT_SCALE = 2/3 (视口缩放比例)
        - 图层尺寸为视口的 1.5 倍
        - 使用圆形遮罩裁剪
        - 可见区域为中心 2/3 (66.7%)
        """
       
        try:
            app_logger.debug("开始渲染自适应图标")
            
            # Android AdaptiveIcon 关键常量
            EXTRA_INSET_PERCENTAGE = 1 / 4
            DEFAULT_VIEW_PORT_SCALE = 1 / (1 + 2 * EXTRA_INSET_PERCENTAGE)  # = 2/3
            
            # 图层尺寸 = 视口尺寸 / DEFAULT_VIEW_PORT_SCALE = 视口尺寸 * 1.5
            layer_size = int(size / DEFAULT_VIEW_PORT_SCALE)
            
            app_logger.debug(f"视口尺寸: {size}, 图层尺寸: {layer_size}")
            
            foreground = None
            background = None
            
            # 检查 adaptive-icon 元素本身的 drawable 属性
            # 根据 Android 源码，这个属性应该作为背景图层使用
            element_attrs = element.get('attrs', {})
            element_drawable = element_attrs.get('drawable')
            if element_drawable:
                app_logger.debug(f"adaptive-icon 元素有 drawable 属性: {element_drawable}")
                if not element_drawable.startswith('0x'):
                    element_drawable = '0x' + element_drawable.lstrip('@')
                background = self._load_layer_image(element_drawable, layer_size, 0)
                if background:
                    app_logger.debug("从 adaptive-icon 的 drawable 属性加载背景成功")
            
            for child in element.get('children', []):
                child_name = child.get('name', '')
                app_logger.debug(f"发现子元素: {child_name}")
                
                if child_name == 'foreground':
                    foreground = self._load_layer_from_element(child, layer_size, 'foreground')
                
                elif child_name == 'background':
                    # 如果子元素有 background，覆盖之前的背景
                    bg = self._load_layer_from_element(child, layer_size, 'background')
                    if bg:
                        background = bg
                        
                elif child_name == 'monochrome':
                    app_logger.debug("monochrome 元素用于主题化图标，跳过解析")
                
                elif child_name:
                    app_logger.warning(f"未知的adaptive-icon子元素: {child_name}")
            
            if foreground is None and background is None:
                app_logger.warning("前景和背景都加载失败")
                return None
            
            if foreground is None:
                app_logger.warning("foreground 前景图层缺失或加载失败")
            if background is None:
                app_logger.warning("background 背景图层缺失或加载失败")

            # 创建图层位图 (1.5倍尺寸)
            layer_img = Image.new('RGBA', (layer_size, layer_size), (0, 0, 0, 0))
            
            if background:
                bg_resized = background.resize((layer_size, layer_size), Image.LANCZOS)
                layer_img = Image.alpha_composite(layer_img, bg_resized.convert('RGBA'))
            
            if foreground:
                fg_resized = foreground.resize((layer_size, layer_size), Image.LANCZOS)
                layer_img = Image.alpha_composite(layer_img, fg_resized.convert('RGBA'))
            
            # 从中心裁剪到视口尺寸
            offset = (layer_size - size) // 2
            cropped = layer_img.crop((offset, offset, offset + size, offset + size))
            
            # 遮罩处理统一在 _render_xml_icon 中通过 _apply_icon_mask 完成
            # 这里直接返回裁剪后的图像数据
            output = BytesIO()
            cropped.save(output, format='PNG')
            app_logger.debug(f"成功渲染自适应图标图层")
            return output.getvalue()
        
        except Exception as e:
            app_logger.error(f"渲染失败: {e}")
            return None
    
    def _create_icon_mask(self, size):
        """创建图标遮罩
        
        使用 Android AOSP 默认的 config_icon_mask 路径数据，通过 PyQt5 QPainterPath 实现高精度贝塞尔曲线渲染。
        
        遮罩路径 (100x100 坐标系):
        M50,0L92,0C96.42,0 100,4.58 100 8L100,92C100,96.42 96.42,100 92,100L8,100C4.58,100 0,96.42 0,92L0,8C0,4.42 4.42,0 8,0L50,0Z
        
        这是一个使用三次贝塞尔曲线绘制的圆角矩形（Squircle），用于：
        1. 自适应图标（adaptive-icon）的遮罩裁剪
        2. 所有 XML 类型图标的统一遮罩处理
        
        参数:
            size: 输出遮罩尺寸（像素）
            
        返回:
            PIL.Image: 灰度遮罩图像，255 表示可见区域，0 表示透明区域
        """
        from PyQt5.QtGui import QImage, QPainter, QPainterPath
        
        scale = size / 100.0
        
        path = QPainterPath()
        
        path.moveTo(50 * scale, 0)
        path.lineTo(92 * scale, 0)
        path.cubicTo(96.42 * scale, 0,
                     100 * scale, 4.58 * scale,
                     100 * scale, 8 * scale)
        
        path.lineTo(100 * scale, 92 * scale)
        path.cubicTo(100 * scale, 96.42 * scale,
                     96.42 * scale, 100 * scale,
                     92 * scale, 100 * scale)
        
        path.lineTo(8 * scale, 100 * scale)
        path.cubicTo(4.58 * scale, 100 * scale,
                     0, 96.42 * scale,
                     0, 92 * scale)
        
        path.lineTo(0, 8 * scale)
        path.cubicTo(0, 4.42 * scale,
                     4.42 * scale, 0,
                     8 * scale, 0)
        
        path.lineTo(50 * scale, 0)
        path.closeSubpath()
        
        q_image = QImage(size, size, QImage.Format_Grayscale8)
        q_image.fill(Qt.white)
        
        painter = QPainter(q_image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillPath(path, Qt.black)
        painter.end()
        
        ptr = q_image.bits()
        ptr.setsize(size * size)
        bytes_data = bytes(ptr)
        
        mask = Image.frombytes('L', (size, size), bytes_data)
        
        mask = mask.point(lambda x: 255 - x)
        
        return mask

    def _get_android_system_color(self, resource_id):
        """
        获取 Android 系统内置颜色值
        
        支持两种查找方式：
        1. 根据资源ID查找：传入十六进制字符串（如 "0x01060005"）
        2. 根据资源名称查找：传入 "color/颜色名" 格式（如 "color/secondary_text_dark"）
        
        参数:
            resource_id: 资源ID字符串或资源名称字符串
        
        返回:
            tuple: (颜色值, 颜色名称) 或 None
        """
        if not isinstance(resource_id, str):
            return None
        
        if resource_id.startswith('0x'):
            try:
                res_id_int = int(resource_id, 16)
                return ANDROID_SYSTEM_COLORS.get(res_id_int)
            except ValueError:
                return None
        elif resource_id.startswith('@0x'):
            try:
                res_id_int = int(resource_id[1:], 16)
                return ANDROID_SYSTEM_COLORS.get(res_id_int)
            except ValueError:
                return None
        elif resource_id.startswith('color/'):
            color_name = resource_id[6:]
            return ANDROID_SYSTEM_COLORS_BY_NAME.get(color_name)
        elif '/' in resource_id:
            parts = resource_id.split('/')
            if len(parts) == 2 and parts[0] == 'color':
                return ANDROID_SYSTEM_COLORS_BY_NAME.get(parts[1])
            return None
        
        return None

    def _load_layer_image(self, resource_id, size=432, depth=0):
        """加载图层图像
        
        参数:
            resource_id: 资源ID
            size: 图标尺寸
            depth: 递归深度（防止无限循环）
        """
        if depth > MAX_RECURSION_DEPTH:
            app_logger.warning(f"资源引用递归深度超过限制({depth}层): {resource_id}")
            return None
        
        try:
            original_resource_id = resource_id[1:] if resource_id.startswith('@') else resource_id
            app_logger.debug(f"加载资源: @{original_resource_id}")
            
            # 检查是否是 Android 系统内置颜色资源
            system_color = self._get_android_system_color(resource_id)
            if system_color:
                color_hex, color_name = system_color
                color = self._parse_color(color_hex)
                app_logger.debug(f"资源类型: color, 名称: {color_name} ({color_hex})")
                return Image.new('RGBA', (size, size), color)
            
            # 根据资源ID查找资源信息
            res_info = self.get_resource_by_id(resource_id)
            if not res_info:
                app_logger.warning(f"未找到资源: @{original_resource_id}")
                return None
            
            res_type = res_info.get('type', '')
            res_name = res_info.get('name', '')
            app_logger.debug(f"资源类型: {res_type}, 名称: {res_name}")
            
            if res_type == 'color':
                color_img = self._load_color_resource(resource_id, size)
                if color_img:
                    return color_img
            
            configs = res_info.get('configs', [])
            app_logger.debug(f"找到 {len(configs)} 个配置")
            
            sorted_configs = self._sort_by_density(configs)
            
            for config in sorted_configs:
                reference = config.get('reference')
                if reference:
                    app_logger.debug(f"发现引用: {reference}")
                    ref_res_info = self.get_resource_by_name(reference)
                    if ref_res_info:
                        ref_configs = ref_res_info.get('configs', [])
                        for ref_config in ref_configs:
                            ref_path = ref_config.get('path', '')
                            if ref_path and ref_path.endswith('.xml'):
                                icon_data = self._render_xml_icon(ref_path, size)
                                if icon_data:
                                    img = Image.open(BytesIO(icon_data))
                                    if img.mode != 'RGBA':
                                        img = img.convert('RGBA')
                                    return img
                            elif ref_path:
                                zf = self.get_zip_file()
                                if ref_path in zf.namelist():
                                    data = zf.read(ref_path)
                                    img = Image.open(BytesIO(data))
                                    if img.mode != 'RGBA':
                                        img = img.convert('RGBA')
                                    return img.resize((size, size), Image.LANCZOS)
            
            for config in sorted_configs:
                path = config.get('path', '')
                config_name = config.get('config', '')
                if path and not path.endswith('.xml'):
                    app_logger.debug(f"尝试加载图片: {path} (config={config_name})")
                    try:
                        zf = self.get_zip_file()
                        if path in zf.namelist():
                            data = zf.read(path)
                            img = Image.open(BytesIO(data))
                            if img.mode != 'RGBA':
                                img = img.convert('RGBA')
                            app_logger.debug(f"成功加载图片: {path}")
                            return img.resize((size, size), Image.LANCZOS)
                    except Exception as e:
                        app_logger.debug(f"加载图片失败: {path}, 错误: {e}")
            
            for config in sorted_configs:
                path = config.get('path', '')
                if path and path.endswith('.xml'):
                    app_logger.debug(f"尝试渲染XML: {path}")
                    icon_data = self._render_xml_icon(path, size)
                    if icon_data:
                        img = Image.open(BytesIO(icon_data))
                        if img.mode != 'RGBA':
                            img = img.convert('RGBA')
                        app_logger.debug(f"成功渲染XML: {path}")
                        return img
            
            app_logger.warning(f"所有加载方式都失败: @{original_resource_id}")
            return None
        
        except Exception as e:
            app_logger.error(f"加载失败: {e}")
            return None
    
    def _load_color_resource(self, resource_id, size=432):
        """
        加载color类型资源，创建纯色图像
        
        参数:
            resource_id: 资源ID
            size: 输出尺寸
        
        返回:
            PIL.Image: 纯色图像，或None
        """
        try:
            app_logger.debug(f"加载颜色资源: {resource_id}")
            
            color_value = self._get_color_resource_value(resource_id)
            if color_value:
                color = self._parse_color(color_value)
                if color:
                    app_logger.debug(f"解析颜色值: {color_value} -> {color}")
                    return Image.new('RGBA', (size, size), color)
            
            app_logger.warning(f"无法解析出颜色值，使用默认白色背景")
            return Image.new('RGBA', (size, size), (255, 255, 255, 255))
        
        except Exception as e:
            app_logger.error(f"加载失败: {e}")
            return None
    
    def _render_vector_icon(self, element, size=432):
        """
        渲染矢量图标（使用SVG方式实现）
        
        参数:
            element: vector元素
            size: 输出尺寸
        
        返回:
            bytes: PNG图像数据，或None
        """
        try:
            app_logger.debug("开始渲染矢量图标")
            app_logger.debug(f"  输出尺寸: {size} x {size}")
            
            result = self._render_vector_icon_with_svg(element, size)
            
            if result:
                # 输出PNG数据的详细信息
                app_logger.debug("矢量图标渲染成功")
                app_logger.debug(f"  PNG数据大小: {len(result)} 字节 ({len(result)/1024:.2f} KB)")
                
                # 尝试解析PNG图像获取实际尺寸
                try:
                    img = Image.open(BytesIO(result))
                    app_logger.debug(f"  PNG图像尺寸: {img.size[0]} x {img.size[1]} 像素")
                    app_logger.debug(f"  PNG图像模式: {img.mode}")
                except Exception as e:
                    app_logger.debug(f"  无法解析PNG图像信息: {e}")
            else:
                app_logger.warning("矢量图标渲染失败")
            
            return result
            
        except Exception as e:
            app_logger.error(f"矢量图标渲染异常: {e}")
            import traceback
            app_logger.error(traceback.format_exc())
            return None
    def _convert_vector_to_svg(self, vector_element):
        """
        将vector元素转换为完整的SVG字符串
        
        参数:
            vector_element: 由_parse_xmltree_output解析出的vector元素
            
        返回:
            str: 完整的SVG字符串
        """
        try:
            app_logger.debug("开始转换vector元素为SVG")
            
            attrs = vector_element.get('attrs', {})
            
            def parse_float(value, default=None):
                """解析数值，带默认值，支持科学计数法
                
                参数:
                    value: 要解析的值
                    default: 默认值，当解析失败时返回
                    
                返回:
                    解析后的浮点数，或default值
                """
                if value is None:
                    return default
                if isinstance(value, (int, float)):
                    return float(value)
                value = str(value).strip('"').strip("'")
                match = re.match(r'^(-?\d+\.?\d*([eE][+-]?\d+)?)', value)
                if match:
                    return float(match.group(1))
                return default
            
            def parse_alpha_value(value, default=1.0):
                """解析透明度属性值，支持浮点数和资源引用
                
                参数:
                    value: 属性值，可能是浮点数或资源引用(如 @0x7f07008f)
                    default: 默认值
                    
                返回:
                    float: 透明度值 (0.0-1.0)
                """
                if value is None:
                    return default
                if isinstance(value, (int, float)):
                    return float(value)
                value_str = str(value).strip()
                
                # 检查是否是资源引用
                if value_str.startswith('@0x') or value_str.startswith('0x'):
                    # 尝试解析资源引用
                    res_id = value_str.lstrip('@')
                    alpha_value = self._get_dimen_resource_value(res_id)
                    if alpha_value is not None:
                        try:
                            return float(alpha_value)
                        except:
                            pass
                    # 尝试解析颜色资源（alpha 可能存储在颜色资源中）
                    color_value = self._get_color_resource_value(res_id)
                    if color_value:
                        # 如果是颜色值，提取 alpha 分量
                        if isinstance(color_value, str) and color_value.startswith('#'):
                            if len(color_value) == 9:  # #AARRGGBB
                                alpha_hex = color_value[1:3]
                                return int(alpha_hex, 16) / 255.0
                    app_logger.warning(f"无法解析透明度资源引用: {value_str}，使用默认值 {default}")
                    return default
                
                # 尝试解析浮点数
                match = re.match(r'^(-?\d+\.?\d*)', value_str)
                if match:
                    return float(match.group(1))
                return default
            
            # 渐变定义列表和计数器
            gradient_defs = []
            gradient_counter = [0]  # 使用列表以便在嵌套函数中修改
            
            def get_gradient_id():
                """生成唯一的渐变ID"""
                gradient_counter[0] += 1
                return f'gradient-{gradient_counter[0]}'
            
            def apply_alpha_to_color(color_str, alpha):
                """
                将alpha透明度应用到颜色值上
                
                参数:
                    color_str: 颜色字符串，格式如 #RRGGBB 或 #AARRGGBB
                    alpha: 透明度值 (0.0-1.0)
                    
                返回:
                    str: 带透明度的颜色字符串 #AARRGGBB
                """
                if not color_str or not color_str.startswith('#'):
                    return color_str
                
                # 将alpha (0-1) 转换为十六进制 (00-FF)
                alpha_hex = format(int(alpha * 255), '02X')
                
                if len(color_str) == 9:
                    # #AARRGGBB 格式，需要替换原有的alpha
                    return f'#{alpha_hex}{color_str[3:]}'
                elif len(color_str) == 7:
                    # #RRGGBB 格式，添加alpha前缀
                    return f'#{alpha_hex}{color_str[1:]}'
                elif len(color_str) == 5:
                    # #ARGB 格式，扩展并替换alpha
                    return f'#{alpha_hex}{color_str[2]}{color_str[2]}{color_str[3]}{color_str[3]}{color_str[4]}{color_str[4]}'
                elif len(color_str) == 4:
                    # #RGB 格式，扩展并添加alpha
                    return f'#{alpha_hex}{color_str[1]}{color_str[1]}{color_str[2]}{color_str[2]}{color_str[3]}{color_str[3]}'
                
                return color_str
            
            def process_color(color_value, alpha=None):
                """
                处理颜色值，解析资源引用并转换为SVG兼容格式
                
                参数:
                    color_value: 颜色值或资源引用
                    alpha: 可选的透明度值 (0.0-1.0)
                    
                返回:
                    tuple: (颜色字符串, alpha值, 是否为渐变)
                    颜色字符串格式: '#RRGGBB' (不带alpha)
                    alpha值: 0.0-1.0，用于 fill-opacity 或 stroke-opacity
                """
                if color_value is None:
                    return (None, 1.0, False)
                
                if isinstance(color_value, str):
                    if color_value.startswith('@'):
                        app_logger.debug(f"解析颜色资源引用: {color_value}")
                        resolved_color = self._get_color_resource_value(color_value)
                        
                        # 检查是否为渐变资源
                        if isinstance(resolved_color, dict):
                            gradient_type = resolved_color.get('type')
                            if gradient_type in ('linear_gradient', 'radial_gradient'):
                                app_logger.debug(f"检测到渐变资源: {gradient_type}")
                                gradient_id = generate_svg_gradient(resolved_color, alpha)
                                if gradient_id:
                                    return (f'url(#{gradient_id})', 1.0, True)
                                else:
                                    app_logger.warning(f"无法生成SVG渐变定义: {color_value}")
                                    return (None, 1.0, False)
                        
                        # 普通颜色资源
                        if resolved_color and isinstance(resolved_color, str) and resolved_color.startswith('#'):
                            color_value = resolved_color
                        else:
                            app_logger.warning(f"无法解析颜色资源引用: {color_value}")
                            return (None, 1.0, False)
                
                if isinstance(color_value, str) and color_value.startswith('#'):
                    color_str = color_value
                    color_alpha = 1.0
                    
                    # 解析颜色和alpha
                    if len(color_str) == 9:
                        # #AARRGGBB 格式 (Android格式)
                        # 提取alpha和颜色
                        a_hex = color_str[1:3]
                        color_alpha = int(a_hex, 16) / 255.0
                        color_hex = f'#{color_str[3:]}'  # #RRGGBB
                    elif len(color_str) == 7:
                        # #RRGGBB 格式
                        color_hex = color_str
                    elif len(color_str) == 5:
                        # #ARGB 格式
                        a_hex = color_str[1]
                        color_alpha = int(a_hex, 16) / 15.0
                        color_hex = f'#{color_str[2]}{color_str[2]}{color_str[3]}{color_str[3]}{color_str[4]}{color_str[4]}'
                    elif len(color_str) == 4:
                        # #RGB 格式
                        color_hex = f'#{color_str[1]}{color_str[1]}{color_str[2]}{color_str[2]}{color_str[3]}{color_str[3]}'
                    else:
                        return (None, 1.0, False)
                    
                    # 应用额外的透明度参数 (Android源码算法: applyAlpha)
                    # 最终alpha = 颜色alpha * fillAlpha/strokeAlpha
                    original_color_alpha = color_alpha
                    if alpha is not None and 0 <= alpha <= 1:
                        color_alpha = color_alpha * alpha
                    
                    app_logger.debug(f"处理颜色: {color_str} -> color={color_hex}, alpha={color_alpha:.6g} (颜色alpha={original_color_alpha:.6g} × 属性alpha={alpha:.6g})")
                    
                    return (color_hex, color_alpha, False)
                
                return (None, 1.0, False)
            
            def generate_svg_gradient(gradient_info, alpha=None):
                """
                根据渐变信息生成SVG渐变定义
                
                参数:
                    gradient_info: 渐变信息字典
                    alpha: 可选的全局透明度
                    
                返回:
                    str: 渐变ID，或None
                """
                try:
                    gradient_type = gradient_info.get('type')
                    items = gradient_info.get('items', [])
                    
                    if not items:
                        return None
                    
                    gradient_id = get_gradient_id()
                    gradient_lines = []
                    
                    def convert_color_to_hex(color_value):
                        """
                        将颜色值转换为SVG兼容的十六进制字符串
                        
                        SVG颜色格式: #RRGGBB 或 #RRGGBBAA (alpha在最后)
                        返回: (颜色字符串, alpha值)
                        """
                        if color_value is None:
                            return ('#000000', 1.0)
                        
                        # 如果是元组 (r, g, b, a)
                        if isinstance(color_value, tuple):
                            if len(color_value) >= 4:
                                r, g, b, a = color_value[:4]
                                # SVG使用 #RRGGBB 格式，alpha单独处理
                                return (f'#{r:02X}{g:02X}{b:02X}', a / 255.0)
                            elif len(color_value) == 3:
                                r, g, b = color_value[:3]
                                return (f'#{r:02X}{g:02X}{b:02X}', 1.0)
                        
                        # 如果已经是字符串
                        if isinstance(color_value, str):
                            if color_value.startswith('#'):
                                # 处理不同格式的颜色字符串
                                if len(color_value) == 9:
                                    # #AARRGGBB 格式 (Android格式) -> 转换为 #RRGGBB
                                    a = int(color_value[1:3], 16) / 255.0
                                    return (f'#{color_value[3:]}', a)
                                elif len(color_value) == 7:
                                    # #RRGGBB 格式
                                    return (color_value, 1.0)
                                elif len(color_value) == 5:
                                    # #ARGB 格式 -> #RRGGBB
                                    a = int(color_value[1], 16) / 15.0
                                    return (f'#{color_value[2]}{color_value[2]}{color_value[3]}{color_value[3]}{color_value[4]}{color_value[4]}', a)
                                elif len(color_value) == 4:
                                    # #RGB 格式 -> #RRGGBB
                                    return (f'#{color_value[1]}{color_value[1]}{color_value[2]}{color_value[2]}{color_value[3]}{color_value[3]}', 1.0)
                        
                        return ('#000000', 1.0)
                    
                    if gradient_type == 'linear_gradient':
                        # 线性渐变
                        start_x = gradient_info.get('startX')
                        start_y = gradient_info.get('startY')
                        end_x = gradient_info.get('endX')
                        end_y = gradient_info.get('endY')
                        is_normalized = gradient_info.get('is_normalized', True)
                        
                        if start_x is None or start_y is None or end_x is None or end_y is None:
                            app_logger.warning(f"线性渐变缺少必要的坐标属性: startX={start_x}, startY={start_y}, endX={end_x}, endY={end_y}")
                            return None
                        
                        # 根据坐标类型选择gradientUnits
                        # is_normalized=False: 绝对像素坐标 -> userSpaceOnUse
                        # is_normalized=True: 归一化坐标(0-1) -> objectBoundingBox
                        gradient_units = "objectBoundingBox" if is_normalized else "userSpaceOnUse"
                        
                        gradient_lines.append(f'<linearGradient id="{gradient_id}" x1="{start_x}" y1="{start_y}" x2="{end_x}" y2="{end_y}" gradientUnits="{gradient_units}">')
                        
                        for item in items:
                            color = item.get('color', '#000000')
                            offset = item.get('offset', 0)
                            
                            # 转换颜色格式，返回颜色和alpha
                            color_hex, color_alpha = convert_color_to_hex(color)
                            
                            # 应用额外的透明度（如fillAlpha/strokeAlpha）
                            final_alpha = color_alpha
                            if alpha is not None and 0 <= alpha <= 1:
                                final_alpha = color_alpha * alpha
                                app_logger.debug(f"渐变stop alpha: {final_alpha:.6g} (颜色alpha={color_alpha:.6g} × 属性alpha={alpha:.6g})")
                            
                            # 生成stop元素，始终显式输出stop-opacity属性
                            gradient_lines.append(f'  <stop offset="{offset}" stop-color="{color_hex}" stop-opacity="{final_alpha:.6g}"/>')
                        
                        gradient_lines.append('</linearGradient>')
                        
                    elif gradient_type == 'radial_gradient':
                        # 径向渐变
                        center_x = gradient_info.get('centerX')
                        center_y = gradient_info.get('centerY')
                        radius = gradient_info.get('gradientRadius')
                        is_normalized = gradient_info.get('is_normalized', True)
                        
                        if center_x is None or center_y is None or radius is None:
                            app_logger.warning(f"径向渐变缺少必要的属性: centerX={center_x}, centerY={center_y}, gradientRadius={radius}")
                            return None
                        
                        # 根据坐标类型选择gradientUnits
                        # is_normalized=False: 绝对像素坐标 -> userSpaceOnUse
                        # is_normalized=True: 归一化坐标(0-1) -> objectBoundingBox
                        gradient_units = "objectBoundingBox" if is_normalized else "userSpaceOnUse"
                        
                        gradient_lines.append(f'<radialGradient id="{gradient_id}" cx="{center_x}" cy="{center_y}" r="{radius}" gradientUnits="{gradient_units}">')
                        
                        for item in items:
                            color = item.get('color', '#000000')
                            offset = item.get('offset', 0)
                            
                            # 转换颜色格式，返回颜色和alpha
                            color_hex, color_alpha = convert_color_to_hex(color)
                            
                            # 应用额外的透明度（如fillAlpha/strokeAlpha）
                            final_alpha = color_alpha
                            if alpha is not None and 0 <= alpha <= 1:
                                final_alpha = color_alpha * alpha
                                app_logger.debug(f"渐变stop alpha: {final_alpha:.6g} (颜色alpha={color_alpha:.6g} × 属性alpha={alpha:.6g})")
                            
                            # 生成stop元素，始终显式输出stop-opacity属性
                            gradient_lines.append(f'  <stop offset="{offset}" stop-color="{color_hex}" stop-opacity="{final_alpha:.6g}"/>')
                        
                        gradient_lines.append('</radialGradient>')
                    
                    else:
                        app_logger.warning(f"不支持的渐变类型: {gradient_type}")
                        return None
                    
                    # 将渐变定义添加到列表
                    gradient_defs.append('\n'.join(gradient_lines))
                    app_logger.debug(f"生成SVG渐变定义: {gradient_id}, 类型: {gradient_type}")
                    
                    return gradient_id
                    
                except Exception as e:
                    app_logger.error(f"生成SVG渐变定义失败: {e}")
                    return None
            
            def convert_element(element, indent=0, clip_path_id=None):
                """
                递归转换单个元素为SVG字符串
                
                参数:
                    element: 要转换的元素
                    indent: 缩进级别
                    clip_path_id: 当前应用的clip-path ID
                    
                返回:
                    str: SVG字符串
                """
                element_name = element.get('name', '')
                element_attrs = element.get('attrs', {})
                children = element.get('children', [])
                
                result = []
                indent_str = '  ' * indent
                
                if element_name == 'group':
                    app_logger.debug(f"处理group元素")
                    transform_parts = []
                    
                    rotation = parse_float(element_attrs.get('rotation'), 0)
                    scale_x = parse_float(element_attrs.get('scaleX'), 1)
                    scale_y = parse_float(element_attrs.get('scaleY'), 1)
                    translate_x = parse_float(element_attrs.get('translateX'), 0)
                    translate_y = parse_float(element_attrs.get('translateY'), 0)
                    pivot_x = parse_float(element_attrs.get('pivotX'), 0)
                    pivot_y = parse_float(element_attrs.get('pivotY'), 0)
                    
                    has_transform = False
                    if rotation != 0 or scale_x != 1 or scale_y != 1 or translate_x != 0 or translate_y != 0:
                        has_transform = True
                        # Android Skia post* 方法是后乘，变换顺序：T1 -> S -> R -> T2
                        # 应用到点时执行顺序（从右到左）：T2 -> R -> S -> T1
                        # SVG transform 从左到右执行，所以要反过来写：T2 -> R -> S -> T1
                        # 这样 SVG 执行顺序才是：T1 -> S -> R -> T2，与 Android 一致
                        transform_parts.append(f'translate({pivot_x + translate_x:.6g}, {pivot_y + translate_y:.6g})')
                        if rotation != 0:
                            transform_parts.append(f'rotate({rotation:.6g})')
                        if scale_x != 1 or scale_y != 1:
                            transform_parts.append(f'scale({scale_x:.6g}, {scale_y:.6g})')
                        transform_parts.append(f'translate({-pivot_x:.6g}, {-pivot_y:.6g})')
                    
                    group_attrs = []
                    if has_transform:
                        group_attrs.append(f'transform="{" ".join(transform_parts)}"')
                    if clip_path_id:
                        group_attrs.append(f'clip-path="url(#{clip_path_id})"')
                    
                    if group_attrs:
                        result.append(f'{indent_str}<g {" ".join(group_attrs)}>')
                    else:
                        result.append(f'{indent_str}<g>')
                    
                    # 处理 Group 的子元素
                    # 根据 Android 源码，clip-path 裁剪的是同 Group 中的后续兄弟元素
                    # 关键机制：SkAutoCanvasRestore 确保嵌套 Group 的 clip 不会影响父 Group
                    # 所以需要记录当前 Group 的 clip_id，嵌套 Group 内部的 clip-path 不会更新它
                    group_clip_id = clip_path_id  # 父 Group 传入的 clip_id
                    current_clip_id = None        # 当前 Group 内部设置的 clip_id
                    
                    for child in children:
                        child_name = child.get('name', '')
                        
                        if child_name == 'clip-path':
                            # 处理 clip-path 元素：生成定义并更新 current_clip_id
                            child_attrs = child.get('attrs', {})
                            path_data = child_attrs.get('pathData')
                            if path_data:
                                new_clip_id = f'clip-{id(child)}'
                                result.append(f'{indent_str}  <defs>')
                                result.append(f'{indent_str}    <clipPath id="{new_clip_id}">')
                                result.append(f'{indent_str}      <path d="{path_data}"/>')
                                result.append(f'{indent_str}    </clipPath>')
                                result.append(f'{indent_str}  </defs>')
                                current_clip_id = new_clip_id
                                app_logger.debug(f"生成clip-path定义: {new_clip_id}")
                        elif child_name == 'group':
                            # 嵌套 Group：使用当前 Group 的 current_clip_id（如果有）
                            # 嵌套 Group 本身是当前 clip-path 的兄弟元素，所以应该被裁剪
                            # 但嵌套 Group 内部的 clip-path 不会影响父 Group 的 current_clip_id
                            child_svg = convert_element(child, indent + 1, current_clip_id or group_clip_id)
                            if child_svg:
                                result.append(child_svg)
                        else:
                            # 其他元素（如 path）：使用当前的 clip_id（如果有）
                            # 注意：这里使用 current_clip_id or group_clip_id，不受嵌套 Group 影响
                            child_svg = convert_element(child, indent + 1, current_clip_id or group_clip_id)
                            if child_svg:
                                result.append(child_svg)
                    
                    result.append(f'{indent_str}</g>')
                
                elif element_name == 'path':
                    app_logger.debug(f"处理path元素")
                    path_attrs = []
                    
                    path_data = element_attrs.get('pathData')
                    if path_data:
                        path_attrs.append(f'd="{path_data}"')
                    
                    # 解析 fillAlpha 属性（默认值为 1.0）
                    # 支持浮点数和资源引用(如 @0x7f07008f)
                    fill_alpha_attr = parse_alpha_value(element_attrs.get('fillAlpha'), 1.0)
                    if fill_alpha_attr is not None and (fill_alpha_attr < 0 or fill_alpha_attr > 1):
                        fill_alpha_attr = 1.0
                    
                    # 解析 strokeAlpha 属性（默认值为 1.0）
                    # 支持浮点数和资源引用(如 @0x7f07008f)
                    stroke_alpha_attr = parse_alpha_value(element_attrs.get('strokeAlpha'), 1.0)
                    if stroke_alpha_attr is not None and (stroke_alpha_attr < 0 or stroke_alpha_attr > 1):
                        stroke_alpha_attr = 1.0
                    
                    # 处理 fillColor
                    # Android源码算法 (VectorDrawable.cpp:160-166):
                    # 普通颜色: paint.setColor(applyAlpha(fillColor, fillAlpha));
                    # 渐变: paint.setColor(applyAlpha(SK_ColorBLACK, fillAlpha));
                    # 注意：传入 fill_alpha_attr 以便渐变生成时正确处理透明度
                    fill_result = process_color(element_attrs.get('fillColor'), fill_alpha_attr)
                    if fill_result and fill_result[0]:
                        fill_color, color_alpha, is_fill_gradient = fill_result
                        path_attrs.append(f'fill="{fill_color}"')
                        
                        if is_fill_gradient:
                            # 渐变填充：透明度已在渐变 stop-opacity 中处理，无需额外 fill-opacity
                            pass
                        else:
                            # 普通颜色填充：fill-opacity = 颜色alpha * fillAlpha
                            # 注意：color_alpha 已经包含了 fill_alpha_attr 的乘积（在 process_color 中处理）
                            path_attrs.append(f'fill-opacity="{color_alpha:.6g}"')
                    else:
                        path_attrs.append('fill="none"')
                    
                    # 处理 strokeColor
                    # Android源码算法 (VectorDrawable.cpp:177-183):
                    # 普通颜色: paint.setColor(applyAlpha(strokeColor, strokeAlpha));
                    # 渐变: paint.setColor(applyAlpha(SK_ColorBLACK, strokeAlpha));
                    # 注意：传入 stroke_alpha_attr 以便渐变生成时正确处理透明度
                    stroke_result = process_color(element_attrs.get('strokeColor'), stroke_alpha_attr)
                    if stroke_result and stroke_result[0]:
                        stroke_color, color_alpha, is_stroke_gradient = stroke_result
                        path_attrs.append(f'stroke="{stroke_color}"')
                        
                        if is_stroke_gradient:
                            # 渐变描边：透明度已在渐变 stop-opacity 中处理，无需额外 stroke-opacity
                            pass
                        else:
                            # 普通颜色描边：stroke-opacity = 颜色alpha * strokeAlpha
                            # 注意：color_alpha 已经包含了 stroke_alpha_attr 的乘积（在 process_color 中处理）
                            path_attrs.append(f'stroke-opacity="{color_alpha:.6g}"')
                        
                        stroke_width = parse_float(element_attrs.get('strokeWidth'), 0)
                        if stroke_width > 0:
                            path_attrs.append(f'stroke-width="{stroke_width:.6g}"')
                        
                        stroke_line_cap = element_attrs.get('strokeLineCap')
                        if stroke_line_cap is not None:
                            cap_map = {0: 'butt', 1: 'round', 2: 'square'}
                            if isinstance(stroke_line_cap, int) or (isinstance(stroke_line_cap, str) and stroke_line_cap.isdigit()):
                                stroke_line_cap = cap_map.get(int(stroke_line_cap), 'butt')
                            path_attrs.append(f'stroke-linecap="{stroke_line_cap}"')
                        
                        stroke_line_join = element_attrs.get('strokeLineJoin')
                        if stroke_line_join is not None:
                            join_map = {0: 'miter', 1: 'round', 2: 'bevel'}
                            if isinstance(stroke_line_join, int) or (isinstance(stroke_line_join, str) and stroke_line_join.isdigit()):
                                stroke_line_join = join_map.get(int(stroke_line_join), 'miter')
                            path_attrs.append(f'stroke-linejoin="{stroke_line_join}"')
                        
                        # 只在 XML 中明确定义时才输出 strokeMiterLimit
                        stroke_miter_limit_raw = element_attrs.get('strokeMiterLimit')
                        if stroke_miter_limit_raw is not None:
                            stroke_miter_limit = parse_float(stroke_miter_limit_raw, 4)
                            path_attrs.append(f'stroke-miterlimit="{stroke_miter_limit:.6g}"')
                    
                    # 只在 XML 中明确定义时才输出 fill-rule
                    # fillType转SVG fill-rule: 0=nonZero(非零环绕) -> nonzero, 1=evenOdd(奇偶规则) -> evenodd
                    fill_type = element_attrs.get('fillType')
                    if fill_type is not None:
                        fill_rule = "nonzero" if int(fill_type) == 0 else "evenodd"
                        path_attrs.append(f'fill-rule="{fill_rule}"')
                    
                    # 处理 trimPath 属性（trimPathStart、trimPathEnd、trimPathOffset）
                    trim_path_start = element_attrs.get('trimPathStart')
                    if trim_path_start is not None:
                        app_logger.warning(f"发现 trimPathStart 属性，但暂不支持: {trim_path_start}")
                    trim_path_end = element_attrs.get('trimPathEnd')
                    if trim_path_end is not None:
                        app_logger.warning(f"发现 trimPathEnd 属性，但暂不支持: {trim_path_end}")
                    trim_path_offset = element_attrs.get('trimPathOffset')
                    if trim_path_offset is not None:
                        app_logger.warning(f"发现 trimPathOffset 属性，但暂不支持: {trim_path_offset}")
                    
                    if clip_path_id:
                        path_attrs.append(f'clip-path="url(#{clip_path_id})"')
                    
                    result.append(f'{indent_str}<path {" ".join(path_attrs)}/>')
                
                elif element_name == 'clip-path':
                    # clip-path 元素在 group 处理中已经处理
                    # 这里处理根级别的 clip-path（如果有的话）
                    app_logger.debug(f"处理根级别clip-path元素")
                    clip_id = f'clip-{id(element)}'
                    
                    path_data = element_attrs.get('pathData')
                    if path_data:
                        result.append(f'{indent_str}<defs>')
                        result.append(f'{indent_str}  <clipPath id="{clip_id}">')
                        result.append(f'{indent_str}    <path d="{path_data}"/>')
                        result.append(f'{indent_str}  </clipPath>')
                        result.append(f'{indent_str}</defs>')
                    
                    # 返回 None 因为 clip-path 本身不产生可见内容
                    # 但需要记录 clip_id 供后续元素使用
                    # 这里简化处理：根级别的 clip-path 不影响后续元素
                    return None
                
                else:
                    app_logger.debug(f"跳过未知元素类型: {element_name}")
                    for child in children:
                        child_svg = convert_element(child, indent, clip_path_id)
                        if child_svg:
                            result.append(child_svg)
                
                return '\n'.join(result) if result else None
            
            # 解析viewport尺寸 - Android无默认值，必须显式设置
            viewport_width = parse_float(attrs.get('viewportWidth'))
            viewport_height = parse_float(attrs.get('viewportHeight'))
            
            if viewport_width is None or viewport_height is None or viewport_width <= 0 or viewport_height <= 0:
                app_logger.error(f"viewport 尺寸无效或未设置: viewportWidth={attrs.get('viewportWidth')}, viewportHeight={attrs.get('viewportHeight')}")
                return None
            
            width = parse_float(attrs.get('width'), viewport_width)
            height = parse_float(attrs.get('height'), viewport_height)
            
            # 解析 vector 根元素的 alpha 属性
            vector_alpha = parse_float(attrs.get('alpha'), 1.0)
            if vector_alpha is not None and (vector_alpha < 0 or vector_alpha > 1):
                vector_alpha = 1.0
            
            app_logger.debug(f"  viewport: {viewport_width} x {viewport_height}, size: {width} x {height}")
            if vector_alpha is not None and vector_alpha < 1.0:
                app_logger.debug(f"  vector alpha: {vector_alpha}")
            
            svg_parts = []
            svg_parts.append('<?xml version="1.0" encoding="utf-8"?>')
            
            # 构建 SVG 根元素属性
            svg_attrs = [f'xmlns="http://www.w3.org/2000/svg"']
            svg_attrs.append(f'width="{width}" height="{height}"')
            svg_attrs.append(f'viewBox="0 0 {viewport_width} {viewport_height}"')
            
            # 如果有 alpha 属性，添加 opacity
            if vector_alpha is not None and vector_alpha < 1.0:
                svg_attrs.append(f'opacity="{vector_alpha}"')
            
            svg_parts.append(f'<svg {" ".join(svg_attrs)}>')
            
            # 处理 vector 根元素的子元素
            # 根据 Android 源码，clip-path 裁剪的是后续兄弟元素
            # 所以需要按顺序处理，遇到 clip-path 后更新 current_clip_id
            current_clip_id = None
            children_svg = []
            for child in vector_element.get('children', []):
                child_name = child.get('name', '')
                
                if child_name == 'clip-path':
                    # 处理 clip-path 元素：生成定义并更新 current_clip_id
                    child_attrs = child.get('attrs', {})
                    path_data = child_attrs.get('pathData')
                    if path_data:
                        new_clip_id = f'clip-{id(child)}'
                        # 将 clip-path 定义添加到 defs 中
                        gradient_defs.append(f'<clipPath id="{new_clip_id}"><path d="{path_data}"/></clipPath>')
                        current_clip_id = new_clip_id
                        app_logger.debug(f"生成根级别clip-path定义: {new_clip_id}")
                else:
                    # 非 clip-path 元素：使用当前的 clip_id（如果有）
                    child_svg = convert_element(child, 1, current_clip_id)
                    if child_svg:
                        children_svg.append(child_svg)
            
            # 如果有渐变定义或clip-path定义，添加 defs 元素
            if gradient_defs:
                svg_parts.append('  <defs>')
                for gradient_def in gradient_defs:
                    for line in gradient_def.split('\n'):
                        svg_parts.append(f'    {line}')
                svg_parts.append('  </defs>')
            
            # 添加处理后的子元素
            for child_svg in children_svg:
                svg_parts.append(child_svg)
            
            svg_parts.append('</svg>')
            
            svg_content = '\n'.join(svg_parts)
            
            app_logger.debug("vector到SVG转换完成")
            app_logger.debug(f"  生成的SVG: \n{svg_content}")
            
            return svg_content
            
        except Exception as e:
            app_logger.error(f"转换vector到SVG失败: {e}")
            import traceback
            app_logger.error(traceback.format_exc())
            return None
    
    def _render_vector_icon_with_svg(self, element, size=432):
        """
        使用SVG方式渲染矢量图标（使用PyQt5 QSvgRenderer）
        
        参数:
            element: vector元素
            size: 输出尺寸
            
        返回:
            bytes: PNG图像数据，或None
        """
        try:
            app_logger.debug("开始使用SVG方式渲染矢量图标")
            
            svg_content = self._convert_vector_to_svg(element)
            if not svg_content:
                app_logger.error("无法生成SVG内容")
                return None
            
            app_logger.debug(f"SVG内容已生成，准备转换为PNG")
            app_logger.debug(f"  目标尺寸: {size} x {size}")
            
            # 使用PyQt5 QSvgRenderer渲染svg图像
            try:
                from PyQt5.QtSvg import QSvgRenderer
                from PyQt5.QtCore import QByteArray
                from PyQt5.QtGui import QImage, QPainter
                
                app_logger.debug("使用PyQt5 QSvgRenderer进行渲染")
                
                svg_data = QByteArray(svg_content.encode('utf-8'))
                renderer = QSvgRenderer(svg_data)
                
                if not renderer.isValid():
                    app_logger.error("PyQt5 QSvgRenderer: SVG无效")
                    return None
                
                q_size = QSize(size, size)
                image = QImage(q_size, QImage.Format_ARGB32)
                image.fill(Qt.transparent)
                
                painter = QPainter(image)
                renderer.render(painter)
                painter.end()
                
                app_logger.debug("PyQt5 QSvgRenderer渲染完成")
                
                # 将QImage转换为PIL Image，再保存为PNG
                bits = image.bits()
                bits.setsize(image.byteCount())
                img = Image.frombuffer("RGBA", (image.width(), image.height()), bits, "raw", "BGRA", 0, 1)
                
                output = BytesIO()
                img.save(output, format='PNG')
                return output.getvalue()
                
            except ImportError as e:
                app_logger.error(f"PyQt5 QSvgRenderer不可用: {e}")
                return None
            except Exception as e:
                app_logger.error(f"PyQt5 QSvgRenderer渲染失败: {e}")
                import traceback
                app_logger.error(traceback.format_exc())
                return None
                
        except Exception as e:
            app_logger.error(f"SVG渲染方式失败: {e}")
            import traceback
            app_logger.error(traceback.format_exc())
            return None
    
    def _get_color_resource_value(self, resource_id, depth=0, visited=None):
        """
        获取颜色资源值，支持渐变资源
        
        参数:
            resource_id: 资源ID（十六进制字符串或名称格式）
            depth: 递归深度（防止无限循环）
            visited: 已访问的资源ID集合（用于检测循环引用）
        
        返回:
            颜色字符串（如 #FFFFFFFF）或渐变字典，或None
        """
        try:
            original_resource_id = resource_id
            
            if not isinstance(resource_id, str):
                app_logger.warning(f"未识别的资源ID类型: {original_resource_id!r}")
                return None
            
            if resource_id.startswith('@'):
                resource_id = resource_id[1:]
            
            if visited is None:
                visited = set()
            
            if resource_id in visited:
                app_logger.warning(f"检测到循环引用: {resource_id}")
                return None
            
            if resource_id in self._color_resource_cache:
                app_logger.debug(f"使用颜色缓存: {resource_id}")
                return self._color_resource_cache[resource_id]
            
            if depth > MAX_RECURSION_DEPTH:
                app_logger.warning(f"资源引用递归深度超过限制({depth}层): {original_resource_id}")
                return None
            
            visited.add(resource_id)
            
            res_id_int = None
            res_info = None
            
            if '/' in resource_id:
                # app_logger.debug(f"加载颜色资源: @{resource_id}")
                res_info = self.get_resource_by_name('@' + resource_id)
            elif resource_id.startswith('0x'):
                try:
                    res_id_int = int(resource_id, 16)
                except ValueError:
                    app_logger.warning(f"未识别的资源ID格式: {original_resource_id}")
                    return None
                # app_logger.debug(f"加载颜色资源: @{resource_id}")
            else:
                app_logger.warning(f"未识别的资源ID格式: {original_resource_id}")
                return None
            
            # 检查是否是 Android 系统内置颜色资源
            system_color = self._get_android_system_color(resource_id)
            if system_color:
                color_hex, color_name = system_color
                app_logger.debug(f"安卓系统内置颜色: {color_name} ({color_hex})")
                return color_hex
            
            result = None
            
            if res_info is None and res_id_int is not None:
                res_info = self.get_resource_by_id(resource_id)
            
            if result is None and res_info:
                value = res_info.get('color_value') or res_info.get('value')
                if value and value.startswith('#'):
                    result = value
                
                if result is None:
                    configs = res_info.get('configs', [])
                    for config in configs:
                        reference = config.get('reference', '')
                        if reference:
                            app_logger.debug(f"发现颜色引用: {resource_id} -> {reference}")
                            if reference.startswith('@0x'):
                                ref_res_id = reference[1:]
                            elif reference.startswith('@'):
                                ref_res_id = reference[1:]
                            else:
                                ref_res_id = reference
                            result = self._get_color_resource_value(ref_res_id, depth + 1, visited)
                            if result is not None:
                                break
                        
                        path = config.get('path', '')
                        if path and path.startswith('#'):
                            result = path
                            break
                        
                        if path and path.endswith('.xml'):
                            gradient_info = self._parse_gradient_xml(path)
                            if gradient_info:
                                result = gradient_info
                                break
            
            if result is not None:
                self._color_resource_cache[original_resource_id] = result
            
            return result
        except Exception as e:
            app_logger.error(f"解析颜色失败: {resource_id}, 错误: {e}")
            return None
    
    def _get_dimen_resource_value(self, resource_id):
        """
        获取尺寸资源值
        
        参数:
            resource_id: 资源ID（可以是十六进制字符串或整数）
        
        返回:
            尺寸字符串（如 "18dp"）或None
        """
        try:
            if isinstance(resource_id, str):
                if resource_id.startswith('@'):
                    resource_id = resource_id[1:]
                res_id_int = int(resource_id, 16) if resource_id.startswith('0x') else int(resource_id, 16)
            else:
                res_id_int = resource_id
            
            res_info = self.get_resource_by_id(resource_id)
            if res_info:
                value = res_info.get('dimen_value')
                if value:
                    return value
            
            return None
        except Exception:
            return None
    
    def _parse_gradient_xml(self, xml_path):
        """
        解析渐变XML资源，支持两种格式：
        1. startColor/endColor/angle 格式
        2. startX/startY/endX/endY + item 子元素格式
        
        参数:
            xml_path: XML文件路径
        
        返回:
            渐变信息字典，或None
        """
        try:
            app_logger.debug(f"解析渐变XML: {xml_path}")
            xml_content, err = self._run_aapt2_xmltree(xml_path)
            app_logger.debug(f"XML解码原文 ({xml_path}):\n{xml_content}")

            if xml_content.strip() == "":
                app_logger.warning(f"获取XML原始内容失败: {xml_path}，{err}")
                return None
            
            parsed = self._parse_xmltree_output(xml_content)
            if not parsed or not parsed.get('elements'):
                app_logger.error(f"解析渐变XML失败: {xml_path}")
                return None
            
            root = parsed['elements'][0]
            root_name = root.get('name', '')
            
            # 查找 gradient 元素（可能在根元素内部）
            gradient_element = None
            if root_name == 'gradient':
                gradient_element = root
            else:
                # 在子元素中查找 gradient
                def find_gradient_element(elem):
                    if elem.get('name') == 'gradient':
                        return elem
                    for child in elem.get('children', []):
                        result = find_gradient_element(child)
                        if result:
                            return result
                    return None
                
                gradient_element = find_gradient_element(root)
            
            if not gradient_element:
                app_logger.error(f"未找到gradient元素: {xml_path}, 根元素: {root_name}")
                return None
            
            attrs = gradient_element.get('attrs', {})
            
            def parse_float_val(v):
                if v is None:
                    return None
                v = str(v).strip('"').strip("'")
                # 兼容普通浮点数+科学计数法，严格匹配整行
                pattern = r'^(-?\d+\.?\d*([eE][+-]?\d+)?)$'
                match = re.match(pattern, v)
                if match:
                    return float(match.group(1))
                return None
            
            start_x = parse_float_val(attrs.get('startX'))
            start_y = parse_float_val(attrs.get('startY'))
            end_x = parse_float_val(attrs.get('endX'))
            end_y = parse_float_val(attrs.get('endY'))
            start_color = attrs.get('startColor')
            end_color = attrs.get('endColor')
            angle = parse_float_val(attrs.get('angle'))
            try:
                gradient_type = int(attrs.get('type', '0'))
            except Exception as e:
                app_logger.warning(f"无法获取渐变类型，使用默认的直线渐变：{e}")
                gradient_type = 0
            center_x = parse_float_val(attrs.get('centerX'))
            center_y = parse_float_val(attrs.get('centerY'))
            gradient_radius = parse_float_val(attrs.get('gradientRadius'))
            
            # 先判断渐变类型，如果未识别或者不支持，则直接返回空
            if gradient_type > 2 or gradient_type < 0:  # 未识别的渐变类型
                app_logger.error(f"未识别渐变类型：{gradient_type}")
                return None
            elif gradient_type == 2:  # 扫描渐变 - 暂时不支持
                app_logger.warning(f"无法解析渐变(扫描渐变, type=2)，暂不支持，跳过: {xml_path}")
                return None
            
            items = []
            
            children = root.get('children', [])
            for child in children:
                if child.get('name') == 'item':
                    child_attrs = child.get('attrs', {})
                    color = child_attrs.get('color')
                    offset = parse_float_val(child_attrs.get('offset')) or 0
                    
                    if color:
                        color_val = self._parse_color(color)
                        items.append({'color': color_val, 'offset': offset})
            
            if start_color and end_color:  # 将 start_color 和 end_color 转换成 items
                start_color_val = self._get_color_resource_value(start_color) if start_color.startswith('0x') else start_color
                end_color_val = self._get_color_resource_value(end_color) if end_color.startswith('0x') else end_color
                # 解析颜色值
                if start_color_val and not isinstance(start_color_val, tuple) and not isinstance(start_color_val, dict):
                    start_color_val = self._parse_color(start_color_val)
                if end_color_val and not isinstance(end_color_val, tuple) and not isinstance(end_color_val, dict):
                    end_color_val = self._parse_color(end_color_val)
                
                if not items:
                    items = [
                        {'color': start_color_val, 'offset': 0.0},
                        {'color': end_color_val, 'offset': 1.0}
                    ]

            if items:
                app_logger.debug(f"渐变解析 - items数量: {len(items)}, gradient_type: {gradient_type}")
                app_logger.debug(f"渐变解析 - center_x: {center_x}, center_y: {center_y}, gradient_radius: {gradient_radius}")
                app_logger.debug(f"渐变解析 - start_x: {start_x}, start_y: {start_y}, end_x: {end_x}, end_y: {end_y}")
                
                # 根据type属性决定渐变类型
                if gradient_type == 1:  # radial
                    # 径向渐变 - 需要centerX, centerY, gradientRadius
                    if center_x is not None and center_y is not None and gradient_radius is not None:
                        result = {
                            'type': 'radial_gradient',
                            'centerX': center_x,
                            'centerY': center_y,
                            'gradientRadius': gradient_radius,
                            'is_normalized': False,
                            'items': items
                        }
                        app_logger.debug(f"解析渐变成功(径向渐变, type=1): {xml_path}, items数量: {len(items)}")
                        return result
                    else:
                        app_logger.warning(f"无法解析渐变(径向渐变, type=1): {xml_path}, 缺少必要属性")
                        return None
                else:  # gradient_type == 0  # linear
                    # 线性渐变，优先使用坐标
                    if start_x is not None and start_y is not None and end_x is not None and end_y is not None:
                        result = {
                            'type': 'linear_gradient',
                            'startX': start_x,
                            'startY': start_y,
                            'endX': end_x,
                            'endY': end_y,
                            'is_normalized': False,
                            'items': items
                        }
                        app_logger.debug(f"解析渐变成功(线性渐变, type=0): {xml_path}, items数量: {len(items)}")
                        return result
                    elif angle is not None:  # 渐变角度
                        # 线性渐变 - 根据angle计算坐标
                        normalized_angle = angle % 360
                        
                        if normalized_angle == 0.0:
                            sx, sy = 0.5, 0.0
                            ex, ey = 0.5, 1.0
                        elif normalized_angle == 45.0:
                            sx, sy = 0.0, 1.0
                            ex, ey = 1.0, 0.0
                        elif normalized_angle == 90.0:
                            sx, sy = 0.0, 0.5
                            ex, ey = 1.0, 0.5
                        elif normalized_angle == 135.0:
                            sx, sy = 0.0, 0.0
                            ex, ey = 1.0, 1.0
                        elif normalized_angle == 180.0:
                            sx, sy = 0.5, 1.0
                            ex, ey = 0.5, 0.0
                        elif normalized_angle == 225.0:
                            sx, sy = 1.0, 0.0
                            ex, ey = 0.0, 1.0
                        elif normalized_angle == 270.0:
                            sx, sy = 1.0, 0.5
                            ex, ey = 0.0, 0.5
                        elif normalized_angle == 315.0:
                            sx, sy = 1.0, 1.0
                            ex, ey = 0.0, 0.0
                        else:
                            adj_rad = math.radians(90.0 - normalized_angle)
                            dx = math.cos(adj_rad)
                            dy = -math.sin(adj_rad)
                            max_dist = max(abs(dx), abs(dy))
                            if max_dist > 0:
                                dx /= max_dist
                                dy /= max_dist
                            sx = 0.5 - dx * 0.5
                            sy = 0.5 - dy * 0.5
                            ex = 0.5 + dx * 0.5
                            ey = 0.5 + dy * 0.5
                        
                        result = {
                            'type': 'linear_gradient',
                            'startX': sx,
                            'startY': sy,
                            'endX': ex,
                            'endY': ey,
                            'is_normalized': True,
                            'items': items
                        }
                        app_logger.debug(f"解析渐变成功(线性渐变, type=0): {xml_path}, angle: {normalized_angle}")
                        return result
                    else:  # 缺少必要属性
                        app_logger.warning(f"无法解析渐变(线性渐变, type=0): {xml_path}, 缺少必要属性")
                        return None
            
            app_logger.warning(f"无法解析渐变: {xml_path}, 缺少必要属性")
            return None
        except Exception as e:
            app_logger.error(f"解析渐变XML异常: {xml_path}, 错误: {e}")
            return None
    
    def _parse_color(self, color_str):
        """解析颜色字符串，支持资源ID引用，带缓存"""
        if not color_str:
            return None
        
        color_str = str(color_str).strip()
        
        if color_str in self._color_cache:
            return self._color_cache[color_str]
        
        result = self._parse_color_internal(color_str)
        self._color_cache[color_str] = result
        return result
    
    def _parse_color_internal(self, color_str):
        """内部颜色解析方法"""
        if color_str.startswith('@'):
            res_id = color_str[1:]
            color_value = self._get_color_resource_value(res_id)
            if color_value:
                return self._parse_color(color_value)
            return (128, 128, 128, 255)
        
        if color_str.startswith('0x'):
            if len(color_str) == 10 and color_str.startswith('0x01'):
                color_value = self._get_color_resource_value(color_str)
                if color_value:
                    return self._parse_color(color_value)
                return (128, 128, 128, 255)
            elif len(color_str) == 10:
                color_value = self._get_color_resource_value(color_str)
                if color_value:
                    if isinstance(color_value, dict):
                        return color_value
                    return self._parse_color(color_value)
                return (128, 128, 128, 255)
        
        if color_str.startswith('#'):
            hex_color = color_str[1:]
            
            try:
                if len(hex_color) == 8:
                    a = int(hex_color[0:2], 16)
                    r = int(hex_color[2:4], 16)
                    g = int(hex_color[4:6], 16)
                    b = int(hex_color[6:8], 16)
                    return (r, g, b, a)
                elif len(hex_color) == 6:
                    r = int(hex_color[0:2], 16)
                    g = int(hex_color[2:4], 16)
                    b = int(hex_color[4:6], 16)
                    return (r, g, b, 255)
                elif len(hex_color) == 4:
                    a = int(hex_color[0], 16) * 17
                    r = int(hex_color[1], 16) * 17
                    g = int(hex_color[2], 16) * 17
                    b = int(hex_color[3], 16) * 17
                    return (r, g, b, a)
                elif len(hex_color) == 3:
                    r = int(hex_color[0], 16) * 17
                    g = int(hex_color[1], 16) * 17
                    b = int(hex_color[2], 16) * 17
                    return (r, g, b, 255)
            except ValueError:
                pass
        
        return None
    
    def _get_fill_color_or_gradient(self, fill_color):
        """
        获取填充颜色或渐变
        
        参数:
            fill_color: 填充颜色字符串（可以是颜色值或资源ID引用）
        
        返回:
            颜色元组或渐变字典
        """
        if not fill_color:
            return None
        
        fill_color = str(fill_color).strip()
        
        if fill_color.startswith('@'):
            res_id = fill_color[1:]
            color_value = self._get_color_resource_value(res_id)
            if color_value:
                if isinstance(color_value, dict):
                    return color_value
                return self._parse_color(color_value)
            return None
        
        if fill_color.startswith('0x') and len(fill_color) == 10:
            color_value = self._get_color_resource_value(fill_color)
            if color_value:
                if isinstance(color_value, dict):
                    return color_value
                return self._parse_color(color_value)
            return None
        
        return self._parse_color(fill_color)
    
    def _render_layer_list_icon(self, element, size=432):
        """渲染layer-list图标
        
        基于 Android 16 LayerDrawable 源码实现:
        - 支持 inset 属性 (left, top, right, bottom)
        - 支持 gravity 属性 (center, fill, top, bottom, left, right 等)
        - 支持 width/height 属性
        """
        try:
            result_img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            
            for child in element.get('children', []):
                child_name = child.get('name', '')
                if child_name == 'item':
                    attrs = child.get('attrs', {})
                    
                    # 解析 inset 属性
                    inset_left = int(self._parse_dimension_to_pixels(attrs.get('left', 0), size))
                    inset_top = int(self._parse_dimension_to_pixels(attrs.get('top', 0), size))
                    inset_right = int(self._parse_dimension_to_pixels(attrs.get('right', 0), size))
                    inset_bottom = int(self._parse_dimension_to_pixels(attrs.get('bottom', 0), size))
                    
                    # 解析 gravity 属性
                    gravity = attrs.get('gravity', 'fill')
                    
                    # 解析显式尺寸
                    explicit_width = attrs.get('width')
                    explicit_height = attrs.get('height')
                    
                    # 计算图层容器尺寸
                    container_w = size - inset_left - inset_right
                    container_h = size - inset_top - inset_bottom
                    
                    if container_w <= 0 or container_h <= 0:
                        continue
                    
                    layer_img = None
                    
                    # 加载图层
                    drawable_id = attrs.get('drawable')
                    if drawable_id:
                        # 计算加载尺寸
                        load_size = max(container_w, container_h)
                        if explicit_width and explicit_height:
                            load_size = max(
                                int(self._parse_dimension_to_pixels(explicit_width, size)),
                                int(self._parse_dimension_to_pixels(explicit_height, size))
                            )
                        
                        layer_img = self._load_layer_image(drawable_id, load_size)
                    else:
                        # 处理内嵌元素
                        for sub_child in child.get('children', []):
                            sub_name = sub_child.get('name', '')
                            load_size = max(container_w, container_h)
                            
                            try:
                                if sub_name == 'vector':
                                    app_logger.debug(f"item包含内嵌vector元素")
                                    data = self._render_vector_icon(sub_child, load_size)
                                    if data:
                                        layer_img = Image.open(BytesIO(data))
                                        if layer_img.mode != 'RGBA':
                                            layer_img = layer_img.convert('RGBA')
                                        break
                                elif sub_name == 'bitmap':
                                    app_logger.debug(f"item包含内嵌bitmap元素")
                                    bitmap_attrs = sub_child.get('attrs', {})
                                    src = bitmap_attrs.get('src')
                                    if src:
                                        if not src.startswith('0x'):
                                            src = '0x' + src.lstrip('@')
                                        layer_img = self._load_layer_image(src, load_size)
                                        if layer_img:
                                            break
                                elif sub_name == 'layer-list':
                                    app_logger.debug(f"item包含内嵌layer-list元素")
                                    data = self._render_layer_list_icon(sub_child, load_size)
                                    if data:
                                        layer_img = Image.open(BytesIO(data))
                                        if layer_img.mode != 'RGBA':
                                            layer_img = layer_img.convert('RGBA')
                                        break
                                elif sub_name == 'selector':
                                    app_logger.debug(f"item包含内嵌selector元素")
                                    data = self._render_selector_icon(sub_child, load_size)
                                    if data:
                                        layer_img = Image.open(BytesIO(data))
                                        if layer_img.mode != 'RGBA':
                                            layer_img = layer_img.convert('RGBA')
                                        break
                                elif sub_name == 'shape':
                                    app_logger.debug(f"item包含内嵌shape元素")
                                    data = self._render_shape_icon(sub_child, load_size)
                                    if data:
                                        layer_img = Image.open(BytesIO(data))
                                        if layer_img.mode != 'RGBA':
                                            layer_img = layer_img.convert('RGBA')
                                        break
                                elif sub_name == 'inset':
                                    app_logger.debug(f"item包含内嵌inset元素")
                                    data = self._render_inset_icon(sub_child, load_size)
                                    if data:
                                        layer_img = Image.open(BytesIO(data))
                                        if layer_img.mode != 'RGBA':
                                            layer_img = layer_img.convert('RGBA')
                                        break
                                elif sub_name == 'aapt:attr':
                                    app_logger.debug(f"item包含aapt:attr元素")
                                    for nested_child in sub_child.get('children', []):
                                        data = self._render_layer_list_icon({'children': [nested_child]}, load_size)
                                        if data:
                                            layer_img = Image.open(BytesIO(data))
                                            if layer_img.mode != 'RGBA':
                                                layer_img = layer_img.convert('RGBA')
                                            break
                                    if layer_img:
                                        break
                                elif sub_name:
                                    app_logger.warning(f"item未知的子元素: {sub_name}")
                            except Exception as e:
                                app_logger.warning(f"处理layer-list子元素 {sub_name} 失败: {e}")
                                continue
                    
                    if layer_img:
                        # 应用显式尺寸
                        if explicit_width or explicit_height:
                            target_w = int(self._parse_dimension_to_pixels(explicit_width, size)) if explicit_width else layer_img.width
                            target_h = int(self._parse_dimension_to_pixels(explicit_height, size)) if explicit_height else layer_img.height
                            layer_img = layer_img.resize((target_w, target_h), Image.LANCZOS)
                        
                        # 根据 gravity 计算位置
                        pos_x, pos_y, final_w, final_h = self._apply_gravity(
                            layer_img, container_w, container_h, gravity
                        )
                        
                        # 如果需要缩放
                        if final_w != layer_img.width or final_h != layer_img.height:
                            layer_img = layer_img.resize((final_w, final_h), Image.LANCZOS)
                        
                        # 创建带 inset 的临时画布
                        temp_img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
                        temp_img.paste(layer_img, (inset_left + pos_x, inset_top + pos_y), layer_img)
                        
                        # 合成到结果
                        result_img = Image.alpha_composite(result_img, temp_img)
                        
                elif child_name:
                    app_logger.warning(f"未知的layer-list子元素: {child_name}")
            
            output = BytesIO()
            result_img.save(output, format='PNG')
            return output.getvalue()
        
        except Exception as e:
            app_logger.error(f"渲染失败: {e}")
            return None
    
    def _apply_gravity(self, img, container_w, container_h, gravity):
        """根据 gravity 计算图层位置和尺寸
        
        基于 Android 16 Gravity.java 和 LayerDrawable.java 实现
        
        参数:
            img: PIL.Image 图层图像
            container_w: 容器宽度
            container_h: 容器高度
            gravity: gravity 属性值 (字符串或整数)
        
        返回:
            tuple: (pos_x, pos_y, final_w, final_h) 位置和最终尺寸
        """
        img_w, img_h = img.size
        
        # 解析 gravity 值
        if isinstance(gravity, str):
            gravity_str = gravity.lower()
        else:
            gravity_str = str(gravity).lower()
        
        # 初始化
        pos_x, pos_y = 0, 0
        final_w, final_h = img_w, img_h
        
        # 处理 fill 模式
        fill_horizontal = 'fill_horizontal' in gravity_str or 'fill' in gravity_str
        fill_vertical = 'fill_vertical' in gravity_str or 'fill' in gravity_str
        
        if fill_horizontal:
            final_w = container_w
        if fill_vertical:
            final_h = container_h
        
        # 计算水平位置
        if 'center_horizontal' in gravity_str or 'center' in gravity_str:
            pos_x = (container_w - final_w) // 2
        elif 'right' in gravity_str or 'end' in gravity_str:
            pos_x = container_w - final_w
        elif 'left' in gravity_str or 'start' in gravity_str:
            pos_x = 0
        elif not fill_horizontal:
            # 默认居中
            pos_x = (container_w - final_w) // 2
        
        # 计算垂直位置
        if 'center_vertical' in gravity_str or 'center' in gravity_str:
            pos_y = (container_h - final_h) // 2
        elif 'bottom' in gravity_str:
            pos_y = container_h - final_h
        elif 'top' in gravity_str:
            pos_y = 0
        elif not fill_vertical:
            # 默认居中
            pos_y = (container_h - final_h) // 2
        
        return pos_x, pos_y, final_w, final_h
    
    def _render_selector_icon(self, element, size=432):
        """渲染selector图标
        
        基于 Android 16 StateListDrawable 源码实现：
        - 选择第一个匹配当前状态的 item
        - 如果没有匹配，选择第一个没有状态限制的 item
        """
        try:
            app_logger.debug("开始渲染selector图标")
            
            default_item = None
            for child in element.get('children', []):
                child_name = child.get('name', '')
                if child_name == 'item':
                    attrs = child.get('attrs', {})
                    has_state = any('state' in k for k in attrs.keys())
                    
                    if not has_state:
                        drawable_id = attrs.get('drawable')
                        if drawable_id:
                            app_logger.debug(f"找到默认selector item: {drawable_id}")
                            return self._load_layer_image(drawable_id, size)
                        default_item = child
                elif child_name:
                    app_logger.warning(f"未知的selector子元素: {child_name}")
            
            if default_item:
                drawable_id = default_item.get('attrs', {}).get('drawable')
                if drawable_id:
                    app_logger.debug(f"使用默认selector item: {drawable_id}")
                    return self._load_layer_image(drawable_id, size)
            
            app_logger.warning("selector图标没有找到可用的item")
            return None
        
        except Exception as e:
            app_logger.error(f"渲染selector图标失败: {e}")
            import traceback
            app_logger.error(traceback.format_exc())
            return None
    
    def _render_bitmap_icon(self, element, size=432):
        """渲染bitmap图标"""
        try:
            attrs = element.get('attrs', {})
            src = attrs.get('src')
            
            if src:
                if not src.startswith('0x'):
                    src = '0x' + src.lstrip('@')
                img = self._load_layer_image(src, size)
                if img:
                    output = BytesIO()
                    img.save(output, format='PNG')
                    return output.getvalue()
            
            return None
        
        except Exception as e:
            app_logger.error(f"渲染失败: {e}")
            return None
    
    def _render_shape_icon(self, element, size=432):
        """渲染 shape 图标"""
        try:
            
            img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            
            attrs = element.get('attrs', {})
            
            shape_type = attrs.get('shape', 'rectangle')
            app_logger.debug(f"shape 类型：{shape_type}")
            
            width = size
            height = size
            
            # 先收集所有子元素信息
            corners_info = None
            solid_color = None
            gradient_info = None
            
            for child in element.get('children', []):
                child_name = child.get('name', '')
                
                if child_name == 'size':
                    size_attrs = child.get('attrs', {})
                    w_val = size_attrs.get('width')
                    h_val = size_attrs.get('height')
                    
                    if w_val:
                        width = self._parse_dimension_to_pixels(w_val, size)
                    if h_val:
                        height = self._parse_dimension_to_pixels(h_val, size)
                
                elif child_name == 'solid':
                    color_attr = child.get('attrs', {}).get('color')
                    if color_attr:
                        solid_color = self._parse_color(color_attr)
                
                elif child_name == 'gradient':
                    gradient_attrs = child.get('attrs', {})
                    start_color = gradient_attrs.get('startColor')
                    end_color = gradient_attrs.get('endColor')
                    angle = gradient_attrs.get('angle', 0)
                    gradient_type = gradient_attrs.get('type', 'linear')
                    
                    if start_color and end_color:
                        start_rgba = self._parse_color(start_color)
                        end_rgba = self._parse_color(end_color)
                        if start_rgba and end_rgba:
                            gradient_info = {
                                'startColor': start_rgba,
                                'endColor': end_rgba,
                                'angle': float(angle) if angle else 0,
                                'type': gradient_type
                            }
                            app_logger.debug(f"解析渐变: startColor={start_rgba}, endColor={end_rgba}, angle={angle}")
                
                elif child_name == 'corners':
                    corners_attrs = child.get('attrs', {})
                    radius = corners_attrs.get('radius')
                    
                    if radius:
                        radius_val = self._parse_dimension_to_pixels(radius, size)
                        corners_info = {
                            'top_left': self._parse_dimension_to_pixels(corners_attrs.get('topLeftRadius', radius), size),
                            'top_right': self._parse_dimension_to_pixels(corners_attrs.get('topRightRadius', radius), size),
                            'bottom_left': self._parse_dimension_to_pixels(corners_attrs.get('bottomLeftRadius', radius), size),
                            'bottom_right': self._parse_dimension_to_pixels(corners_attrs.get('bottomRightRadius', radius), size)
                        }
            
            # 绘制形状
            if gradient_info:
                img = self._draw_shape_gradient(img, shape_type, 0, 0, size, size, gradient_info, corners_info)
            elif solid_color:
                self._draw_shape(draw, shape_type, 0, 0, size, size, fill=solid_color, corners=corners_info)
            
            output = BytesIO()
            img.save(output, format='PNG')
            return output.getvalue()
        
        except Exception as e:
            app_logger.error(f"渲染失败：{e}")
            return None
    
    def _parse_dimension_to_pixels(self, value, base_size=432):
        """将维度值转换为像素"""
        if value is None:
            return base_size
        
        if isinstance(value, (int, float)):
            return float(value)
        
        value = str(value).strip()
        
        try:
            if value.endswith('%'):
                percent_val = float(value[:-1])
                if percent_val < 1:
                    percent_val *= 100
                return percent_val / 100 * base_size
            elif value.endswith('dp'):
                return float(value[:-2]) * base_size / 48
            elif value.endswith('px'):
                return float(value[:-2])
            elif value.endswith('dip'):
                return float(value[:-3]) * base_size / 48
            elif value.endswith('pt'):
                return float(value[:-2]) * base_size / 72
            elif value.endswith('mm'):
                return float(value[:-2]) * base_size / 25.4
            elif value.endswith('in'):
                return float(value[:-2]) * base_size
            else:
                return float(value) * base_size / 48
        except:
            return base_size
    
    def _draw_shape_gradient(self, img, shape_type, x, y, width, height, gradient_info, corners=None):
        """
        绘制带渐变的形状。
        
        Args:
            img: PIL Image 对象
            shape_type: 形状类型 (rectangle, oval, line, ring)
            x, y, width, height: 形状位置和尺寸
            gradient_info: 渐变信息字典，包含 startColor, endColor, angle, type
            corners: 圆角信息（仅对 rectangle 有效）
            
        Returns:
            PIL Image 对象
        """
        start_color = gradient_info.get('startColor', (255, 255, 255, 255))
        end_color = gradient_info.get('endColor', (0, 0, 0, 255))
        angle = gradient_info.get('angle', 0)
        
        # 规范化角度到 0-359 范围
        angle = ((int(angle) % 360) + 360) % 360
        
        # 根据 Android 源码 GradientDrawable.java 中的角度定义计算渐变起止点
        # 参考: android16-release/graphics-java-android-graphics-drawable/GradientDrawable.java
        # angle 0 = LEFT_RIGHT (从左到右)
        # angle 45 = BL_TR (从左下到右上)
        # angle 90 = BOTTOM_TOP (从下到上)
        # angle 135 = BR_TL (从右下到左上)
        # angle 180 = RIGHT_LEFT (从右到左)
        # angle 225 = TR_BL (从右上到左下)
        # angle 270 = TOP_BOTTOM (从上到下)
        # angle 315 = TL_BR (从左上到右下)
        
        # 计算渐变起点和终点（参考 Android ensureValidRect 方法）
        # 使用矩形边界
        r_left, r_top, r_right, r_bottom = 0, 0, width, height
        
        # 根据角度确定渐变方向（只支持 45 度倍数，其他角度使用默认方向）
        if angle == 0:  # LEFT_RIGHT
            x0, y0 = r_left, r_top
            x1, y1 = r_right, r_top
        elif angle == 45:  # BL_TR
            x0, y0 = r_left, r_bottom
            x1, y1 = r_right, r_top
        elif angle == 90:  # BOTTOM_TOP
            x0, y0 = r_left, r_bottom
            x1, y1 = r_left, r_top
        elif angle == 135:  # BR_TL
            x0, y0 = r_right, r_bottom
            x1, y1 = r_left, r_top
        elif angle == 180:  # RIGHT_LEFT
            x0, y0 = r_right, r_top
            x1, y1 = r_left, r_top
        elif angle == 225:  # TR_BL
            x0, y0 = r_right, r_top
            x1, y1 = r_left, r_bottom
        elif angle == 270:  # TOP_BOTTOM
            x0, y0 = r_left, r_top
            x1, y1 = r_left, r_bottom
        elif angle == 315:  # TL_BR
            x0, y0 = r_left, r_top
            x1, y1 = r_right, r_bottom
        else:
            # 默认使用 TOP_BOTTOM (从上到下)
            x0, y0 = r_left, r_top
            x1, y1 = r_left, r_bottom
        
        dx = x1 - x0
        dy = y1 - y0
        length_sq = dx * dx + dy * dy
        
        gradient_img = Image.new('RGBA', (int(width), int(height)), (0, 0, 0, 0))
        
        if length_sq == 0:
            # 如果长度为0，用纯色填充
            draw = ImageDraw.Draw(gradient_img)
            if shape_type == 'rectangle':
                draw.rectangle([0, 0, width - 1, height - 1], fill=start_color)
            elif shape_type == 'oval':
                draw.ellipse([0, 0, width - 1, height - 1], fill=start_color)
        else:
            pixels = gradient_img.load()
            
            for py in range(int(height)):
                for px in range(int(width)):
                    # 计算当前点在渐变方向上的投影比例 t
                    t = ((px - x0) * dx + (py - y0) * dy) / length_sq
                    t = max(0.0, min(1.0, t))
                    
                    r = int(start_color[0] + t * (end_color[0] - start_color[0]))
                    g = int(start_color[1] + t * (end_color[1] - start_color[1]))
                    b = int(start_color[2] + t * (end_color[2] - start_color[2]))
                    a = int(start_color[3] + t * (end_color[3] - start_color[3]))
                    
                    pixels[px, py] = (r, g, b, a)
        
        # 应用形状遮罩
        if shape_type == 'rectangle' and corners:
            mask = Image.new('L', (int(width), int(height)), 0)
            mask_draw = ImageDraw.Draw(mask)
            self._draw_rounded_rectangle(mask_draw, [0, 0, width - 1, height - 1],
                                       corners.get('top_left', 0), corners.get('top_right', 0),
                                       corners.get('bottom_left', 0), corners.get('bottom_right', 0),
                                       fill=255)
            result = Image.new('RGBA', (int(width), int(height)), (0, 0, 0, 0))
            result.paste(gradient_img, (0, 0), mask)
            gradient_img = result
        elif shape_type == 'oval':
            mask = Image.new('L', (int(width), int(height)), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse([0, 0, width - 1, height - 1], fill=255)
            result = Image.new('RGBA', (int(width), int(height)), (0, 0, 0, 0))
            result.paste(gradient_img, (0, 0), mask)
            gradient_img = result
        
        # 将渐变图像粘贴到原图
        img.paste(gradient_img, (int(x), int(y)), gradient_img)
        
        return img
    
    def _draw_shape(self, draw, shape_type, x, y, width, height, fill=None, outline=None, width_stroke=1, corners=None):
        """绘制不同形状的图形"""
        if shape_type == 'rectangle':
            if corners:
                self._draw_rounded_rectangle(draw, [x, y, x + width - 1, y + height - 1],
                                           corners.get('top_left', 0), corners.get('top_right', 0),
                                           corners.get('bottom_left', 0), corners.get('bottom_right', 0),
                                           fill=fill, outline=outline, width=width_stroke)
            else:
                draw.rectangle([x, y, x + width - 1, y + height - 1], fill=fill, outline=outline, width=width_stroke)
        
        elif shape_type == 'oval':
            draw.ellipse([x, y, x + width - 1, y + height - 1], fill=fill, outline=outline, width=width_stroke)
        
        elif shape_type == 'line':
            draw.line([(x, y + height // 2), (x + width, y + height // 2)], fill=outline, width=width_stroke)
        
        elif shape_type == 'ring':
            if fill:
                draw.ellipse([x, y, x + width - 1, y + height - 1], fill=fill)
            if outline:
                inner_x = x + width_stroke
                inner_y = y + width_stroke
                inner_width = width - 2 * width_stroke
                inner_height = height - 2 * width_stroke
                if inner_width > 0 and inner_height > 0:
                    draw.ellipse([inner_x, inner_y, inner_x + inner_width - 1, inner_y + inner_height - 1], fill=(0, 0, 0, 0))
    
    def _draw_rounded_rectangle(self, draw, bbox, radius_top_left, radius_top_right, 
                               radius_bottom_left, radius_bottom_right, 
                               fill=None, outline=None, width=1):
        """绘制圆角矩形"""
        
        x1, y1, x2, y2 = bbox
        
        if radius_top_left == 0 and radius_top_right == 0 and radius_bottom_left == 0 and radius_bottom_right == 0:
            if fill:
                draw.rectangle([x1, y1, x2, y2], fill=fill)
            if outline:
                draw.rectangle([x1, y1, x2, y2], outline=outline, width=width)
            return
        
        mask = Image.new('L', (x2 - x1 + 1, y2 - y1 + 1), 0)
        mask_draw = ImageDraw.Draw(mask)
        
        min_radius = min(radius_top_left, radius_top_right, radius_bottom_left, radius_bottom_right)
        
        if radius_top_left > 0:
            mask_draw.pieslice([x1, y1, x1 + 2 * radius_top_left - 1, y1 + 2 * radius_top_left - 1], 
                              start=90, end=180, fill=255)
        
        if radius_top_right > 0:
            mask_draw.pieslice([x2 - 2 * radius_top_right + 1, y1, x2, y1 + 2 * radius_top_right - 1], 
                              start=0, end=90, fill=255)
        
        if radius_bottom_left > 0:
            mask_draw.pieslice([x1, y2 - 2 * radius_bottom_left + 1, x1 + 2 * radius_bottom_left - 1, y2], 
                              start=180, end=270, fill=255)
        
        if radius_bottom_right > 0:
            mask_draw.pieslice([x2 - 2 * radius_bottom_right + 1, y2 - 2 * radius_bottom_right + 1, x2, y2], 
                              start=270, end=360, fill=255)
        
        center_x1 = x1 + min_radius
        center_x2 = x2 - min_radius
        center_y1 = y1 + min_radius
        center_y2 = y2 - min_radius
        
        if center_x1 < center_x2 and center_y1 < center_y2:
            mask_draw.rectangle([center_x1, center_y1, center_x2, center_y2], fill=255)
        
        if radius_top_left > 0 or radius_top_right > 0:
            top_y1 = y1 + min_radius
            top_y2 = y1 + max(radius_top_left, radius_top_right) - 1
            if top_y1 <= top_y2:
                if radius_top_left > 0 and radius_top_right > 0:
                    mask_draw.rectangle([x1, top_y1, x2, top_y2], fill=255)
        
        if radius_bottom_left > 0 or radius_bottom_right > 0:
            bottom_y1 = y2 - max(radius_bottom_left, radius_bottom_right) + 1
            bottom_y2 = y2 - min_radius
            if bottom_y1 <= bottom_y2:
                if radius_bottom_left > 0 and radius_bottom_right > 0:
                    mask_draw.rectangle([x1, bottom_y1, x2, bottom_y2], fill=255)
        
        if radius_top_left > 0 or radius_bottom_left > 0:
            left_x1 = x1 + min_radius
            left_x2 = x1 + max(radius_top_left, radius_bottom_left) - 1
            if left_x1 <= left_x2:
                if radius_top_left > 0 and radius_bottom_left > 0:
                    mask_draw.rectangle([left_x1, y1, left_x2, y2], fill=255)
        
        if radius_top_right > 0 or radius_bottom_right > 0:
            right_x1 = x2 - max(radius_top_right, radius_bottom_right) + 1
            right_x2 = x2 - min_radius
            if right_x1 <= right_x2:
                if radius_top_right > 0 and radius_bottom_right > 0:
                    mask_draw.rectangle([right_x1, y1, right_x2, y2], fill=255)
        
        if fill:
            draw.bitmap((x1, y1), mask, fill=fill)
        
        if outline and width > 0:
            outline_mask = Image.new('L', (x2 - x1 + 1, y2 - y1 + 1), 0)
            outline_draw = ImageDraw.Draw(outline_mask)
            
            outer_bbox = [x1, y1, x2, y2]
            inner_x1 = x1 + width
            inner_y1 = y1 + width
            inner_x2 = x2 - width
            inner_y2 = y2 - width
            
            if inner_x1 < inner_x2 and inner_y1 < inner_y2:
                self._draw_rounded_rectangle(outline_draw, [inner_x1, inner_y1, inner_x2, inner_y2],
                                           max(0, radius_top_left - width), max(0, radius_top_right - width),
                                           max(0, radius_bottom_left - width), max(0, radius_bottom_right - width),
                                           fill=0)
            
            self._draw_rounded_rectangle(outline_draw, outer_bbox,
                                       radius_top_left, radius_top_right,
                                       radius_bottom_left, radius_bottom_right,
                                       fill=255)
            
            draw.bitmap((x1, y1), outline_mask, fill=outline)

    def _render_inset_icon(self, element, size=432):
        """渲染inset图标
        
        基于 Android 16 InsetDrawable 源码实现
        """
        try:
            app_logger.debug("开始渲染inset图标")
            attrs = element.get('attrs', {})
            
            inset_all = attrs.get('inset', '0')
            inset_left = attrs.get('insetLeft', inset_all)
            inset_top = attrs.get('insetTop', inset_all)
            inset_right = attrs.get('insetRight', inset_all)
            inset_bottom = attrs.get('insetBottom', inset_all)
            
            drawable_id = attrs.get('drawable')
            
            parsed_cache = {}
            
            def parse_dimension(val):
                try:
                    cache_key = str(val)
                    if cache_key in parsed_cache:
                        return parsed_cache[cache_key]
                    
                    result = 0
                    if isinstance(val, str):
                        if val.startswith('0x') or val.startswith('@'):
                            dimen_val = self._get_dimen_resource_value(val)
                            if dimen_val:
                                app_logger.debug(f"解析dimen资源: {val} -> {dimen_val}")
                                val = dimen_val
                            else:
                                app_logger.warning(f"无法解析dimen资源: {val}")
                                parsed_cache[cache_key] = 0
                                return 0
                        if val.endswith('%'):
                            percent_val = float(val[:-1])
                            # 如果百分比小于1，可能是aapt2输出错误，应该乘以100
                            if percent_val < 1:
                                percent_val *= 100
                                app_logger.debug(f"修正百分比值: {float(val[:-1])}% -> {percent_val}%")
                            result = percent_val / 100 * size
                        elif val.endswith('dp'):
                            result = float(val[:-2]) * size / 48
                        elif val.endswith('px'):
                            result = float(val[:-2])
                        else:
                            result = float(val) * size / 48
                    parsed_cache[cache_key] = result
                    return result
                except Exception as e:
                    app_logger.warning(f"解析尺寸失败: {val}, 错误: {e}")
                    parsed_cache[str(val)] = 0
                    return 0
            
            left = parse_dimension(inset_left)
            top = parse_dimension(inset_top)
            right = parse_dimension(inset_right)
            bottom = parse_dimension(inset_bottom)
            
            inner_size = int(max(1, size - left - right))
            inner_height = int(max(1, size - top - bottom))
            
            if drawable_id:
                if not drawable_id.startswith('0x'):
                    drawable_id = '0x' + drawable_id.lstrip('@')
                app_logger.debug(f"drawable_id: {drawable_id}")
                inner_img = self._load_layer_image(drawable_id, max(inner_size, inner_height))
                if inner_img:
                    result = Image.new('RGBA', (size, size), (0, 0, 0, 0))
                    result.paste(inner_img, (int(left), int(top)))
                    output = BytesIO()
                    result.save(output, format='PNG')
                    return output.getvalue()
            
            for child in element.get('children', []):
                child_name = child.get('name', '')
                
                try:
                    if child_name == 'vector':
                        data = self._render_vector_icon(child, max(inner_size, inner_height))
                        if data:
                            inner_img = Image.open(BytesIO(data))
                            if inner_img.mode != 'RGBA':
                                inner_img = inner_img.convert('RGBA')
                            result = Image.new('RGBA', (size, size), (0, 0, 0, 0))
                            result.paste(inner_img, (int(left), int(top)))
                            output = BytesIO()
                            result.save(output, format='PNG')
                            return output.getvalue()
                    
                    elif child_name == 'bitmap':
                        bitmap_attrs = child.get('attrs', {})
                        src = bitmap_attrs.get('src')
                        if src:
                            if not src.startswith('0x'):
                                src = '0x' + src.lstrip('@')
                            inner_img = self._load_layer_image(src, max(inner_size, inner_height))
                            if inner_img:
                                result = Image.new('RGBA', (size, size), (0, 0, 0, 0))
                                result.paste(inner_img, (int(left), int(top)))
                                output = BytesIO()
                                result.save(output, format='PNG')
                                return output.getvalue()
                    
                    elif child_name:
                        app_logger.warning(f"未知的inset子元素: {child_name}")
                
                except Exception as e:
                    app_logger.warning(f"处理inset子元素 {child_name} 失败: {e}")
                    continue
            
            return None
        
        except Exception as e:
            app_logger.error(f"渲染失败: {e}")
            return None
    
    def get_call_count(self):
        """获取aapt2调用次数"""
        return self._aapt2_call_count


# ============================================================================
# 批量重命名后台工作线程类
# ============================================================================

class BatchRenameWorker(QThread):
    """
    批量重命名后台工作线程。
    
    在后台线程中执行APK文件的批量重命名操作，避免阻塞主界面。
    
    Signals:
        progress_update: 进度更新信号 (当前索引, 总数, 消息)
        file_processed: 单个文件处理完成信号 (文件名, 状态, 消息)
        finished: 全部处理完成信号 (结果列表, 成功数, 失败数, 跳过数)
    
    Attributes:
        apk_files: APK文件路径列表
        rename_format: 重命名格式模板
        auto_number: 重复文件名是否自动添加编号
        stop_flag: 停止标志，用于中断操作
    """
    progress_update = pyqtSignal(int, int, str)
    file_processed = pyqtSignal(str, str, str)
    finished = pyqtSignal(list, int, int, int)
    
    def __init__(self, apk_files, rename_format, auto_number=False):
        """
        初始化批量重命名工作线程。
        
        Args:
            apk_files: APK文件路径列表
            rename_format: 重命名格式模板
            auto_number: 重复文件名是否自动添加编号，默认False
        """
        super().__init__()
        self.apk_files = apk_files
        self.rename_format = rename_format
        self.auto_number = auto_number
        self.stop_flag = False
    
    def run(self):
        """
        执行批量重命名任务。
        
        遍历APK文件列表，获取每个文件的基本信息，
        根据格式模板生成新文件名，执行重命名操作。
        如果auto_number为True且目标文件名重复，则自动添加编号后缀。
        """
        success_count = 0
        fail_count = 0
        skip_count = 0
        result_messages = []
        invalid_chars = ['\\', '/', ':', '*', '?', '"', '<', '>', '|']
        
        total = len(self.apk_files)
        app_logger.info(f"开始批量重命名，共 {total} 个文件, 自动编号: {self.auto_number}")
        
        for i, apk_path in enumerate(self.apk_files):
            if self.stop_flag:
                result_messages.append(f"已取消: {os.path.basename(apk_path)}")
                fail_count += 1
                self.progress_update.emit(i + 1, total, f"已取消: {os.path.basename(apk_path)}")
                continue
            
            filename = os.path.basename(apk_path)
            
            try:
                self.progress_update.emit(i + 1, total, f"正在解析: {filename}")
                
                info = get_apk_basic_info(apk_path)
                if not info:
                    fail_count += 1
                    msg = f"失败: {filename} - 无法解析APK信息"
                    result_messages.append(msg)
                    self.file_processed.emit(filename, "失败", "无法解析APK信息")
                    continue
                
                new_name = self.rename_format
                format_map = {
                    "app_name": info.get('app_name', ''),
                    "chinese_app_name": info.get('chinese_app_name', ''),
                    "package_name": info.get('package_name', ''),
                    "version_name": info.get('version_name', ''),
                    "version_code": info.get('version_code', ''),
                    "min_sdk_version": info.get('min_sdk_version', ''),
                    "target_sdk_version": info.get('target_sdk_version', ''),
                    "compile_sdk_version": info.get('compile_sdk_version', ''),
                    "arch_support": info.get('arch_support', ''),
                    "permissions_count": str(info.get('permissions_count', 0)),
                    "file_size": info.get('file_size', ''),
                    "file_md5": info.get('file_md5', ''),
                    "cert_md5": info.get('cert_md5', ''),
                }
                
                for key, value in format_map.items():
                    placeholder = "{" + key + "}"
                    new_name = new_name.replace(placeholder, str(value))
                
                for char in invalid_chars:
                    new_name = new_name.replace(char, '_')
                
                if not new_name.strip():
                    new_name = "unnamed"
                
                new_name = new_name.strip()
                
                max_filename_length = 200
                if len(new_name) > max_filename_length:
                    new_name = new_name[:max_filename_length]
                
                new_name = new_name + ".apk"
                new_path = os.path.join(os.path.dirname(apk_path), new_name)
                
                # 初始化自动编号相关变量
                auto_numbered = False
                original_target = None
                
                if apk_path == new_path:
                    skip_count += 1
                    msg = f"跳过: {filename} (文件名相同)"
                    result_messages.append(msg)
                    self.file_processed.emit(filename, "跳过", "文件名相同")
                    app_logger.debug(f"跳过重命名（文件名相同）: {filename}")
                    continue
                
                if os.path.exists(new_path):
                    if self.auto_number:
                        # 自动添加编号以避免文件名重复
                        base_name = new_name[:-4]  # 去除.apk扩展名
                        dir_name = os.path.dirname(apk_path)
                        found_unique = False
                        should_skip = False
                        number = 1
                        original_target = new_name  # 保存原始目标文件名
                        
                        while number <= 9999:
                            numbered_name = f"{base_name}_{number:02d}.apk"
                            numbered_path = os.path.join(dir_name, numbered_name)
                            
                            # 如果编号后的路径与源文件相同，视为跳过
                            if numbered_path == apk_path:
                                skip_count += 1
                                msg = f"跳过: {filename} (自动编号后文件名相同)"
                                result_messages.append(msg)
                                self.file_processed.emit(filename, "跳过", "自动编号后文件名相同")
                                app_logger.debug(f"跳过重命名（自动编号后文件名相同）: {filename}")
                                should_skip = True
                                break
                            
                            # 检查编号后的文件名是否已存在
                            if not os.path.exists(numbered_path):
                                new_name = numbered_name
                                new_path = numbered_path
                                found_unique = True
                                auto_numbered = True  # 标记使用了自动编号
                                app_logger.debug(f"自动编号: {filename} -> {new_name}")
                                break
                            
                            number += 1
                        
                        # 编号后与源文件名相同，跳过该文件
                        if should_skip:
                            continue
                        
                        if not found_unique:
                            # 编号超过上限，无法找到唯一文件名
                            fail_count += 1
                            msg = f"失败: {filename} - 无法生成唯一文件名（编号已超过上限）"
                            result_messages.append(msg)
                            self.file_processed.emit(filename, "失败", "无法生成唯一文件名（编号已超过上限）")
                            app_logger.warning(f"重命名失败（自动编号超过上限）: {filename}")
                            continue
                    else:
                        # 不自动编号，目标文件已存在则重命名失败
                        fail_count += 1
                        msg = f"失败: {filename} - 目标文件已存在"
                        result_messages.append(msg)
                        self.file_processed.emit(filename, "失败", "目标文件已存在")
                        app_logger.warning(f"重命名失败（目标文件已存在）: {filename} -> {new_name}")
                        continue
                
                os.rename(apk_path, new_path)
                success_count += 1
                # 如果使用了自动编号，显示额外提示
                if auto_numbered:
                    msg = f"成功: {filename} -> {new_name} (自动编号，原目标名 {original_target} 已存在)"
                    result_messages.append(msg)
                    self.file_processed.emit(filename, "成功", f"-> {new_name} (自动编号)")
                    app_logger.debug(f"重命名成功（自动编号）: {filename} -> {new_name}")
                else:
                    msg = f"成功: {filename} -> {new_name}"
                    result_messages.append(msg)
                    self.file_processed.emit(filename, "成功", f"-> {new_name}")
                    app_logger.debug(f"重命名成功: {filename} -> {new_name}")
                
            except Exception as e:
                fail_count += 1
                msg = f"失败: {filename} - {str(e)}"
                result_messages.append(msg)
                self.file_processed.emit(filename, "失败", str(e))
        
        app_logger.info(f"批量重命名完成，总计: {total}, 成功: {success_count}, 失败: {fail_count}, 跳过: {skip_count}")
        self.finished.emit(result_messages, success_count, fail_count, skip_count)
    
    def stop(self):
        """停止批量重命名操作"""
        self.stop_flag = True


# ============================================================================
# 管理员权限执行bat脚本工作线程类
# ============================================================================

class ElevatedScriptWorker(QThread):
    """
    管理员权限执行bat脚本工作线程。
    
    在后台线程中执行需要管理员权限的脚本，避免阻塞主界面。
    使用MinSudo提权，通过^转义重定向输出到临时文件。
    
    Signals:
        finished: 执行完成信号 (success, message, output_content)
    
    Attributes:
        script_name: 脚本文件名
        operation_name: 操作名称（用于日志和提示）
        timeout: 超时时间（秒）
    """
    finished = pyqtSignal(bool, str, str)
    
    def __init__(self, script_name, operation_name, timeout=30):
        """
        初始化提权脚本执行工作线程。
        
        Args:
            script_name: 脚本文件名（如 "☆reg_apk.bat"）
            operation_name: 操作名称（如 "关联APK"）
            timeout: 超时时间（秒），默认30秒
        """
        super().__init__()
        self.script_name = script_name
        self.operation_name = operation_name
        self.timeout = timeout
        self.output_file = None
    
    def run(self):
        """
        执行提权脚本。
        
        使用MinSudo提权执行脚本，通过^转义重定向输出到临时文件。
        执行完成后读取临时文件内容并通过finished信号返回结果。
        """
        # 获取脚本路径和MinSudo路径
        script_path = get_long_path(os.path.join(BASE_DIR, self.script_name))
        sudo_path = get_long_path(os.path.join(BASE_DIR, "MinSudo.exe"))
        
        # 检查文件是否存在
        if not os.path.exists(sudo_path):
            app_logger.error(f"缺少sudo组件文件: {sudo_path}")
            self.finished.emit(False, f"缺少sudo组件文件:\n{sudo_path}\n\n请确保程序文件完整。", "")
            return
        
        if not os.path.exists(script_path):
            app_logger.error(f"脚本文件不存在: {script_path}")
            self.finished.emit(False, f"脚本文件不存在:\n{script_path}\n\n请确保程序文件完整。", "")
            return
        
        import tempfile
        # 使用tempfile创建临时文件（自动生成唯一文件名）
        fd, self.output_file = tempfile.mkstemp(suffix=".txt", prefix="apk_helper_")
        os.close(fd)  # 关闭文件描述符，只保留路径
        
        # 构建命令：MinSudo --NoLogo "script.bat"  2^>^&1 ^> "output.txt"
        # 使用 ^ 转义，使重定向符仅用于bat脚本内部
        cmd_str = f'"{sudo_path}" --NoLogo "{script_path}" 2^>^&1 ^> "{self.output_file}"'
        app_logger.debug(f"执行命令: {cmd_str}")
        
        try:
            # 解决32位python程序无法调用64位system32目录下的程序，实际可能无法传递给提权后进程
            custom_env = os.environ.copy()
            x64_system_path = os.path.expandvars(r"%windir%\sysnative")
            custom_env["PATH"] = custom_env["PATH"] + f";{x64_system_path}"
            
            # 执行命令
            # 注意：不使用capture_output=True（即stdout/stderr=PIPE），
            # 因为MinSudo提权后子进程会继承管道句柄，超时后process.communicate()
            # 会因管道未关闭而阻塞，导致实际超时时间远大于设定值。
            # 输出已通过shell重定向(2^>^&1 ^>)写入临时文件，无需管道捕获。
            result = subprocess.run(
                cmd_str, 
                shell=True, 
                text=True, 
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=self.timeout,
                env=custom_env
            )
            
            app_logger.debug(f"{self.script_name} 执行结果: returncode={result.returncode}")
            
            # 等待文件写入完成
            time.sleep(0.6)
            
            # 读取输出文件
            output_content = ""
            if os.path.exists(self.output_file):
                try:
                    # 注意：bat脚本采用gbk编码，所以这里一定要使用gbk编码
                    # 使用newline=''禁用Python自动换行符转换，然后手动处理\r
                    with open(self.output_file, 'r', encoding='gbk', errors='replace', newline='') as f:
                        output_content = f.read()
                    # 移除Windows多余的\r字符
                    output_content = output_content.replace("\r\r\n", "\n").replace("\r", "")
                    output_content_lite = output_content[:500] + "..." if len(output_content) > 500 else output_content
                    app_logger.debug(f"输出文件内容: \n{output_content_lite}")
                except Exception as e:
                    app_logger.warning(f"读取输出文件失败: {e}")
            
            # 判断执行结果：需要满足三个条件
            # 1. 返回值为0
            # 2. 输出文件存在
            # 3. 输出内容不为空
            file_exists = os.path.exists(self.output_file)
            content_not_empty = len(output_content.strip()) > 0
            
            if result.returncode == 0 and file_exists and content_not_empty:
                if "OoooK" in output_content:
                    app_logger.info(f"{self.operation_name}成功")
                    self.finished.emit(True, f"{self.operation_name}成功！", output_content)
                else:
                    app_logger.info(f"{self.operation_name}完成")
                    self.finished.emit(True, f"{self.operation_name}完成！", output_content)
            else:
                # 执行失败，构建详细的错误信息
                error_parts = []
                if result.returncode != 0:
                    # 注意：stdout/stderr已设为DEVNULL，result.stderr为None，
                    # 错误输出已通过shell重定向写入临时文件，可从output_content获取
                    error_parts.append(f"返回码: {result.returncode}")
                if not file_exists:
                    error_parts.append("临时输出文件未创建，程序组件可能未正常运行")
                if not content_not_empty:
                    error_parts.append("临时输出内容为空，程序组件可能未正常运行")
                
                error_msg = "\n".join(error_parts) if error_parts else "未知错误"
                app_logger.warning(f"{self.operation_name}执行失败: {error_msg}")
                self.finished.emit(False, f"执行失败:\n{error_msg}\n\n请确认已赋予管理员权限并杀毒软件放行", output_content)
                
        except subprocess.TimeoutExpired:
            app_logger.error(f"{self.operation_name}操作超时")
            self.finished.emit(False, f"执行操作超时！\n请检查是否有管理员权限确认窗口等待确认或杀毒软件拦截", "")
        except Exception as e:
            app_logger.error(f"{self.operation_name}时发生错误: {e}")
            self.finished.emit(False, f"发生错误:\n{str(e)}\n\n{self.operation_name}可能已经成功完成", "")
        finally:
            self._cleanup_temp_file()
    
    def _cleanup_temp_file(self):
        """清理临时文件"""
        if self.output_file and os.path.exists(self.output_file):
            try:
                os.remove(self.output_file)
                app_logger.debug(f"已清理临时文件: {self.output_file}")
            except Exception as e:
                app_logger.warning(f"清理临时文件失败: {e}")


# ============================================================================
# 管理员权限执行ps1脚本工作线程类
# ============================================================================

class ElevatedPs1Worker(QThread):
    """
    管理员权限执行ps1脚本工作线程。
    
    在后台线程中执行需要管理员权限的PowerShell脚本(.ps1)，避免阻塞主界面。
    使用MinSudo提权，通过-OutputFile参数传递输出文件路径给脚本。
    脚本内部使用Add-Content -LiteralPath输出到文件，支持所有特殊字符路径。
    PowerShell脚本输出使用UTF-8编码。
    
    Signals:
        finished: 执行完成信号 (success, message, output_content)
    
    Attributes:
        script_name: 脚本文件完整路径
        operation_name: 操作名称（用于日志和提示）
        timeout: 超时时间（秒）
    """
    finished = pyqtSignal(bool, str, str)
    
    def __init__(self, script_name, operation_name, timeout=30, extra_params=""):
        """
        初始化提权PowerShell脚本执行工作线程。
        
        Args:
            script_name: 脚本文件完整路径（如 "C:\\path\\to\\install.ps1"）
            operation_name: 操作名称（如 "安装组件"）
            timeout: 超时时间（秒），默认30秒
            extra_params: 额外传递给PowerShell脚本的命令行参数，默认为空字符串
        """
        super().__init__()
        self.script_name = script_name
        self.operation_name = operation_name
        self.timeout = timeout
        self.extra_params = extra_params
        self.output_file = None
    
    def run(self):
        """
        执行提权PowerShell脚本。
        
        使用MinSudo提权执行PowerShell脚本，通过-OutputFile参数传递输出文件路径。
        脚本内部使用Add-Content -LiteralPath输出到文件，支持所有特殊字符路径。
        执行完成后读取输出文件内容并通过finished信号返回结果。
        """
        # 获取脚本路径和MinSudo路径
        # 注意：script_name已经是完整路径，不需要再拼接BASE_DIR
        script_path = get_long_path(self.script_name)
        sudo_path = get_long_path(os.path.join(BASE_DIR, "MinSudo.exe"))
        
        # 检查文件是否存在
        if not os.path.exists(sudo_path):
            app_logger.error(f"缺少sudo组件文件: {sudo_path}")
            self.finished.emit(False, f"缺少sudo组件文件:\n{sudo_path}\n\n请确保程序文件完整。", "")
            return
        
        if not os.path.exists(script_path):
            app_logger.error(f"脚本文件不存在: {script_path}")
            self.finished.emit(False, f"脚本文件不存在:\n{script_path}\n\n请确保程序文件完整。", "")
            return
        
        import tempfile
        # 使用tempfile创建临时文件（自动生成唯一文件名）
        fd, self.output_file = tempfile.mkstemp(suffix=".txt", prefix="apk_helper_")
        os.close(fd)  # 关闭文件描述符，只保留路径
        
        # 构建命令：MinSudo --NoLogo powershell -ExecutionPolicy Bypass -File "script.ps1" -OutputFile "output.txt"
        # 使用 -ExecutionPolicy Bypass 绕过PowerShell执行策略限制
        # 通过 -OutputFile 参数传递输出文件路径给脚本，脚本内部使用 Add-Content -LiteralPath 输出
        # 这种方式支持包含空格、中文、[]等特殊字符的路径
        cmd_str = f'"{sudo_path}" --NoLogo powershell -ExecutionPolicy Bypass -File "{script_path}" -OutputFile "{self.output_file}"'
        # 拼接额外参数（如 -InstallPath "C:\path" 等）
        if self.extra_params:
            cmd_str += f" {self.extra_params}"
        app_logger.debug(f"执行命令: {cmd_str}")
        
        try:
            # 解决32位python程序无法调用64位system32目录下的程序，实际可能无法传递给提权后进程
            custom_env = os.environ.copy()
            x64_system_path = os.path.expandvars(r"%windir%\sysnative")
            custom_env["PATH"] = custom_env["PATH"] + f";{x64_system_path}"
            
            # 执行命令
            # 注意：不使用capture_output=True（即stdout/stderr=PIPE），
            # 因为MinSudo提权后子进程会继承管道句柄，超时后process.communicate()
            # 会因管道未关闭而阻塞，导致实际超时时间远大于设定值。
            # PS1脚本输出通过-OutputFile参数写入临时文件，无需管道捕获。
            result = subprocess.run(
                cmd_str, 
                shell=True, 
                text=True, 
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=self.timeout,
                env=custom_env
            )
            
            app_logger.debug(f"{self.script_name} 执行结果: returncode={result.returncode}")
            
            # 等待文件写入完成
            time.sleep(0.6)
            
            # 读取输出文件
            output_content = ""
            if os.path.exists(self.output_file):
                try:
                    # 注意：PowerShell脚本输出使用UTF-8编码，所以这里使用utf-8编码
                    # 使用newline=''禁用Python自动换行符转换，然后手动处理\r
                    with open(self.output_file, 'r', encoding='utf-8', errors='replace', newline='') as f:
                        output_content = f.read()
                    # 剥离UTF-8 BOM字符（PowerShell 5.x使用-Encoding UTF8写入文件时会自动添加BOM）
                    if output_content.startswith('\ufeff'):
                        output_content = output_content[1:]
                    # 移除Windows多余的\r字符
                    output_content = output_content.replace("\r\r\n", "\n").replace("\r", "")
                    output_content_lite = output_content[:500] + "..." if len(output_content) > 500 else output_content
                    app_logger.debug(f"输出文件内容: \n{output_content_lite}")
                except Exception as e:
                    app_logger.warning(f"读取输出文件失败: {e}")
            
            # 判断执行结果：需要满足三个条件
            # 1. 返回值为0
            # 2. 输出文件存在
            # 3. 输出内容不为空
            file_exists = os.path.exists(self.output_file)
            content_not_empty = len(output_content.strip()) > 0
            
            if result.returncode == 0 and file_exists and content_not_empty:
                # 根据脚本类型判断成功标志
                # install.ps1 成功时输出包含"安装完成"
                # uninstall.ps1 成功时输出包含"卸载完成"
                if "安装完成" in output_content or "卸载完成" in output_content:
                    app_logger.info(f"{self.operation_name}成功")
                    self.finished.emit(True, f"{self.operation_name}成功！", output_content)
                else:
                    app_logger.info(f"{self.operation_name}完成")
                    self.finished.emit(True, f"{self.operation_name}完成！", output_content)
            else:
                # 执行失败，构建详细的错误信息
                error_parts = []
                if result.returncode != 0:
                    # 注意：stdout/stderr已设为DEVNULL，result.stderr为None，
                    # 错误输出已通过-OutputFile参数写入临时文件，可从output_content获取
                    error_parts.append(f"返回码: {result.returncode}")
                if not file_exists:
                    error_parts.append("临时输出文件未创建，程序组件可能未正常运行")
                if not content_not_empty:
                    error_parts.append("临时输出内容为空，程序组件可能未正常运行")
                
                error_msg = "\n".join(error_parts) if error_parts else "未知错误"
                app_logger.warning(f"{self.operation_name}执行失败: {error_msg}")
                self.finished.emit(False, f"执行失败:\n{error_msg}\n\n请确认已赋予管理员权限并杀毒软件放行", output_content)
                
        except subprocess.TimeoutExpired:
            app_logger.error(f"{self.operation_name}操作超时")
            self.finished.emit(False, f"执行操作超时！\n请检查是否有管理员权限确认窗口等待确认或杀毒软件拦截", "")
        except Exception as e:
            app_logger.error(f"{self.operation_name}时发生错误: {e}")
            self.finished.emit(False, f"发生错误:\n{str(e)}\n\n{self.operation_name}可能已经成功完成", "")
        finally:
            self._cleanup_temp_file()
    
    def _cleanup_temp_file(self):
        """清理临时文件"""
        if self.output_file and os.path.exists(self.output_file):
            try:
                os.remove(self.output_file)
                app_logger.debug(f"已清理临时文件: {self.output_file}")
            except Exception as e:
                app_logger.warning(f"清理临时文件失败: {e}")


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
            'arch_support': {},    # CPU架构支持信息
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
        
        try:
            self.parser = APKParser(self.apk_path)
        except Exception as e:
            app_logger.error(f"APKParser初始化失败: {e}")
            self.app_info_finished.emit(self.apk_info, f"APK解析器初始化失败: {e}", True)
            self.signature_info_finished.emit("", None, f"APK解析器初始化失败: {e}", True)
            self.file_info_finished.emit("", f"APK解析器初始化失败: {e}", True)
            self.icon_finished.emit(None, f"APK解析器初始化失败: {e}", self.apk_icon_info, True)
            return
        
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
            icon_thread.start()
            
            # 等待所有线程完成
            app_thread.join()
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
        
        使用aapt2解析APK基本信息，解析完成后发送信号通知主线程。
        """
        try:
            app_logger.debug("开始解析应用信息任务")
            info = self.parser.get_basic_info()
            
            self.apk_info['package_name'] = info.get('package_name', '')
            self.apk_info['version_name'] = info.get('version_name', '')
            self.apk_info['version_code'] = info.get('version_code', '')
            self.apk_info['min_sdk_version'] = info.get('sdk_version', '')
            self.apk_info['target_sdk_version'] = info.get('target_sdk_version', '')
            self.apk_info['compile_sdk_version'] = info.get('compile_sdk_version', '')
            self.apk_info['app_name'] = info.get('application_label', '')
            self.apk_info['chinese_app_name'] = info.get('application_label_zh', '') or info.get('application_label', '')
            self.apk_info['permissions'] = self.parser.get_permissions()
            self.apk_info['arch_support'] = self.parser.analyze_arch_support()
            self.apk_info['locales'] = info.get('locales', [])  # 获取支持的语言列表
            
            app_logger.debug(f"包名: {self.apk_info['package_name']}, 版本: {self.apk_info['version_name']}")
            app_logger.debug(f"权限数量: {len(self.apk_info['permissions'])}")
            app_logger.debug(f"架构支持: {self.apk_info['arch_support'].get('display_text', '未知')}")
            app_logger.debug(f"支持语言: {len(self.apk_info['locales'])} 种")
            
            self.app_info_finished.emit(self.apk_info, "", True)
        except Exception as e:
            app_logger.error(f"失败: {e}")
            self.app_info_finished.emit(self.apk_info, f"解析应用信息失败: {e}", True)

    def _parse_signature_info_task(self):
        """
        解析签名信息的任务。
        
        获取APK签名信息，解析完成后发送信号通知主线程。
        """
        try:
            app_logger.debug("开始解析签名信息任务")
            self.signature_info_finished.emit("正在解析签名信息...", None, "", False)
            
            sig_info = self.parser.get_signature_info()
            self.certs = sig_info.get('certificates', [])
            
            basic_info = self.parser.get_basic_info()
            package_name = basic_info.get('package_name', '') or self.apk_info.get('package_name', '')
            
            app_logger.debug(f"V1: {sig_info['v1']}, V2: {sig_info['v2']}, V3: {sig_info['v3']}")
            
            signature_lines = []
            signature_lines.append(f"应用包名: {package_name}")
            signature_lines.append(f"V1签名状态: {'已签名' if sig_info['v1'] else '未签名'}")
            signature_lines.append(f"V2签名状态: {'已签名' if sig_info['v2'] else '未签名'}")
            signature_lines.append(f"V3签名状态: {'已签名' if sig_info['v3'] else '未签名'}")
            
            certificates = sig_info.get('certificates', [])
            if certificates:
                signature_lines.append(f"\n++++存在 {len(certificates)} 个证书++++")
                app_logger.debug(f"找到 {len(certificates)} 个证书")
                
                for i, cert in enumerate(certificates, 1):
                    signature_lines.append(f"\n证书 {i}:")
                    if cert.get('subject'):
                        signature_lines.append(f"主题: {cert['subject']}")
                    if cert.get('issuer'):
                        signature_lines.append(f"颁发者: {cert['issuer']}")
                    if cert.get('serial_number'):
                        signature_lines.append(f"序列号: {cert['serial_number']}")
                    if cert.get('signature_algorithm'):
                        signature_lines.append(f"签名算法: {cert['signature_algorithm']}")
                    if cert.get('not_before'):
                        signature_lines.append(f"有效期从: {cert['not_before']}")
                    if cert.get('not_after'):
                        signature_lines.append(f"有效期至: {cert['not_after']}")
                    
                    # 计算证书的各种哈希值
                    signature_lines.append("\n证书指纹(哈希值):")
                    signature_lines.append(f"MD5: {cert.get('md5', 'N/A')}")
                    signature_lines.append(f"SHA1: {cert.get('sha1', 'N/A')}")
                    signature_lines.append(f"SHA256: {cert.get('sha256', 'N/A')}")
                    signature_lines.append(f"SHA512: {cert.get('sha512', 'N/A')}")
            else:
                signature_lines.append("\n未找到证书")
                app_logger.warning("未找到证书")
            
            signature_info = '\n'.join(signature_lines)
            self.signature_info_finished.emit(signature_info, self.certs, "", True)
        except Exception as e:
            app_logger.error(f"失败: {str(e)}")
            self.signature_info_finished.emit("", self.certs, f"解析签名信息失败: {str(e)}", True)

    def _parse_file_info_task(self):
        """解析文件信息的任务"""
        try:
            app_logger.debug("开始解析文件信息任务")
            self.file_info_finished.emit("正在解析文件信息...", "", False)
            
            file_info = self.parser.get_file_info()
            file_size = file_info.get('size', 0)
            size_mb = file_size / (1024 * 1024)
            
            app_logger.debug(f"文件大小: {size_mb:.2f} MB")
            
            info = f"文件路径: {file_info.get('path', '')}\n"
            info += f"文件 MD5: {file_info.get('md5', 'N/A')}\n"
            info += f"文件大小: {file_size:,} 字节 ({size_mb:.2f} MB)"
            
            self.file_info_finished.emit(info, "", True)
        except Exception as e:
            app_logger.error(f"失败: {str(e)}")
            self.file_info_finished.emit("", f"解析文件信息失败: {str(e)}", True)

    def _parse_icon_task(self):
        """解析图标的任务
        
        icon_sure 含义:
            True - 图标是通过标准方式（manifest/badging/资源ID）确定的默认图标
            False - 图标是通过推测/猜测方式得到的（如修改后缀名模糊匹配等），可能不是准确的默认图标
        """
        try:
            app_logger.debug("开始解析应用图标任务")
            self.icon_finished.emit(None, "", self.apk_icon_info, False)
            
            icon_data, icon_sure = self.parser.get_icon_image()
            self.apk_icon_info['icon_sure'] = icon_sure
            
            if icon_data:
                app_logger.debug(f"成功获取图标数据, 大小: {len(icon_data)} 字节, icon_sure={icon_sure}")
            else:
                app_logger.warning("未找到图标")
            
            self.icon_finished.emit(icon_data, "" if icon_data else "未找到图标", self.apk_icon_info, True)
        except Exception as e:
            app_logger.error(f"失败: {str(e)}")
            self.icon_finished.emit(None, f"解析图标失败: {str(e)}", self.apk_icon_info, True)

# ============================================================================
# 自定义UI控件类
# ============================================================================

# 自定义表格类，继承 QTableWidget
class CustomTableWidget(QTableWidget):
    """
    自定义表格控件，继承自QTableWidget。
    
    重写了minimumSizeHint方法，解决表格控件无法缩小到很小尺寸的问题。
    适用于需要灵活调整大小的界面布局。
    支持 Ctrl+C 复制选中单元格内容。
    支持自定义行间分隔符和列间隔符。
    
    Class Variables:
        row_separator: 行间分隔符（默认换行符 \n）
        col_separator: 列间隔符（默认制表符 \t）
    """
    
    row_separator = "\n"
    col_separator = "\t"
    
    def __init__(self, parent=None):
        """
        初始化自定义表格控件。
        
        Args:
            parent: 父控件
        """
        super().__init__(parent)
        # 应用表格样式表
        self.setStyleSheet(TABLE_WIDGET_STYLE)
        # 设置允许的最小行高（改为10px允许更紧凑的行高）
        self.verticalHeader().setMinimumSectionSize(10)
        # 设置默认行高（紧凑布局）
        self.verticalHeader().setDefaultSectionSize(14)
        # 设置水平表头最小行高
        self.horizontalHeader().setMinimumHeight(20)
        # 设置水平表头文字省略模式（右侧显示...）
        self.horizontalHeader().setTextElideMode(Qt.ElideRight)

    
    def minimumSizeHint(self):
        """
        返回自定义的最小尺寸提示。
        
        Returns:
            QSize: 最小尺寸，设置为20x20像素
        """
        return QSize(20, 20)
    
    def keyPressEvent(self, event):
        """
        处理键盘按键事件。
        
        支持 Ctrl+C 复制选中单元格的内容到剪贴板。
        复制格式为制表符分隔的多行文本，可直接粘贴到Excel等软件。
        
        Args:
            event: QKeyEvent键盘事件对象
        """
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_C:
            selected_items = self.selectedItems()
            if not selected_items:
                super().keyPressEvent(event)
                return
            
            rows = set()
            cols = set()
            item_dict = {}
            
            for item in selected_items:
                row = item.row()
                col = item.column()
                rows.add(row)
                cols.add(col)
                item_dict[(row, col)] = item.text()
            
            sorted_rows = sorted(rows)
            sorted_cols = sorted(cols)
            
            copied_lines = []
            for row in sorted_rows:
                row_data = []
                for col in sorted_cols:
                    row_data.append(item_dict.get((row, col), ""))
                copied_lines.append(self.col_separator.join(row_data))
            
            if copied_lines:
                clipboard = QApplication.clipboard()
                clipboard.setText(self.row_separator.join(copied_lines))
                event.accept()
            else:
                super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)
    
    def contextMenuEvent(self, event):
        """
        处理右键菜单事件。
        
        提供复制和全选的右键菜单选项。
        
        Args:
            event: QContextMenuEvent右键菜单事件对象
        """
        menu = QMenu(self)
        
        # 创建复制动作（显示快捷键提示）
        copy_action = menu.addAction("复制\tCtrl+C")
        copy_action.setToolTip("复制选中单元格内容到剪贴板")
        
        # 创建全选动作（显示快捷键提示）
        select_all_action = menu.addAction("全选\tCtrl+A")
        select_all_action.setToolTip("选中表格中所有单元格")
        
        # 检查是否有选中的单元格
        selected_items = self.selectedItems()
        if not selected_items:
            copy_action.setEnabled(False)
        
        # 检查表格是否为空
        if self.rowCount() == 0 or self.columnCount() == 0:
            select_all_action.setEnabled(False)
        
        # 显示菜单并获取用户选择
        action = menu.exec_(event.globalPos())
        
        if action == copy_action and selected_items:
            # 执行复制操作（复用 keyPressEvent 中的逻辑）
            rows = set()
            cols = set()
            item_dict = {}
            
            for item in selected_items:
                row = item.row()
                col = item.column()
                rows.add(row)
                cols.add(col)
                item_dict[(row, col)] = item.text()
            
            sorted_rows = sorted(rows)
            sorted_cols = sorted(cols)
            
            copied_lines = []
            for row in sorted_rows:
                row_data = []
                for col in sorted_cols:
                    row_data.append(item_dict.get((row, col), ""))
                copied_lines.append(self.col_separator.join(row_data))
            
            if copied_lines:
                clipboard = QApplication.clipboard()
                clipboard.setText(self.row_separator.join(copied_lines))
        
        elif action == select_all_action:
            # 执行全选操作
            self.selectAll()

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
        self.setGeometry(100, 100, 400, 520)  # 整个主窗口尺寸(左距离, 上距离, 宽度, 高度)，
        
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
            'locales': [],    # 支持的语言列表
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
        top_layout.addWidget(icon_group, 0, Qt.AlignTop)  # 图标区域居上对齐
        
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
        
        self.copy_custom_info_button = QPushButton("复制自定义信息")
        self.copy_custom_info_button.setMinimumHeight(button1_Height)
        self.copy_custom_info_button.setFixedWidth(button1_width)
        self.copy_custom_info_button.setToolTip("按照自定义格式复制APK信息到剪贴板，\n请在更多设置中设定信息格式模版")
        self.copy_custom_info_button.clicked.connect(self.copy_custom_info)
        button_layout.addWidget(self.copy_custom_info_button, 0, 1)
        self.copy_custom_info_button.setEnabled(False)
        
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
        
        self.more_settings_button = QPushButton("更多")
        self.more_settings_button.setMinimumHeight(button1_Height)
        self.more_settings_button.setFixedWidth(about_button_width)
        self.more_settings_button.setToolTip("打开更多设置窗口")
        self.more_settings_button.clicked.connect(self.show_more_settings)
        right_col2_layout.addWidget(self.more_settings_button)
        
        # 添加置顶复选框
        self.always_on_top_checkbox = QCheckBox("置顶")
        self.always_on_top_checkbox.setMinimumHeight(button1_Height)
        self.always_on_top_checkbox.setToolTip("勾选后使窗口始终保持在最顶层")
        self.always_on_top_checkbox.stateChanged.connect(self.toggle_always_on_top)
        self.always_on_top_checkbox.setStyleSheet("QCheckBox::indicator { width: 12px; height: 12px; } QCheckBox { spacing: 2px; }")
        right_col2_layout.addWidget(self.always_on_top_checkbox)
        
        button_layout.addWidget(right_col2_widget, 2, 1)
        
        
        # 添加拖拽提示文本
        drag_hint = QLabel("提示: 拖拽APK文件到窗口即可查看信息")
        drag_hint.setAlignment(Qt.AlignCenter)
        drag_hint.setStyleSheet("color: blue;")
        button_layout.addWidget(drag_hint, 3, 0, 1, 2)  # 横跨两列
        
        button_layout.setRowStretch(4, 1)
        button_layout.setColumnStretch(2, 1)
        
        # 将按钮容器添加到顶部布局
        top_layout.addWidget(button_container)
        top_layout.setContentsMargins(0, 0, 0, 0)  # 左、上、右、下的边距值
        # 将top_widget添加到splitter中，支持与应用信息区域拖拽
        self.main_splitter.addWidget(top_widget)
        
        
        #### 应用基本信息区域（使用选项卡包含基本信息和权限信息）
        self.app_info_group = QGroupBox("")
        app_info_layout = QVBoxLayout(self.app_info_group)
        app_info_layout.setContentsMargins(3, 3, 3, 3)    # 内部组件的间距
        
        # 创建选项卡部件
        self.app_info_tab_widget = QTabWidget()
        self.app_info_tab_widget.setDocumentMode(True)
        
        # === 基本信息选项卡 ===
        basic_info_widget = QWidget()
        basic_info_layout = QVBoxLayout(basic_info_widget)
        basic_info_layout.setContentsMargins(0, 0, 0, 0)
        
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
        
        basic_info_layout.addWidget(self.app_info_stacked_widget)
        self.app_info_tab_widget.addTab(basic_info_widget, "基本信息")
        
        # === 权限信息选项卡 ===
        permission_widget = QWidget()
        permission_layout = QVBoxLayout(permission_widget)
        permission_layout.setContentsMargins(0, 0, 0, 0)
        
        self.permission_table = CustomTableWidget()
        self.permission_table.setColumnCount(2)  # 两列的表格
        self.permission_table.setHorizontalHeaderLabels(["", ""])  # 列名均为空
        self.permission_table.verticalHeader().setVisible(False)  # 行名不显示
        # self.permission_table.horizontalHeader().setVisible(False)
        header = self.permission_table.horizontalHeader()
        header.setFixedHeight(2)  # 表头高度设为很小，方便拖拽
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        
        # 设置表格为可选择但不可编辑，支持单元格选择和文本拖选
        self.permission_table.setEditTriggers(self.permission_table.NoEditTriggers)
        self.permission_table.setSelectionBehavior(self.permission_table.SelectItems)  # 支持单元格选择
        self.permission_table.setSelectionMode(self.permission_table.ExtendedSelection)  # 支持扩展选择
        self.permission_table.setTextElideMode(Qt.ElideNone)  # 不省略文本

        # 增加垂直滚动条
        self.permission_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.permission_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        permission_layout.addWidget(self.permission_table)
        self.app_info_tab_widget.addTab(permission_widget, "权限信息")
        
        app_info_layout.addWidget(self.app_info_tab_widget)
        self.main_splitter.addWidget(self.app_info_group)
        
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
        self.show_signature_details_btn = QPushButton("..")
        self.show_signature_details_btn.setFixedWidth(24)
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
        self.main_splitter.setSizes([160, 500, 200, 140])
        
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
        self.permission_table.setColumnWidth(0, 230)  # 设置第一列的列宽
        
        # 应用基本信息：设置应用基本信息表格的属性名
        properties = [
            "应用包名",
            "默认应用名",
            "中文应用名",
            "版本号",
            "内部版本号",
            "CPU架构",
            "最低兼容SDK版本",
            "目标适配SDK版本",
            "编译构建SDK版本",
            "支持语言",
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
        app_info_sh = int(1000 * (total_height+36) / height)  # 多增加一定数量的像素作为区域框额外的高度。这样换算出来实际像素对应的高度比例值
        # app_logger.debug(f"main_splitter高度={height}像素, app_info_table高度比例值={app_info_sh}")
        self.main_splitter.setSizes([160, app_info_sh, 700-app_info_sh, 140])  # 图标区域固定，动态调整应用信息、签名信息区域，最后文件信息固定。最终按比例分摊各区域。

    def center_window(self):
        """
        将窗口显示在屏幕中心。
        
        使用QDesktopWidget获取屏幕可用区域，
        计算窗口居中位置并移动窗口。
        如果窗口高度或宽度超出屏幕可用区域，则调整窗口位置使标题栏可见。
        高度和宽度分别独立处理：
        - 垂直方向：高度超出则顶部对齐，否则垂直居中
        - 水平方向：宽度超出则左对齐，否则水平居中
        """
        # 使用QDesktopWidget来获取屏幕尺寸，更可靠
        desktop = QDesktopWidget()
        # 获取屏幕尺寸
        screen_rect = desktop.availableGeometry()
        # 获取窗口尺寸
        window_rect = self.frameGeometry()
        
        # 垂直方向处理：高度超出则顶部对齐，否则垂直居中
        if window_rect.height() >= screen_rect.height():
            # 窗口高度大于等于屏幕可用高度，顶部对齐屏幕顶部（确保标题栏可见）
            window_rect.moveTop(screen_rect.top())
        else:
            # 窗口高度小于屏幕可用高度，垂直居中
            new_y = screen_rect.top() + (screen_rect.height() - window_rect.height()) // 2
            window_rect.moveTop(new_y)
        
        # 水平方向处理：宽度超出则左对齐，否则水平居中
        if window_rect.width() >= screen_rect.width():
            # 窗口宽度大于等于屏幕可用宽度，左对齐屏幕左边
            window_rect.moveLeft(screen_rect.left())
        else:
            # 窗口宽度小于屏幕可用宽度，水平居中
            new_x = screen_rect.left() + (screen_rect.width() - window_rect.width()) // 2
            window_rect.moveLeft(new_x)
        
        # 设置窗口位置
        self.move(window_rect.topLeft())

    def showEvent(self, event):
        """
        窗口显示事件处理。
        
        首次显示时自动调整窗口以适应屏幕大小：
        1. 首先尝试压缩窗口高度，使整个窗口在屏幕显示范围内
        2. 压缩到最矮后仍不能容纳时，确保标题行在屏幕可见范围内
        """
        super().showEvent(event)
        if not hasattr(self, '_screen_adjusted'):
            self._screen_adjusted = True
            # 使用QTimer确保窗口完全显示后再调整，避免布局计算不完整
            QTimer.singleShot(0, self.adjust_to_screen)

    def adjust_to_screen(self):
        """
        自动调整窗口以适应屏幕大小。
        
        调整策略：
        1. 首先尝试压缩窗口高度，使整个窗口在屏幕显示范围内
        2. 压缩到最矮后仍不能容纳整个软件界面时，确保软件标题行在屏幕显示范围内，
           剩余部分允许超出屏幕底部
        
        高度和宽度分别独立处理：
        - 垂直方向：高度超出则压缩高度或顶部对齐，否则垂直居中
        - 水平方向：宽度超出则左对齐，否则水平居中
        
        使用QScreen获取屏幕可用区域（排除任务栏），计算窗口与屏幕的适配关系。
        """
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        
        screen_rect = screen.availableGeometry()
        frame_rect = self.frameGeometry()
        
        # 检查窗口是否完全在屏幕可用区域内（包括水平和垂直方向）
        if (frame_rect.left() >= screen_rect.left() and 
            frame_rect.right() <= screen_rect.right() and
            frame_rect.top() >= screen_rect.top() and 
            frame_rect.bottom() <= screen_rect.bottom()):
            return
        
        app_logger.debug(f"窗口尺寸({frame_rect.width()}x{frame_rect.height()})超出屏幕可用区域({screen_rect.width()}x{screen_rect.height()})，开始自动调整")
        
        # 策略1：压缩窗口高度以适应屏幕（仅在高度超出时执行）
        height_exceeded = frame_rect.height() > screen_rect.height()
        
        if height_exceeded:
            # 计算窗口边框额外高度（标题栏+边框）
            frame_extra_height = frame_rect.height() - self.height()
            # 目标内容区高度 = 屏幕可用高度 - 边框额外高度 - 边距
            margin = 10
            target_content_height = screen_rect.height() - frame_extra_height - margin
            
            if target_content_height > 0:
                app_logger.debug(f"策略1：压缩窗口内容区高度至 {target_content_height} 像素")
                self.resize(self.width(), target_content_height)
                # 强制处理事件，确保窗口尺寸更新
                QApplication.processEvents()
                
                # 重新获取窗口尺寸
                frame_rect = self.frameGeometry()
        
        # 策略2：调整窗口位置（高度和宽度分别独立处理）
        frame_rect = self.frameGeometry()
        
        # 垂直方向处理：高度超出则顶部对齐，否则垂直居中
        if frame_rect.height() > screen_rect.height():
            # 窗口高度大于屏幕可用高度，顶部对齐屏幕顶部（确保标题栏可见）
            app_logger.debug("策略2：窗口高度大于屏幕可用高度，调整窗口位置")
            new_y = screen_rect.top()
        else:
            # 窗口高度小于等于屏幕可用高度，垂直居中
            new_y = screen_rect.top() + (screen_rect.height() - frame_rect.height()) // 2
        
        # 水平方向处理：宽度超出则左对齐，否则水平居中
        if frame_rect.width() > screen_rect.width():
            # 窗口宽度大于屏幕可用宽度，左对齐屏幕左边
            app_logger.debug("策略2：窗口宽度大于屏幕可用宽度，调整窗口位置")
            new_x = screen_rect.left()
        else:
            # 窗口宽度小于等于屏幕可用宽度，水平居中
            new_x = screen_rect.left() + (screen_rect.width() - frame_rect.width()) // 2
        
        self.move(new_x, new_y)

    def display_app_info(self):
        """
        显示应用基本信息。
        
        将apk_info中的信息显示在基本信息表格中，包括：
        包名、应用名、中文应用名、版本号、内部版本号、CPU架构、SDK版本等。
        SDK版本会自动转换为对应的Android版本名称。
        CPU架构信息独立成一行显示。
        """
        # 切换到基本信息选项卡
        self.app_info_tab_widget.setCurrentIndex(0)
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

        # 架构支持信息处理
        arch_support = self.apk_info.get('arch_support', {})
        arch_display_text = arch_support.get('display_text', '')
        arch_tooltip = self._build_arch_tooltip(arch_support)

        # 添加到表格
        self.add_table_row(self.app_info_table, "应用包名", package_name)
        self.add_table_row(self.app_info_table, "默认应用名", default_app_name)
        self.add_table_row(self.app_info_table, "中文应用名", chinese_app_name)
        self.add_table_row(self.app_info_table, "版本号", version_name)
        self.add_table_row(self.app_info_table, "内部版本号", version_code)
        self.add_table_row(self.app_info_table, "CPU架构", arch_display_text if arch_display_text else "-", arch_tooltip)
        self.add_table_row(self.app_info_table, "最低兼容SDK版本", min_sdk_display)
        self.add_table_row(self.app_info_table, "目标适配SDK版本", target_sdk_display)
        self.add_table_row(self.app_info_table, "编译构建SDK版本", compile_sdk_display)
        
        # 添加支持语言行（带查看按钮）
        self._add_locale_row()
        
        # 根据内容自动调整第一列列宽
        self.app_info_table.resizeColumnToContents(0)
        
        # 调整表格高度
        total_height = 0
        for i in range(self.app_info_table.rowCount()):
            total_height += self.app_info_table.rowHeight(i)
        self.app_info_table.setMaximumHeight(total_height+2)  # 设定表格最大高度

    def _add_locale_row(self):
        """
        添加支持语言行到基本信息表格。
        
        该行显示语言数量和一个"查看"按钮，点击按钮弹出语言列表详情窗口。
        """
        # 获取语言列表
        locales = self.apk_info.get('locales', [])
        locale_count = len(locales)
        
        # 创建行
        row = self.app_info_table.rowCount()
        self.app_info_table.insertRow(row)
        
        # 第一列：属性名
        self.app_info_table.setItem(row, 0, QTableWidgetItem("支持语言"))
        
        # 第二列：设置文本内容（用于复制功能）
        if locale_count > 0:
            locale_text = f"{locale_count} 种语言"
        else:
            locale_text = "未知"
        self.app_info_table.setItem(row, 1, QTableWidgetItem(locale_text))
        
        # 如果有语言，添加查看按钮（紧挨文本右侧）
        if locale_count > 0:
            # 计算文本宽度
            font = self.app_info_table.font()
            fm = QFontMetrics(font)
            text_width = fm.horizontalAdvance(locale_text)
            
            # 创建只包含按钮的透明控件
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(text_width + 10, 0, 0, 0)  # 左边距 = 文本宽度 + 间距
            btn_layout.setSpacing(0)
            
            # 查看按钮
            view_btn = QPushButton("查看")
            view_btn.setFixedSize(40, 20)
            view_btn.setToolTip("点击查看详细语言列表")
            view_btn.clicked.connect(lambda: self._show_locale_dialog(locales))
            btn_layout.addWidget(view_btn)
            
            btn_layout.addStretch()
            
            self.app_info_table.setCellWidget(row, 1, btn_widget)
        
        self.app_info_table.resizeRowToContents(row)
    
    def _show_locale_dialog(self, locales):
        """
        显示语言列表详情对话框。
        
        Args:
            locales: 语言代码列表
        """
        dialog = LocaleListDialog(locales, self)
        dialog.exec_()

    def _build_arch_tooltip(self, arch_support):
        """
        构建架构信息的工具提示文本。
        
        Args:
            arch_support: 架构支持信息字典
            
        Returns:
            str: 工具提示文本，如果无架构信息则返回None
        """
        if not arch_support:
            return None
        
        display_text = arch_support.get('display_text', '')
        native_codes = arch_support.get('native_codes', [])
        
        if not display_text:
            return None
        
        if display_text == '纯应用':
            return "该应用无原生库(Native Library)\n使用纯Java/Kotlin代码编写\n可在所有安卓设备上运行"
        
        if display_text == '未知':
            other_archs = arch_support.get('other_archs', [])
            if other_archs:
                return f"检测到未知架构:\n{', '.join(other_archs)}\n请查看日志了解详情"
            return "无法识别的CPU架构"
        
        tooltip_parts = [f"支持的CPU架构:\n{display_text}", ""]
        
        if native_codes:
            tooltip_parts.append("原始ABI列表:")
            for abi in native_codes:
                abi_desc = self._get_abi_description(abi)
                tooltip_parts.append(f"  - {abi}: {abi_desc}")
        
        return "\n".join(tooltip_parts)
    
    def _get_abi_description(self, abi):
        """
        获取ABI的描述信息。
        
        Args:
            abi: ABI名称
            
        Returns:
            str: ABI描述
        """
        abi_descriptions = {
            'armeabi': 'ARM 32位 (旧架构)',
            'armeabi-v7a': 'ARM 32位 (旧架构)',
            'arm64-v8a': 'ARM 64位 (主流架构)',
            'x86': 'x86 32位 (旧架构)',
            'x86_64': 'x86 64位 (非主流架构)',
            'mips': 'MIPS 32位 (旧架构)',
            'mips64': 'MIPS 64位 (旧架构)',
            'riscv64': 'RISC-V 64位 (非主流新兴架构)'
        }
        return abi_descriptions.get(abi, '未知架构')

    def show_parsing_status(self, message):
        """
        显示解析状态信息。
        
        在解析过程中显示状态提示，切换到内容框视图，
        以蓝色居中文字显示状态信息。
        
        Args:
            message: 要显示的状态信息文本
        """
        # 切换到基本信息选项卡
        self.app_info_tab_widget.setCurrentIndex(0)
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
        # 切换到基本信息选项卡
        self.app_info_tab_widget.setCurrentIndex(0)
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
            # 根据内容自动调整第二列宽度
            self.permission_table.resizeColumnToContents(1)
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
        
        # 根据内容自动调整第二列宽度
        self.permission_table.resizeColumnToContents(1)

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

    def add_table_row(self, table, key, value, tooltip=None):
        """
        向指定表格添加一行数据。
        
        Args:
            table: QTableWidget表格控件
            key: 第一列的键名
            value: 第二列的值
            tooltip: 可选，工具提示文本
        """
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem(key))
        value_item = QTableWidgetItem(str(value))
        if tooltip:
            value_item.setToolTip(tooltip)
        table.setItem(row, 1, value_item)
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
        self.more_settings_button.setEnabled(False)    # 更多按钮
        self.always_on_top_checkbox.setEnabled(False)    # 窗体置顶复选框
        self.copy_custom_info_button.setEnabled(False)    # 复制自定义信息按钮
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
        self.more_settings_button.setEnabled(True)    # 更多按钮
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

    def check_apk_association(self):
        r"""
        检查APK文件是否已关联到当前程序。
        
        通过检查Windows注册表中的相关键值来判断关联状态，判断规则：
        1. HKCR\ApkFile.apkhelper 必须存在
        2. 如果存在 HKCU\...\FileExts\.apk\UserChoice 的 Progid 键，则必须为 ApkFile.apkhelper
           如果存在 HKCU\...\FileExts\.apk\UserChoiceLatest\ProgId 的 ProgId 键，则必须为 ApkFile.apkhelper
        3. 如果不存在 Progid 键，则 HKCR\.apk 默认键值必须是 ApkFile.apkhelper 或 Applications\apk_helper.exe
        
        Returns:
            bool: 已关联APK返回True，否则返回False
        """
        try:
            # 条件1：检查HKCR\ApkFile.apkhelper是否存在
            condition1 = False
            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "ApkFile.apkhelper", 0, winreg.KEY_READ):
                    condition1 = True
                    app_logger.debug("条件1满足: 找到 HKCR\\ApkFile.apkhelper 注册表项")
            except OSError as e:
                app_logger.debug(f"条件1不满足: 未找到 HKCR\\ApkFile.apkhelper 注册表项: {e}")
            
            # 如果条件1不满足，直接返回False
            if not condition1:
                return False
            
            # 条件2：检查Progid是否存在以及键值
            condition2 = True
            goto3 = False
            
            #### 先检查 UserChoice 的 Progid 是否存在
            user_choice_progid = None
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.apk\UserChoice", 0, winreg.KEY_READ) as key:
                    try:
                        progid_val, progid_type = winreg.QueryValueEx(key, "Progid")
                        user_choice_progid = progid_val
                        app_logger.debug(f"找到 UserChoice Progid: {progid_val}")
                    except OSError as e:
                        app_logger.debug(f"UserChoice 中无 Progid 项: {e}")
            except OSError as e:
                app_logger.debug(f"不存在 UserChoice 注册表项: {e}")
            
            # 根据UserChoice的Progid是否存在，采用不同的判断逻辑
            if user_choice_progid is not None:
                # 如果存在Progid，则必须为ApkFile.apkhelper或apk_helper.exe
                if user_choice_progid == "ApkFile.apkhelper" or user_choice_progid == r"Applications\apk_helper.exe":
                    app_logger.debug(f"条件2满足1: UserChoice Progid = {user_choice_progid}")
                else:
                    condition2 = False
                    app_logger.debug(f"条件2不满足: UserChoice Progid = {user_choice_progid}")
                    return False
            else:
                goto3 = True
            
            # 使用全局变量 WINDOWS_BUILD_VERSION（已在程序启动时初始化）
            # 只有 Win11 24H2+ (≥26100) 才支持 UserChoiceLatest
            if WINDOWS_BUILD_VERSION >= 26100:
                app_logger.debug(f"检测到系统版本高于 Win11 24H2 : {WINDOWS_BUILD_VERSION}")
                goto3 = False

                #### 再检查 UserChoiceLatest 的 Progid 是否存在
                user_choice_progid_Latest = None
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.apk\UserChoiceLatest\ProgId", 0, winreg.KEY_READ) as key:
                        try:
                            progid_val, progid_type = winreg.QueryValueEx(key, "ProgId")
                            user_choice_progid_Latest = progid_val
                            app_logger.debug(f"找到 UserChoiceLatest Progid: {progid_val}")
                        except OSError as e:
                            app_logger.debug(f"UserChoiceLatest 中无 Progid 项: {e}")
                except OSError as e:
                    app_logger.debug(f"不存在 UserChoiceLatest 注册表项: {e}")
                
                # 根据UserChoiceLatest的Progid是否存在，采用不同的判断逻辑
                if user_choice_progid_Latest is not None:
                    # 如果存在Progid，则必须为ApkFile.apkhelper或apk_helper.exe
                    if user_choice_progid_Latest == "ApkFile.apkhelper" or user_choice_progid_Latest == r"Applications\apk_helper.exe":
                        app_logger.debug(f"条件2满足2: UserChoiceLatest Progid = {user_choice_progid_Latest}")
                    else:
                        condition2 = False
                        app_logger.debug(f"条件2不满足: UserChoiceLatest Progid = {user_choice_progid_Latest}")
                        return False
                else:
                    goto3 = True
            
            condition3 = False if goto3 else True    # 不检查时，默认为True
            if goto3:
                # 如果不存在Progid，则检查HKCR\.apk默认键值是否是ApkFile.apkhelper
                try:
                    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r".apk", 0, winreg.KEY_READ) as key:
                        try:
                            default_val, default_type = winreg.QueryValueEx(key, "")
                            if default_val == "ApkFile.apkhelper":
                                condition3 = True
                                app_logger.debug(f"条件3满足: HKCR\\.apk 默认键值 = {default_val}")
                            else:
                                app_logger.debug(f"条件3不满足: HKCR\\.apk 默认键值 = {default_val}")
                        except OSError as e:
                            app_logger.debug(f"条件3不满足: HKCR\\.apk 无默认键值: {e}")
                except OSError as e:
                    app_logger.debug(f"条件3不满足: 无法打开 HKCR\\.apk 注册表项: {e}")
            
            # 所有条件都满足才算已关联
            result = condition1 and condition2 and condition3
            app_logger.debug(f"检查结果: 条件1={condition1}, 条件2={condition2}, 条件3={condition3}, 关联状态={result}")
            return result
        except ImportError:
            # 非Windows系统，不支持注册表操作
            app_logger.warning("当前系统不是Windows系统")
            return False
        except Exception as e:
            app_logger.warning(f"检查APK关联状态时出错: {e}")
            return False
    
    def reg_apk(self):
        """
        执行关联APK脚本。
        
        调用外部批处理脚本注册APK文件关联，使双击APK文件时使用本程序打开。
        需要管理员权限执行，使用异步方式避免界面卡死。
        """
        # 显示执行提示
        self._show_executing_dialog("注册关联APK", "正在执行注册关联APK操作...\n\n如果弹出管理员权限确认窗口，请点击\"是\"确认。")
        
        # 创建异步工作线程
        self._reg_apk_worker = ElevatedScriptWorker("☆reg_apk.bat", "注册关联APK", timeout=30)
        self._reg_apk_worker.finished.connect(self._on_reg_apk_finished)
        self._reg_apk_worker.start()
    
    def _on_reg_apk_finished(self, success, message, output_content):
        """
        关联APK操作完成回调。
        
        Args:
            success: 是否成功
            message: 结果消息
            output_content: 脚本输出内容
        """
        if success:
            # 刷新文件关联图标，使APK文件图标立即更新
            refresh_file_association_icon()
        
        # 关闭执行提示对话框
        self._close_executing_dialog()
        
        if success:
            QMessageBox.information(self, "成功", message)
        else:
            QMessageBox.warning(self, "提示", message)
        
        # 刷新关联状态显示
        self.update_association_status()
    
    def unreg_apk(self):
        """
        执行取消关联APK脚本。
        
        调用外部批处理脚本取消APK文件与本程序的关联。
        需要管理员权限执行，使用异步方式避免界面卡死。
        """
        # 显示执行提示
        self._show_executing_dialog("取消关联APK", "正在执行取消关联APK操作...\n\n如果弹出管理员权限确认窗口，请点击\"是\"确认。")
        
        # 创建异步工作线程
        self._unreg_apk_worker = ElevatedScriptWorker("☆unreg_apk.bat", "取消关联APK", timeout=30)
        self._unreg_apk_worker.finished.connect(self._on_unreg_apk_finished)
        self._unreg_apk_worker.start()
    
    def _on_unreg_apk_finished(self, success, message, output_content):
        """
        取消关联APK操作完成回调。
        
        Args:
            success: 是否成功
            message: 结果消息
            output_content: 脚本输出内容
        """
        if success:
            # 刷新文件关联图标，使APK文件图标立即更新
            refresh_file_association_icon()
        
        # 关闭执行提示对话框
        self._close_executing_dialog()
        
        if success:
            QMessageBox.information(self, "成功", message)
        else:
            QMessageBox.warning(self, "提示", message)
        
        # 刷新关联状态显示
        self.update_association_status()
    
    def check_msix_installed(self):
        """
        检测MSIX包(ApkHelperContextMenu)是否已安装。
        
        通过读取Windows注册表，直接检查MSIX包对应的子键是否存在，
        判断ApkHelperContextMenu包是否已安装。
        仅在Windows 11 (build >= 22000) 上进行检测。
        使用注册表查询替代PowerShell命令，大幅提升检测速度。
        
        同一个MSIX包在不同Win11电脑上的注册表子键名称完全一致，
        由全局变量 MSIX_PACKAGE_REG_NAME 指定，直接检查该子键是否存在即可。
        
        仅检测HKCU当前用户注册表路径，判断当前用户是否安装了MSIX包：
        - HKCU\\...\\AppModel\\Repository\\Packages\\<MSIX_PACKAGE_REG_NAME>
        
        注册表路径对应关系：
        - Python端：本方法检测 HKCU\...\AppModel\Repository\Packages\<MSIX_PACKAGE_REG_NAME>
        - install.ps1：使用 Add-AppxPackage 安装MSIX包，安装后系统自动创建上述注册表项
        - uninstall.ps1：使用 Remove-AppxPackage 卸载MSIX包，卸载后系统自动删除上述注册表项
        - DLL端：ApkHelperContextMenu.dll 读取 HKCR\SystemFileAssociations\.apk\APKHelperEx
                  （与MSIX安装状态不同，DLL读取的是install.ps1写入的注册表项）
        
        Returns:
            bool: MSIX包已安装返回True，否则返回False
        """
        # 非Win11系统不需要检测MSIX
        if WINDOWS_BUILD_VERSION < 22000:
            app_logger.debug("非Win11系统，跳过MSIX检测")
            return False

        try:
            # 仅检查HKCU当前用户注册表路径
            reg_paths = [
                (winreg.HKEY_CURRENT_USER,
                 r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages",
                 "HKCU当前用户安装"),
            ]
            
            for root_key, reg_path, desc in reg_paths:
                # 拼接完整的子键路径
                full_path = f"{reg_path}\\{MSIX_PACKAGE_REG_NAME}"
                # 尝试64位和32位注册表视图
                for wow64_flag in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                    try:
                        with winreg.OpenKey(root_key, full_path, 0,
                                            winreg.KEY_READ | wow64_flag) as key:
                            app_logger.debug(f"检测到已安装的MSIX包({desc}): {MSIX_PACKAGE_REG_NAME}")
                            return True
                    except OSError:
                        # 当前路径不存在，尝试下一个视图
                        continue
            
            app_logger.debug("未检测到已安装的MSIX包")
            return False
        except ImportError:
            # 非Windows系统，不支持winreg模块
            app_logger.warning("非Windows系统，无法检测MSIX安装状态")
            return False
        except Exception as e:
            app_logger.warning(f"检测MSIX安装状态时出错: {e}")
            return False

    def check_context_menu(self):
        """
        检查APK文件传统右键菜单是否已添加。
        
        通过检查Windows注册表中的相关键值来判断传统右键菜单状态：
        - HKCR\SystemFileAssociations\.apk\shell\APKHelper
        
        注意：本方法仅检测传统右键菜单（shell\APKHelper），不检测MSIX新版右键菜单。
        MSIX新版右键菜单的安装状态由 check_msix_installed() 方法检测。
        install.ps1安装MSIX后会删除shell\APKHelper以避免重复菜单项，
        因此安装MSIX后本方法返回False，这是正确行为。
        
        注册表路径对应关系：
        - Python端：本方法检测 HKCR\SystemFileAssociations\.apk\shell\APKHelper
        - ☆add_menu.bat：写入 shell\APKHelper（含command和Icon子键），同时删除 APKHelperEx
        - ☆rm_menu.bat：删除 shell\APKHelper
        - install.ps1：删除 shell\APKHelper（避免新旧菜单重复），写入 APKHelperEx
        - uninstall.ps1：删除 shell\APKHelper 和 APKHelperEx
        
        Returns:
            bool: 已添加传统右键菜单返回True，否则返回False
        """
        try:
            # 尝试打开注册表项，如果存在则说明传统右键菜单已添加
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"SystemFileAssociations\.apk\shell\APKHelper", 0, winreg.KEY_READ):
                app_logger.debug("找到 HKCR\\SystemFileAssociations\\.apk\\shell\\APKHelper 注册表项")
                return True
        except OSError as e:
            app_logger.debug(f"未找到 HKCR\\SystemFileAssociations\\.apk\\shell\\APKHelper 注册表项: {e}")
            return False
        except ImportError:
            # 非Windows系统，不支持注册表操作
            app_logger.warning("当前系统不是Windows系统")
            return False
        except Exception as e:
            app_logger.warning(f"检查右键菜单状态时出错: {e}")
            return False
    
    def add_context_menu(self):
        """
        执行添加右键菜单脚本。
        
        根据操作系统版本和用户勾选状态，决定添加右键菜单时的操作流程：
        - Win11 + 勾选兼容新版右键菜单：仅执行install.ps1
          install.ps1内部流程：安装证书 → 安装MSIX → 写入APKHelperEx注册表 → 删除shell\APKHelper
        - Win11 + 未勾选兼容新版右键菜单：若MSIX已安装则先卸载MSIX再执行bat，否则直接执行bat
          ☆add_menu.bat内部流程：写入shell\APKHelper（含command和Icon）→ 删除APKHelperEx
        - 非Win11：仅执行☆add_menu.bat脚本
        
        需要管理员权限执行，使用异步方式避免界面卡死。
        """
        # 获取Win11新版右键菜单勾选状态
        enable_win11_menu = config.get("enable_win11_new_menu", False)
        if hasattr(self, 'win11_menu_checkbox') and self.win11_menu_checkbox is not None:
            enable_win11_menu = self.win11_menu_checkbox.isChecked()
        
        if WINDOWS_BUILD_VERSION >= 22000 and enable_win11_menu:
            # Win11 + 勾选兼容新版右键菜单：直接执行install.ps1
            app_logger.debug("Win11系统，勾选了兼容新版右键菜单，直接执行install.ps1安装")
            self._show_executing_dialog("添加右键菜单", "正在安装Win11新版右键菜单...\n\n如果弹出管理员权限确认窗口，请点击\"是\"确认。")
            
            install_ps1_path = os.path.join(BASE_DIR, "ApkHelperContextMenu", "release", "install.ps1")
            # 传递InstallPath参数，指向apk_helper.exe所在目录
            extra_params = f'-InstallPath "{BASE_DIR}"'
            self._install_msix_worker = ElevatedPs1Worker(install_ps1_path, "安装Win11新版右键菜单", timeout=60, extra_params=extra_params)
            self._install_msix_worker.finished.connect(self._on_install_msix_finished)
            self._install_msix_worker.start()
        elif WINDOWS_BUILD_VERSION >= 22000 and not enable_win11_menu:
            # Win11 + 未勾选兼容新版右键菜单
            if self.check_msix_installed():
                # MSIX已安装，先卸载MSIX，再执行bat
                app_logger.debug("Win11系统，未勾选兼容新版右键菜单，检测到已安装的MSIX，先卸载再添加传统右键菜单")
                self._show_executing_dialog("添加右键菜单", "正在卸载Win11新版右键菜单组件...\n\n如果弹出管理员权限确认窗口，请点击\"是\"确认。")
                
                uninstall_ps1_path = os.path.join(BASE_DIR, "ApkHelperContextMenu", "release", "uninstall.ps1")
                self._uninstall_msix_worker = ElevatedPs1Worker(uninstall_ps1_path, "卸载Win11新版右键菜单", timeout=60)
                self._uninstall_msix_worker.finished.connect(self._on_uninstall_msix_before_add_finished)
                self._uninstall_msix_worker.start()
            else:
                # MSIX未安装，直接执行bat脚本
                app_logger.debug("Win11系统，未勾选兼容新版右键菜单，直接添加传统右键菜单")
                self._show_executing_dialog("添加右键菜单", "正在执行添加右键菜单操作...\n\n如果弹出管理员权限确认窗口，请点击\"是\"确认。")
                
                self._add_menu_worker = ElevatedScriptWorker("☆add_menu.bat", "添加右键菜单", timeout=30)
                self._add_menu_worker.finished.connect(self._on_add_menu_finished)
                self._add_menu_worker.start()
        else:
            # 非Win11系统，仅执行bat脚本
            self._show_executing_dialog("添加右键菜单", "正在执行添加右键菜单操作...\n\n如果弹出管理员权限确认窗口，请点击\"是\"确认。")
            
            self._add_menu_worker = ElevatedScriptWorker("☆add_menu.bat", "添加右键菜单", timeout=30)
            self._add_menu_worker.finished.connect(self._on_add_menu_finished)
            self._add_menu_worker.start()
    
    def _on_add_menu_finished(self, success, message, output_content):
        """
        添加传统右键菜单bat脚本执行完成回调。
        
        Args:
            success: bat脚本是否执行成功
            message: 结果消息
            output_content: 脚本输出内容
        """
        # 关闭执行提示对话框
        self._close_executing_dialog()
        
        if success:
            QMessageBox.information(self, "成功", message)
        else:
            QMessageBox.warning(self, "提示", message)
        
        # 刷新右键菜单状态显示
        self.update_context_menu_status()
    
    def _on_install_msix_finished(self, success, message, output_content):
        """
        MSIX安装完成回调（添加右键菜单时调用）。
        
        Args:
            success: 安装是否成功
            message: 结果消息
            output_content: 脚本输出内容
        """
        self._close_executing_dialog()
        
        if success:
            QMessageBox.information(self, "成功", message)
        else:
            QMessageBox.warning(self, "提示", message)
        
        self.update_context_menu_status()
    
    def _on_uninstall_msix_before_add_finished(self, success, message, output_content):
        """
        添加右键菜单时，先卸载MSIX完成后的回调。
        
        卸载MSIX成功后，继续执行bat脚本添加传统右键菜单。
        
        Args:
            success: 卸载是否成功
            message: 结果消息
            output_content: 脚本输出内容
        """
        if not success:
            self._close_executing_dialog()
            QMessageBox.warning(self, "提示", message)
            self.update_context_menu_status()
            return
        
        # 卸载MSIX成功，继续执行bat脚本添加传统右键菜单
        app_logger.debug("MSIX卸载成功，继续执行bat脚本添加传统右键菜单")
        self._show_executing_dialog("添加右键菜单", "Win11新版右键菜单组件已卸载！\n正在添加传统右键菜单...\n\n如果弹出管理员权限确认窗口，请点击\"是\"确认。")
        
        self._add_menu_worker = ElevatedScriptWorker("☆add_menu.bat", "添加右键菜单", timeout=30)
        self._add_menu_worker.finished.connect(self._on_add_menu_finished)
        self._add_menu_worker.start()
    
    def remove_context_menu(self):
        """
        执行清除右键菜单脚本。
        
        根据操作系统版本，决定清除右键菜单时的操作流程：
        - Win11：仅执行uninstall.ps1
          uninstall.ps1内部流程：删除shell\APKHelper → 删除APKHelperEx → 卸载MSIX包
          无论当前是MSIX新版菜单还是传统菜单，uninstall.ps1都会清理干净
        - 非Win11：仅执行☆rm_menu.bat脚本
          ☆rm_menu.bat内部流程：删除shell\APKHelper
        
        需要管理员权限执行，使用异步方式避免界面卡死。
        """
        if WINDOWS_BUILD_VERSION >= 22000:
            # Win11系统，直接执行uninstall.ps1
            app_logger.debug("Win11系统，执行uninstall.ps1清除右键菜单")
            self._show_executing_dialog("清除右键菜单", "正在执行清除右键菜单操作...\n\n如果弹出管理员权限确认窗口，请点击\"是\"确认。")
            
            uninstall_ps1_path = os.path.join(BASE_DIR, "ApkHelperContextMenu", "release", "uninstall.ps1")
            self._remove_msix_worker = ElevatedPs1Worker(uninstall_ps1_path, "清除右键菜单", timeout=60)
            self._remove_msix_worker.finished.connect(self._on_remove_msix_finished)
            self._remove_msix_worker.start()
        else:
            # 非Win11系统，仅执行bat脚本
            self._show_executing_dialog("清除右键菜单", "正在执行清除右键菜单操作...\n\n如果弹出管理员权限确认窗口，请点击\"是\"确认。")
            
            self._remove_menu_worker = ElevatedScriptWorker("☆rm_menu.bat", "清除右键菜单", timeout=30)
            self._remove_menu_worker.finished.connect(self._on_remove_menu_finished)
            self._remove_menu_worker.start()
    
    def _on_remove_menu_finished(self, success, message, output_content):
        """
        清除传统右键菜单bat脚本执行完成回调。
        
        Args:
            success: bat脚本是否执行成功
            message: 结果消息
            output_content: 脚本输出内容
        """
        # 关闭执行提示对话框
        self._close_executing_dialog()
        
        if success:
            QMessageBox.information(self, "成功", message)
        else:
            QMessageBox.warning(self, "提示", message)
        
        # 刷新右键菜单状态显示
        self.update_context_menu_status()
    
    def _on_remove_msix_finished(self, success, message, output_content):
        """
        清除右键菜单时，ps1脚本执行完成回调。
        
        Args:
            success: 卸载是否成功
            message: 结果消息
            output_content: 脚本输出内容
        """
        self._close_executing_dialog()
        
        if success:
            QMessageBox.information(self, "成功", message)
        else:
            QMessageBox.warning(self, "提示", message)
        
        self.update_context_menu_status()
    
    def _show_executing_dialog(self, title, message):
        """
        显示执行中的提示对话框。
        
        Args:
            title: 对话框标题
            message: 提示消息
        """
        # 如果已有对话框，先关闭
        if hasattr(self, '_executing_dialog') and self._executing_dialog is not None:
            self._executing_dialog.hide()
            self._executing_dialog.close()
            self._executing_dialog.deleteLater()
        
        # 创建消息对话框（模态但允许界面刷新）
        self._executing_dialog = QMessageBox(self)
        self._executing_dialog.setWindowTitle(title)
        self._executing_dialog.setText(message)
        self._executing_dialog.setIcon(QMessageBox.Information)
        self._executing_dialog.setStandardButtons(QMessageBox.NoButton)
        # 设置窗口保持在最前
        self._executing_dialog.setWindowFlags(
            self._executing_dialog.windowFlags() | Qt.WindowStaysOnTopHint
        )
        self._executing_dialog.show()
        
        # 强制刷新界面，确保窗口立即显示
        QApplication.processEvents()
    
    def _close_executing_dialog(self):
        """关闭执行中的提示对话框"""
        if hasattr(self, '_executing_dialog') and self._executing_dialog is not None:
            self._executing_dialog.hide()  # 先隐藏
            self._executing_dialog.close()
            self._executing_dialog.deleteLater()
            self._executing_dialog = None
            # 强制刷新界面，确保窗口立即关闭
            QApplication.processEvents()
    
    def update_association_status(self):
        """更新APK关联状态显示 - 检查注册表并更新标签样式"""
        is_associated = self.check_apk_association()
        if hasattr(self, 'association_status_label'):
            if is_associated:
                self.association_status_label.setText("当前状态：已关联APK文件")
                self.association_status_label.setStyleSheet("font-size: 10pt; font-weight: bold; padding: 4px; color: green;")
            else:
                self.association_status_label.setText("当前状态：未关联APK文件")
                self.association_status_label.setStyleSheet("font-size: 10pt; font-weight: bold; padding: 4px; color: red;")
            app_logger.debug(f"APK关联状态已刷新: {'已关联' if is_associated else '未关联'}")
    
    def update_context_menu_status(self):
        """
        更新右键菜单状态显示。
        
        根据操作系统版本和安装状态，显示更精确的右键菜单状态信息：
        - Win11 + 已安装MSIX：显示"已添加Win11新版右键菜单"（MSIX优先判断）
          对应 check_msix_installed() 检测 HKCU\...\AppModel\Repository\Packages
        - Win11 + 未安装MSIX但有传统右键菜单：显示"已添加右键菜单"
          对应 check_context_menu() 检测 HKCR\SystemFileAssociations\.apk\shell\APKHelper
        - Win11 + 都没有：显示"未添加右键菜单"
        - 非Win11：仅根据传统右键菜单注册表状态显示
        
        状态判断优先级：MSIX安装状态 > 传统菜单注册表状态
        这是因为install.ps1安装MSIX后会删除shell\APKHelper（避免重复菜单项），
        所以安装MSIX后check_context_menu()返回False是正确的。
        """
        has_menu = self.check_context_menu()
        menu_font_green = "font-size: 10pt; font-weight: bold; padding: 4px; color: green;"
        menu_font_red = "font-size: 10pt; font-weight: bold; padding: 4px; color: red;"
        if hasattr(self, 'context_menu_status_label'):
            if WINDOWS_BUILD_VERSION >= 22000:
                # Win11系统，结合MSIX安装状态显示
                has_msix = self.check_msix_installed()
                if has_msix:
                    self.context_menu_status_label.setText("当前状态：已添加Win11新版右键菜单")
                    self.context_menu_status_label.setStyleSheet(menu_font_green)
                    app_logger.debug("右键菜单状态已刷新: 已添加Win11新版右键菜单")
                elif has_menu:
                    self.context_menu_status_label.setText("当前状态：已添加右键菜单")
                    self.context_menu_status_label.setStyleSheet(menu_font_green)
                    app_logger.debug("右键菜单状态已刷新: 已添加传统右键菜单")
                else:
                    self.context_menu_status_label.setText("当前状态：未添加右键菜单")
                    self.context_menu_status_label.setStyleSheet(menu_font_red)
                    app_logger.debug("右键菜单状态已刷新: 未添加右键菜单")
            else:
                # 非Win11系统，仅根据传统右键菜单状态显示
                if has_menu:
                    self.context_menu_status_label.setText("当前状态：已添加右键菜单")
                    self.context_menu_status_label.setStyleSheet(menu_font_green)
                else:
                    self.context_menu_status_label.setText("当前状态：未添加右键菜单")
                    self.context_menu_status_label.setStyleSheet(menu_font_red)
                app_logger.debug(f"右键菜单状态已刷新: {'已添加' if has_menu else '未添加'}")
    
    def copy_custom_info(self):
        """
        按照自定义格式复制APK信息到剪贴板。
        
        根据用户设置的格式模板，将APK信息格式化后复制到系统剪贴板。
        """
        if not self.apk_info:
            QMessageBox.warning(self, "警告", "请先解析APK文件")
            return
        
        format_template = config.get("copy_custom_format", DEFAULT_CONFIG["copy_custom_format"])
        
        try:
            info = self.apk_info
            icon_info = self.apk_icon_info if hasattr(self, 'apk_icon_info') else {}
            
            file_info_text = self.file_info_text.toPlainText()
            file_info_lines = file_info_text.split('\n') if file_info_text else []
            
            cert_md5 = ''
            if self.certs and len(self.certs) > 0:
                cert_md5 = self.certs[0].get('md5', '')
            
            format_map = {
                "app_name": info.get('app_name', ''),
                "chinese_app_name": info.get('chinese_app_name', ''),
                "package_name": info.get('package_name', ''),
                "version_name": info.get('version_name', ''),
                "version_code": info.get('version_code', ''),
                "min_sdk_version": info.get('min_sdk_version', ''),
                "target_sdk_version": info.get('target_sdk_version', ''),
                "compile_sdk_version": info.get('compile_sdk_version', ''),
                "arch_support": info.get('arch_support', {}).get('display_text', ''),
                "permissions_count": str(len(info.get('permissions', []))),
                "file_size": file_info_lines[2].split(': ', 1)[1].strip() if len(file_info_lines) > 2 else '',
                "file_md5": file_info_lines[1].split(': ', 1)[1].strip() if len(file_info_lines) > 1 else '',
                "cert_md5": cert_md5,
            }
            
            result = format_template
            for key, value in format_map.items():
                placeholder = "{" + key + "}"
                result = result.replace(placeholder, str(value))
            
            clipboard = QApplication.clipboard()
            clipboard.setText(result)
            
            app_logger.debug(f"已复制自定义信息: {result[:50]}{'...' if len(result) > 50 else ''}")
            
            # 根据配置决定是否弹框提示
            no_popup = config.get("copy_custom_no_popup", DEFAULT_CONFIG["copy_custom_no_popup"])
            if not no_popup:
                QMessageBox.information(self, "成功", f"(可以在更多设置中自定义格式模版)\n自定义信息已复制到剪贴板:\n\n{result[:100]}{'...' if len(result) > 100 else ''}")
            
        except Exception as e:
            app_logger.error(f"复制自定义信息失败: {e}")
            QMessageBox.critical(self, "错误", f"复制自定义信息失败:\n{str(e)}")
    
    def show_more_settings(self):
        """
        显示更多设置窗口。
        
        整合了设置关联、日志设置、批量重命名、复制设置、架构说明、关于等选项卡。
        各选项卡独立保存配置，底部仅保留关闭按钮。
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("更多设置")
        dialog.setMinimumSize(360, 400)
        dialog.resize(400, 480)
        
        layout = QVBoxLayout(dialog)
        
        # 主选项卡（双层结构）
        main_tab_widget = QTabWidget()
        main_tab_widget.setDocumentMode(True)
        
        # === 设置选项卡（第一层） ===
        settings_widget = QWidget()
        settings_layout = QVBoxLayout(settings_widget)
        settings_layout.setContentsMargins(5, 5, 5, 5)
        
        # 设置子选项卡（第二层）
        settings_tab_widget = QTabWidget()
        settings_tab_widget.setTabPosition(QTabWidget.North)
        
        # === 关联APK设置选项卡 ===
        # 该选项卡包含两个功能区域：APK文件关联 和 APK右键菜单
        association_widget = QWidget()
        association_layout = QVBoxLayout(association_widget)
        association_layout.setContentsMargins(10, 10, 10, 10)
        association_layout.setSpacing(20)  # 两个GroupBox之间的间距
        
        # === APK文件关联区域 ===
        # 用于设置双击APK文件时使用本程序打开
        apk_association_group = QGroupBox("APK文件关联")
        apk_association_layout = QVBoxLayout(apk_association_group)
        apk_association_layout.setSpacing(10)  # 控件之间的间距
        
        # 关联状态显示标签 - 显示当前APK文件关联状态
        self.association_status_label = QLabel()
        self.association_status_label.setAlignment(Qt.AlignCenter)
        self.association_status_label.setStyleSheet("font-size: 10pt; font-weight: bold; padding: 4px;")
        self.association_status_label.setMinimumHeight(20)
        
        # 初始化时更新状态显示
        self.update_association_status()
        apk_association_layout.addWidget(self.association_status_label)
        
        # 功能说明文字
        association_info = QLabel("设置或取消APK文件与本程序的关联。\n双击APK文件时可自动使用本程序打开。")
        association_info.setWordWrap(True)
        association_info.setAlignment(Qt.AlignCenter)
        apk_association_layout.addWidget(association_info)
        
        # 提示文字（放在按钮上方，居中）
        tip_label = QLabel("提示: 需要管理员权限才能成功执行")
        tip_label.setStyleSheet("color: blue;")
        tip_label.setAlignment(Qt.AlignCenter)
        apk_association_layout.addWidget(tip_label)
        
        # 关联操作按钮布局（水平居中排列）
        association_btn_layout = QHBoxLayout()
        association_btn_layout.setSpacing(5)  # 按钮之间的间距
        association_btn_layout.addStretch()  # 左侧弹性空间，使按钮居中
        
        # 关联APK文件按钮 - 调用☆reg_apk.bat脚本
        reg_btn = QPushButton("关联APK文件")
        reg_btn.setFixedWidth(100)
        reg_btn.setToolTip("注册APK文件关联，APK文件默认使用本程序打开")
        association_btn_layout.addWidget(reg_btn)
        
        # 取消关联APK按钮 - 调用☆unreg_apk.bat脚本
        unreg_btn = QPushButton("取消关联APK")
        unreg_btn.setFixedWidth(100)
        unreg_btn.setToolTip("取消APK文件关联，APK文件不再默认使用本程序打开")
        association_btn_layout.addWidget(unreg_btn)
        
        # 刷新状态按钮 - 重新检测关联状态
        refresh_btn = QPushButton("刷新状态")
        refresh_btn.setFixedWidth(100)
        refresh_btn.setToolTip("刷新当前关联状态")
        association_btn_layout.addWidget(refresh_btn)
        
        association_btn_layout.addStretch()  # 右侧弹性空间，使按钮居中
        apk_association_layout.addLayout(association_btn_layout)
        
        # 关联按钮点击事件处理
        def on_reg_apk():
            """执行关联APK操作并刷新状态显示"""
            self.reg_apk()
        
        def on_unreg_apk():
            """执行取消关联APK操作并刷新状态显示"""
            self.unreg_apk()
        
        reg_btn.clicked.connect(on_reg_apk)
        unreg_btn.clicked.connect(on_unreg_apk)
        refresh_btn.clicked.connect(self.update_association_status)
        
        # 将APK文件关联区域添加到主布局
        association_layout.addWidget(apk_association_group)
        
        # === 右键菜单区域 ===
        # 用于在APK文件右键菜单中添加"使用 APK Helper 打开"选项
        context_menu_group = QGroupBox("APK右键菜单")
        context_menu_layout = QVBoxLayout(context_menu_group)
        context_menu_layout.setSpacing(10)  # 控件之间的间距
        
        # 右键菜单状态显示标签 - 显示当前右键菜单是否已添加
        self.context_menu_status_label = QLabel()
        self.context_menu_status_label.setAlignment(Qt.AlignCenter)
        self.context_menu_status_label.setStyleSheet("font-size: 10pt; font-weight: bold; padding: 4px;")
        self.context_menu_status_label.setMinimumHeight(20)
        
        # 初始化时更新状态显示
        self.update_context_menu_status()
        context_menu_layout.addWidget(self.context_menu_status_label)
        
        # 功能说明文字
        context_menu_info = QLabel("添加或清除APK文件的右键菜单。\n右键APK文件时可选择\"使用 APK Helper 打开\"。")
        context_menu_info.setWordWrap(True)
        context_menu_info.setAlignment(Qt.AlignCenter)
        context_menu_layout.addWidget(context_menu_info)
        
        # 提示文字（放在按钮上方，居中）
        tip_label = QLabel("提示: 需要管理员权限才能成功执行")
        tip_label.setStyleSheet("color: blue;")
        tip_label.setAlignment(Qt.AlignCenter)
        context_menu_layout.addWidget(tip_label)
        
        # Win11新版右键菜单选项（仅当build版本号>=22000时显示）
        # Windows 11 (build >= 22000) 使用新版右键菜单，需要特殊处理
        if WINDOWS_BUILD_VERSION >= 22000:
            # 使用水平布局使勾选框居中显示
            win11_checkbox_layout = QHBoxLayout()
            win11_checkbox_layout.addStretch()
            
            win11_menu_checkbox = QCheckBox("兼容Win11新版右键菜单")
            win11_menu_checkbox.setToolTip("添加右键菜单时，兼容Windows 11新版右键菜单。\n注意：需要安装msix组件以及对应证书。")
            win11_menu_checkbox.setChecked(config.get("enable_win11_new_menu", False))
            win11_checkbox_layout.addWidget(win11_menu_checkbox)
            
            win11_checkbox_layout.addStretch()
            context_menu_layout.addLayout(win11_checkbox_layout)
            
            # 保存勾选框的引用，以便后续保存设置
            self.win11_menu_checkbox = win11_menu_checkbox
            
            # 勾选框状态变更时自动保存到配置
            def on_win11_menu_checkbox_changed(state):
                """Win11新版右键菜单勾选框状态变更回调"""
                is_checked = (state == Qt.Checked)
                config["enable_win11_new_menu"] = is_checked
                if save_config():
                    app_logger.info(f"Win11新版右键菜单选项已保存: {'勾选' if is_checked else '取消勾选'}")
                else:
                    app_logger.warning("Win11新版右键菜单选项保存失败")
            
            win11_menu_checkbox.stateChanged.connect(on_win11_menu_checkbox_changed)
        else:
            # 非Win11系统，确保不存在勾选框引用
            if hasattr(self, 'win11_menu_checkbox'):
                self.win11_menu_checkbox = None
        
        # 右键菜单操作按钮布局（水平居中排列）
        context_menu_btn_layout = QHBoxLayout()
        context_menu_btn_layout.setSpacing(5)  # 按钮之间的间距
        context_menu_btn_layout.addStretch()  # 左侧弹性空间，使按钮居中
        
        # 添加右键菜单按钮 - 调用☆add_menu.bat脚本
        add_menu_btn = QPushButton("添加右键菜单")
        add_menu_btn.setFixedWidth(100)
        add_menu_btn.setToolTip("添加APK文件右键菜单，右键APK文件时显示\"使用 APK Helper 打开\"选项")
        context_menu_btn_layout.addWidget(add_menu_btn)
        
        # 清除右键菜单按钮 - 调用☆rm_menu.bat脚本
        remove_menu_btn = QPushButton("清除右键菜单")
        remove_menu_btn.setFixedWidth(100)
        remove_menu_btn.setToolTip("清除APK文件右键菜单")
        context_menu_btn_layout.addWidget(remove_menu_btn)
        
        # 刷新状态按钮 - 重新检测右键菜单状态
        refresh_menu_btn = QPushButton("刷新状态")
        refresh_menu_btn.setFixedWidth(100)
        refresh_menu_btn.setToolTip("刷新当前右键菜单状态")
        context_menu_btn_layout.addWidget(refresh_menu_btn)
        
        context_menu_btn_layout.addStretch()  # 右侧弹性空间，使按钮居中
        context_menu_layout.addLayout(context_menu_btn_layout)
        
        # 右键菜单按钮点击事件处理
        def on_add_menu():
            """执行添加右键菜单操作并刷新状态显示"""
            self.add_context_menu()
        
        def on_remove_menu():
            """执行清除右键菜单操作并刷新状态显示"""
            self.remove_context_menu()
        
        # 连接按钮信号到槽函数
        add_menu_btn.clicked.connect(on_add_menu)
        remove_menu_btn.clicked.connect(on_remove_menu)
        refresh_menu_btn.clicked.connect(self.update_context_menu_status)
        
        # 将右键菜单区域添加到主布局
        association_layout.addWidget(context_menu_group)
        
        # 添加弹性空间，将内容推向上方
        association_layout.addStretch()
        
        # 将APK关联选项卡添加到设置子选项卡
        settings_tab_widget.addTab(association_widget, "关联APK")
        
        # === 复制自定义信息设置选项卡 ===
        copy_custom_widget = QWidget()
        copy_custom_layout = QVBoxLayout(copy_custom_widget)
        copy_custom_layout.setContentsMargins(10, 10, 10, 10)
        
        copy_info_label = QLabel("设置复制自定义信息的格式模板。\n解析APK后，点击\"复制自定义信息\"按钮将按此格式复制信息到剪贴板。\n")
        copy_info_label.setWordWrap(True)
        copy_custom_layout.addWidget(copy_info_label)
        
        copy_params_label = QLabel("格式模版可用参数（可选中复制）：")
        copy_custom_layout.addWidget(copy_params_label)
        
        copy_params_text = QTextEdit()
        copy_params_text.setMaximumHeight(150)
        copy_params_text.setReadOnly(True)
        copy_params_text.setPlainText(
            "{app_name} - 应用名称\n"
            "{chinese_app_name} - 中文名称\n"
            "{package_name} - 包名\n"
            "{version_name} - 版本号\n"
            "{version_code} - 内部版本号\n"
            "{min_sdk_version} - 最低SDK版本\n"
            "{target_sdk_version} - 目标SDK版本\n"
            "{compile_sdk_version} - 编译SDK版本\n"
            "{arch_support} - 支持架构\n"
            "{permissions_count} - 权限数量\n"
            "{file_size} - 文件大小\n"
            "{file_md5} - 文件MD5值\n"
            "{cert_md5} - 证书MD5值"
        )
        copy_params_text.setToolTip("选中参数后按Ctrl+C复制")
        copy_custom_layout.addWidget(copy_params_text)
        
        escape_label = QLabel("支持转义字符：\\n(换行) \\t(制表符) \\\\(反斜杠)")
        copy_custom_layout.addWidget(escape_label)
        
        copy_format_group = QGroupBox("格式模板")
        copy_format_layout = QVBoxLayout(copy_format_group)
        
        copy_format_edit = QLineEdit()
        copy_format_edit.setText(config.get("copy_custom_format", DEFAULT_CONFIG["copy_custom_format"]))
        copy_format_edit.setToolTip("输入自定义格式模板，使用{变量名}作为占位符，最多200个字符")
        copy_format_edit.setMaxLength(200)
        copy_format_layout.addWidget(copy_format_edit)
        
        copy_custom_layout.addWidget(copy_format_group)
        
        # 复制后不弹框提示选项
        copy_no_popup_checkbox = QCheckBox("每次复制自定义信息后不再弹框提示")
        copy_no_popup_checkbox.setToolTip("勾选后，点击\"复制自定义信息\"按钮时将不再弹出提示框")
        copy_no_popup_checkbox.setChecked(config.get("copy_custom_no_popup", DEFAULT_CONFIG["copy_custom_no_popup"]))
        copy_custom_layout.addWidget(copy_no_popup_checkbox)
        
        # 复制设置按钮布局（居中）
        copy_btn_layout = QHBoxLayout()
        copy_btn_layout.addStretch()
        
        copy_save_btn = QPushButton("保存设置")
        copy_save_btn.setFixedWidth(100)
        copy_save_btn.setToolTip("保存当前设置")
        copy_btn_layout.addWidget(copy_save_btn)
        
        copy_reset_btn = QPushButton("恢复默认设置")
        copy_reset_btn.setFixedWidth(100)
        copy_reset_btn.setToolTip("恢复为默认设置")
        copy_btn_layout.addWidget(copy_reset_btn)
        
        copy_btn_layout.addStretch()
        copy_custom_layout.addLayout(copy_btn_layout)
        
        copy_custom_layout.addStretch()
        
        settings_tab_widget.addTab(copy_custom_widget, "复制自定义信息格式")
        
        # === 复制分隔符设置选项卡 ===
        separator_widget = QWidget()
        separator_layout = QVBoxLayout(separator_widget)
        separator_layout.setContentsMargins(10, 10, 10, 10)
        
        separator_info = QLabel(
            "表格内容选中单项或多项时，使用 Ctrl+C 键可以复制选中单元格内容。\n"
            "这里可以设置复制表格内容时插入的分隔符。\n\n"
            "选择\"自定义\"后可输入自定义分隔符（最多10个字符，仅支持可打印ASCII字符）。"
            "支持的转义字符：\\n(换行) \\t(制表) \\r(回车) \\\\(反斜杠)。\n"
        )
        separator_info.setWordWrap(True)
        separator_layout.addWidget(separator_info)
        
        row_sep_group = QGroupBox("行间分隔符")
        row_sep_layout = QVBoxLayout(row_sep_group)
        
        row_sep_combo = QComboBox()
        row_sep_items = [
            ("换行符 (\\n)", "\n"),
            ("制表符 (\\t)", "\t"),
            ("分号 (;)", ";"),
            ("逗号 (,)", ","),
            ("竖线 (|)", "|"),
            ("空格", " "),
            ("减号 (-)", "-"),
            ("下划线 (_)", "_"),
            ("斜杠 (/)", "/"),
            ("反斜杠 (\\)", "\\"),
            ("井号 (#)", "#"),
            ("冒号 (:)", ":"),
            ("大于号 (>)", ">"),
            ("等号 (=)", "="),
            ("自定义...", None),
        ]
        for item_text, item_sep in row_sep_items:
            row_sep_combo.addItem(item_text, item_sep)
        
        row_sep_combo.setToolTip("选择预设分隔符或选择\"自定义\"输入自定义分隔符")
        row_sep_layout.addWidget(row_sep_combo)
        
        row_sep_custom = QLineEdit()
        row_sep_custom.setPlaceholderText("输入自定义分隔符")
        row_sep_custom.setEnabled(False)
        row_sep_custom.setToolTip("选择\"自定义\"后可在此输入自定义分隔符")
        row_sep_layout.addWidget(row_sep_custom)
        
        current_row_sep = CustomTableWidget.row_separator
        found_row_sep = False
        for i in range(row_sep_combo.count() - 1):
            if row_sep_combo.itemData(i) == current_row_sep:
                row_sep_combo.setCurrentIndex(i)
                found_row_sep = True
                break
        if not found_row_sep:
            row_sep_combo.setCurrentIndex(row_sep_combo.count() - 1)
            row_sep_custom.setEnabled(True)
            row_sep_custom.setText(current_row_sep)
        
        def on_row_sep_changed(index):
            """行间分隔符选择变更处理"""
            if row_sep_combo.itemData(index) is None:
                row_sep_custom.setEnabled(True)
                row_sep_custom.setFocus()
            else:
                row_sep_custom.setEnabled(False)
                row_sep_custom.clear()
        
        row_sep_combo.currentIndexChanged.connect(on_row_sep_changed)
        
        separator_layout.addWidget(row_sep_group)
        
        col_sep_group = QGroupBox("列间隔符")
        col_sep_layout = QVBoxLayout(col_sep_group)
        
        col_sep_combo = QComboBox()
        col_sep_items = [
            ("制表符 (\\t)", "\t"),
            ("换行符 (\\n)", "\n"),
            ("分号 (;)", ";"),
            ("逗号 (,)", ","),
            ("竖线 (|)", "|"),
            ("空格", " "),
            ("减号 (-)", "-"),
            ("下划线 (_)", "_"),
            ("斜杠 (/)", "/"),
            ("反斜杠 (\\)", "\\"),
            ("井号 (#)", "#"),
            ("冒号 (:)", ":"),
            ("大于号 (>)", ">"),
            ("等号 (=)", "="),
            ("自定义...", None),
        ]
        for item_text, item_sep in col_sep_items:
            col_sep_combo.addItem(item_text, item_sep)
        
        col_sep_combo.setToolTip("选择预设分隔符或选择\"自定义\"输入自定义分隔符")
        col_sep_layout.addWidget(col_sep_combo)
        
        col_sep_custom = QLineEdit()
        col_sep_custom.setPlaceholderText("输入自定义分隔符")
        col_sep_custom.setEnabled(False)
        col_sep_custom.setToolTip("选择\"自定义\"后可在此输入自定义分隔符")
        col_sep_layout.addWidget(col_sep_custom)
        
        current_col_sep = CustomTableWidget.col_separator
        found_col_sep = False
        for i in range(col_sep_combo.count() - 1):
            if col_sep_combo.itemData(i) == current_col_sep:
                col_sep_combo.setCurrentIndex(i)
                found_col_sep = True
                break
        if not found_col_sep:
            col_sep_combo.setCurrentIndex(col_sep_combo.count() - 1)
            col_sep_custom.setEnabled(True)
            col_sep_custom.setText(current_col_sep)
        
        def on_col_sep_changed(index):
            """列间隔符选择变更处理"""
            if col_sep_combo.itemData(index) is None:
                col_sep_custom.setEnabled(True)
                col_sep_custom.setFocus()
            else:
                col_sep_custom.setEnabled(False)
                col_sep_custom.clear()
        
        col_sep_combo.currentIndexChanged.connect(on_col_sep_changed)
        
        separator_layout.addWidget(col_sep_group)
        
        # 分隔符选项卡按钮布局（居中）
        separator_btn_layout = QHBoxLayout()
        separator_btn_layout.addStretch()
        
        separator_save_btn = QPushButton("保存设置")
        separator_save_btn.setFixedWidth(100)
        separator_save_btn.setToolTip("保存当前设置")
        separator_btn_layout.addWidget(separator_save_btn)
        
        separator_reset_btn = QPushButton("恢复默认设置")
        separator_reset_btn.setFixedWidth(100)
        separator_reset_btn.setToolTip("恢复为默认设置")
        separator_btn_layout.addWidget(separator_reset_btn)
        
        separator_btn_layout.addStretch()
        separator_layout.addLayout(separator_btn_layout)
        
        separator_layout.addStretch()
        
        settings_tab_widget.addTab(separator_widget, "分隔符")
        
        # === 日志管理设置选项卡 ===
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(10, 10, 10, 10)
        
        log_group = QGroupBox("日志设置")
        log_group_layout = QVBoxLayout(log_group)
        
        # 日志级别和保存日志按钮在同一行
        log_level_layout = QHBoxLayout()
        log_level_layout.addWidget(QLabel("日志级别:"))
        
        log_level_combo = QComboBox()
        log_level_combo.setToolTip("修改日志级别后，后续日志将按新级别生成")
        log_levels = ["DEBUG", "INFO", "WARNING", "ERROR"]
        log_level_combo.addItems(log_levels)
        
        global CURRENT_LOG_LEVEL
        if CURRENT_LOG_LEVEL in log_levels:
            log_level_combo.setCurrentText(CURRENT_LOG_LEVEL)
        else:
            log_level_combo.setCurrentText(DEFAULT_LOG_LEVEL)
        
        log_level_layout.addWidget(log_level_combo)
        log_level_layout.addStretch()
        
        save_log_btn = QPushButton("保存当前日志")
        save_log_btn.setFixedWidth(100)
        save_log_btn.setToolTip(f"将缓存的日志信息保存到文件，\n当前缓存大小限制: {LOG_CACHE_MAX_SIZE // 1024}KB")
        log_level_layout.addWidget(save_log_btn)
        
        log_group_layout.addLayout(log_level_layout)
        
        log_layout.addWidget(log_group)
        
        # 保存设置按钮（居中，在GroupBox外面）
        log_save_btn_layout = QHBoxLayout()
        log_save_btn_layout.addStretch()
        
        log_save_btn = QPushButton("保存设置")
        log_save_btn.setFixedWidth(100)
        log_save_btn.setToolTip("保存日志级别设置")
        log_save_btn_layout.addWidget(log_save_btn)
        
        log_reset_btn = QPushButton("恢复默认设置")
        log_reset_btn.setFixedWidth(100)
        log_reset_btn.setToolTip("恢复日志级别为默认设置")
        log_save_btn_layout.addWidget(log_reset_btn)
        
        log_save_btn_layout.addStretch()
        log_layout.addLayout(log_save_btn_layout)
        
        log_layout.addStretch()
        
        settings_tab_widget.addTab(log_widget, "日志")
        
        settings_layout.addWidget(settings_tab_widget)
        main_tab_widget.addTab(settings_widget, "设置")
        
        # === 批量重命名APK选项卡（与设置并列） ===
        batch_rename_widget = QWidget()
        batch_rename_layout = QVBoxLayout(batch_rename_widget)
        batch_rename_layout.setContentsMargins(10, 10, 10, 10)
        
        batch_rename_group = QGroupBox("")
        batch_rename_group_layout = QVBoxLayout(batch_rename_group)
        
        batch_rename_label = QLabel("批量重命名指定目录下的所有apk文件，可以自定义文件名的格式模版。\n")
        batch_rename_label.setWordWrap(True)
        batch_rename_group_layout.addWidget(batch_rename_label)
        
        batch_rename_params_label = QLabel("格式模版可用参数（可选中复制）：")
        batch_rename_group_layout.addWidget(batch_rename_params_label)
        
        batch_rename_params_text = QTextEdit()
        batch_rename_params_text.setMaximumHeight(150)
        batch_rename_params_text.setReadOnly(True)
        batch_rename_params_text.setPlainText(
            "{app_name} - 应用名称\n"
            "{chinese_app_name} - 中文名称\n"
            "{package_name} - 包名\n"
            "{version_name} - 版本号\n"
            "{version_code} - 内部版本号\n"
            "{min_sdk_version} - 最低SDK版本\n"
            "{target_sdk_version} - 目标SDK版本\n"
            "{compile_sdk_version} - 编译SDK版本\n"
            "{arch_support} - 支持架构\n"
            "{permissions_count} - 权限数量\n"
            "{file_size} - 文件大小\n"
            "{file_md5} - 文件MD5值\n"
            "{cert_md5} - 证书MD5值"
        )
        batch_rename_params_text.setToolTip("选中参数后按Ctrl+C复制")
        batch_rename_group_layout.addWidget(batch_rename_params_text)
        
        notice_label = QLabel("注意：文件名不能包含非法字符 \\ / : * ? \" < > |")
        batch_rename_group_layout.addWidget(notice_label)
        
        dir_select_layout = QHBoxLayout()
        dir_select_layout.addWidget(QLabel("目录:"))
        
        batch_dir_edit = QLineEdit()
        batch_dir_edit.setPlaceholderText("选择需要批量处理的目录")
        dir_select_layout.addWidget(batch_dir_edit)
        
        batch_dir_btn = QPushButton("浏览")
        batch_dir_btn.setFixedWidth(60)
        batch_dir_btn.setToolTip("选择目录")
        dir_select_layout.addWidget(batch_dir_btn)
        
        batch_rename_group_layout.addLayout(dir_select_layout)
        
        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel("格式:"))
        
        rename_format_edit = QLineEdit()
        rename_format_edit.setText(config.get("rename_format", DEFAULT_CONFIG["rename_format"]))
        rename_format_edit.setToolTip("输入重命名格式，使用{变量名}作为占位符，最多200个字符")
        rename_format_edit.setMaxLength(200)
        format_layout.addWidget(rename_format_edit)
        
        batch_rename_group_layout.addLayout(format_layout)
        
        include_subdir_checkbox = QCheckBox("包含子目录")
        include_subdir_checkbox.setChecked(config.get("rename_include_subdir", DEFAULT_CONFIG["rename_include_subdir"]))
        batch_rename_group_layout.addWidget(include_subdir_checkbox)
        
        auto_number_checkbox = QCheckBox("重复文件名自动添加编号")
        auto_number_checkbox.setChecked(config.get("rename_auto_number", DEFAULT_CONFIG["rename_auto_number"]))
        auto_number_checkbox.setToolTip(
            "勾选后，批量重命名时如果目标文件名重复，将自动添加编号后缀以避免冲突。\n\n"
            "编号规则：\n"
            "- 在文件名末尾（扩展名前）添加 _编号\n"
            "- 编号起始为两位数字（如 _01），超过两位时自动扩展（如 _100）\n"
            "- 例如：app_1.0.apk → app_1.0_01.apk, app_1.0_02.apk\n\n"
            "不勾选时，如果目标文件名已存在，则该文件重命名失败。"
        )
        batch_rename_group_layout.addWidget(auto_number_checkbox)
        
        batch_rename_layout.addWidget(batch_rename_group)
        
        # 批量重命名按钮布局（居中）
        batch_rename_btn_layout = QHBoxLayout()
        batch_rename_btn_layout.addStretch()
        
        execute_btn = QPushButton("执行重命名")
        execute_btn.setFixedWidth(100)
        batch_rename_btn_layout.addWidget(execute_btn)
        
        batch_rename_save_btn = QPushButton("保存设置")
        batch_rename_save_btn.setFixedWidth(100)
        batch_rename_save_btn.setToolTip("保存当前设置")
        batch_rename_btn_layout.addWidget(batch_rename_save_btn)
        
        batch_rename_reset_btn = QPushButton("恢复默认设置")
        batch_rename_reset_btn.setFixedWidth(100)
        batch_rename_reset_btn.setToolTip("恢复为默认设置")
        batch_rename_btn_layout.addWidget(batch_rename_reset_btn)
        
        batch_rename_btn_layout.addStretch()
        batch_rename_layout.addLayout(batch_rename_btn_layout)
        
        batch_rename_layout.addStretch()
        
        main_tab_widget.addTab(batch_rename_widget, "批量重命名")
        
        # === 配置信息选项卡 ===
        config_info_widget = QWidget()
        config_info_layout = QVBoxLayout(config_info_widget)
        config_info_layout.setContentsMargins(10, 10, 10, 10)
        
        # 配置文件路径显示区域
        config_path_group = QGroupBox("配置文件路径")
        config_path_layout = QVBoxLayout(config_path_group)
        
        config_path_edit = QLineEdit()
        config_path_edit.setReadOnly(True)
        config_path_edit.setToolTip("当前配置文件的保存路径（只读）")
        # 获取当前配置文件路径（转换为长路径格式）
        current_config_path, current_is_local = get_config_file_path()
        display_path = get_long_path(current_config_path) if current_config_path else "未知"
        config_path_edit.setText(display_path)
        config_path_layout.addWidget(config_path_edit)
        
        config_info_layout.addWidget(config_path_group)
        
        # 配置文件内容显示区域
        config_content_group = QGroupBox("配置文件内容")
        config_content_layout = QVBoxLayout(config_content_group)
        
        config_content_edit = QTextEdit()
        config_content_edit.setReadOnly(True)
        config_content_edit.setMaximumHeight(200)
        config_content_edit.setToolTip("当前配置文件的内容（只读）")
        # 读取并显示配置文件内容
        if current_config_path and os.path.isfile(current_config_path):
            try:
                with open(current_config_path, 'r', encoding='utf-8') as f:
                    config_content_edit.setPlainText(f.read())
            except Exception as e:
                config_content_edit.setPlainText(f"读取配置文件失败: {e}")
        else:
            config_content_edit.setPlainText("配置文件不存在，使用默认配置")
        config_content_layout.addWidget(config_content_edit)
        
        config_info_layout.addWidget(config_content_group)
        
        # 本地配置模式选项
        local_config_group = QGroupBox("配置保存位置")
        local_config_layout = QVBoxLayout(local_config_group)
        
        local_config_checkbox = QCheckBox("将配置文件保存在程序所在目录（便携模式）")
        local_config_checkbox.setToolTip(
            "勾选后，配置文件将保存在程序所在目录而非系统AppData目录。\n\n"
            "说明：\n"
            "- 勾选此选项并保存后，会在程序目录下创建 LOCAL_CONFIG 标志文件\n"
            "- 取消勾选并保存后，会删除 LOCAL_CONFIG 标志文件，配置将保存到 AppData 目录\n"
            "- 此选项适用于便携版或需要将配置与程序放在一起的情况"
        )
        local_config_checkbox.setChecked(current_is_local)
        local_config_layout.addWidget(local_config_checkbox)
        
        config_info_layout.addWidget(local_config_group)
        
        # 按钮区域
        config_info_btn_layout = QHBoxLayout()
        config_info_btn_layout.addStretch()
        
        refresh_config_btn = QPushButton("刷新")
        refresh_config_btn.setFixedWidth(80)
        refresh_config_btn.setToolTip("刷新配置文件路径和内容显示")
        config_info_btn_layout.addWidget(refresh_config_btn)
        
        reset_all_config_btn = QPushButton("重置所有配置")
        reset_all_config_btn.setFixedWidth(100)
        reset_all_config_btn.setToolTip("将所有配置恢复为默认值并保存")
        config_info_btn_layout.addWidget(reset_all_config_btn)
        
        save_config_location_btn = QPushButton("保存设置")
        save_config_location_btn.setFixedWidth(80)
        save_config_location_btn.setToolTip("保存配置保存位置设置")
        config_info_btn_layout.addWidget(save_config_location_btn)
        
        config_info_btn_layout.addStretch()
        config_info_layout.addLayout(config_info_btn_layout)
        
        config_info_layout.addStretch()
        
        main_tab_widget.addTab(config_info_widget, "配置信息")
        
        # === 关于选项卡（双层结构） ===
        about_widget = QWidget()
        about_layout = QVBoxLayout(about_widget)
        about_layout.setContentsMargins(5, 5, 5, 5)
        
        about_tab_widget = QTabWidget()
        about_tab_widget.setTabPosition(QTabWidget.North)
        
        # 关于软件子选项卡
        about_text = f"APK文件信息解析工具-APK Helper\n\n" + \
                     f"版本: {b_ver}\n" + \
                     f"日期: {b_date}\n" + \
                     f"作者: {b_auth}（https://github.com/wzsx150/apk_helper）\n\n" + \
                     f"使用aapt2工具分析安卓应用APK文件，显示一些基本信息。支持将APK文件关联到本程序。\n\n" + \
                     f"功能: \n" + \
                     f"- 查看应用图标和基本信息\n" + \
                     f"- 查看应用权限\n" + \
                     f"- 查看签名信息和证书哈希值\n" + \
                     f"- 查看文件大小和MD5值\n" + \
                     f"- 复制自定义格式的应用信息到剪贴板\n" + \
                     f"- 复制应用所有信息到剪贴板\n" + \
                     f"- 保存应用所有信息到文本文件\n" + \
                     f"- 保存应用图标到PNG文件\n" + \
                     f"- 比较签名证书哈希值是否相同\n" + \
                     f"- 表格选中单项或多项内容后，按Ctrl+C键可复制选中内容\n" + \
                     f"- 可设定复制表格选中内容的分隔符\n" + \
                     f"- 批量重命名APK文件\n" + \
                     f"- 支持关联到APK文件，作为默认打开程序\n" + \
                     f"- 支持添加右键菜单，使用本程序打开APK文件\n" + \
                     f"- 支持拖拽APK文件到程序窗口进行解析"
        
        about_text_edit = QTextEdit()
        about_text_edit.setPlainText(about_text)
        about_text_edit.setReadOnly(True)
        about_text_edit.setStyleSheet("QTextEdit { background-color: white; color: black; }")
        about_tab_widget.addTab(about_text_edit, "关于软件")
        
        # 架构说明子选项卡
        arch_text = (
            "ARM架构：主流处理器架构(高通、联发科等)\n"
            "  - armeabi：ARM 32位 (旧架构)\n"
            "  - armeabi-v7a：ARM 32位 (旧架构)\n"
            "  - arm64-v8a：ARM 64位 (主流架构)\n\n"
            "x86架构：Intel处理器架构\n"
            "  - x86：Intel 32位处理器 (旧架构)\n"
            "  - x86_64：Intel 64位处理器 (非主流架构)\n\n"
            "其他架构：\n"
            "  - mips/mips64：MIPS架构 (旧架构)\n"
            "  - riscv64：RISC-V架构 (非主流新兴架构)\n"
            "  - 纯应用：纯Java/Kotlin应用，无架构限制\n"
            "  - 未知：无法识别的架构\n\n"
            "兼容说明：\n"
            "  - 32位应用理论上可在同架构64位系统上运行，如armeabi-v7a架构的应用可以在arm64设备上运行\n"
            "  - 应用支持的架构与安卓设备系统架构不一致时，理论上他们无法兼容和运行\n"
            "  - 纯应用(无架构)理论上可以兼容所有架构安卓设备，实际是否能运行还取决于其他因素影响"
        )
        
        arch_text_edit = QTextEdit()
        arch_text_edit.setPlainText(arch_text)
        arch_text_edit.setReadOnly(True)
        arch_text_edit.setStyleSheet("QTextEdit { background-color: white; color: black; }")
        about_tab_widget.addTab(arch_text_edit, "架构说明")
        
        about_layout.addWidget(about_tab_widget)
        main_tab_widget.addTab(about_widget, "关于")
        
        layout.addWidget(main_tab_widget)
        
        # 底部关闭按钮
        close_btn_layout = QHBoxLayout()
        close_btn_layout.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.setFixedWidth(100)
        close_btn_layout.addWidget(close_btn)
        close_btn_layout.addStretch()
        layout.addLayout(close_btn_layout)
        
        # === 辅助函数定义 ===
        
        def parse_separator(text):
            """解析分隔符转义字符"""
            if not text:
                return ""
            result = text.replace("\\\\", "\x00")
            result = result.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r")
            result = result.replace("\x00", "\\")
            return result
        
        def validate_separator(sep, name):
            """验证分隔符是否有效"""
            if not sep:
                return True, ""
            if len(sep) > 10:
                return False, f"{name}长度不能超过10个字符"
            for char in sep:
                code = ord(char)
                if code > 126:
                    return False, f"{name}包含无效字符"
            return True, ""
        
        def validate_format(format_text, name):
            """验证格式模板是否有效"""
            if not format_text or not format_text.strip():
                return False, f"{name}不能为空"
            if len(format_text) > 200:
                return False, f"{name}长度不能超过200个字符"
            return True, ""
        
        def refresh_config_info():
            """刷新配置文件路径和内容显示"""
            current_path, is_local = get_config_file_path()
            # 转换为长路径格式显示
            display_path = get_long_path(current_path) if current_path else "未知"
            config_path_edit.setText(display_path)
            
            # 更新复选框状态
            local_config_checkbox.setChecked(is_local)
            
            # 更新配置文件内容
            if current_path and os.path.isfile(current_path):
                try:
                    with open(current_path, 'r', encoding='utf-8') as f:
                        config_content_edit.setPlainText(f.read())
                except Exception as e:
                    config_content_edit.setPlainText(f"读取配置文件失败: {e}")
            else:
                config_content_edit.setPlainText("配置文件不存在，使用默认配置")
            
            app_logger.debug("配置信息已刷新")
        
        def save_config_location():
            """保存配置保存位置设置"""
            use_local = local_config_checkbox.isChecked()
            current_is_local_mode = is_local_config_mode()
            
            # 获取 LOCAL_CONFIG 标志文件路径
            local_config_flag = ""
            if 'PRO_DIR' in globals() and PRO_DIR:
                local_config_flag = os.path.join(PRO_DIR, LOCAL_CONFIG_FILE)
            
            if use_local:
                # 用户选择本地配置模式
                if not local_config_flag or not os.path.isabs(local_config_flag):
                    QMessageBox.warning(dialog, "警告", "无法确定程序目录，无法使用本地配置模式")
                    local_config_checkbox.setChecked(current_is_local_mode)
                    return
                
                # 先执行权限设置脚本，获取管理员权限并赋予目录写权限
                app_logger.info("正在执行程序目录权限设置脚本...")
                
                # 获取脚本路径和MinSudo路径
                script_path = get_long_path(os.path.join(BASE_DIR, "☆file_perm.bat")) if 'BASE_DIR' in globals() else ""
                sudo_path = get_long_path(os.path.join(BASE_DIR, "MinSudo.exe")) if 'BASE_DIR' in globals() else ""
                
                # 检查必要文件是否存在
                if not script_path or not os.path.exists(script_path):
                    app_logger.warning(f"权限设置脚本不存在: {script_path}")
                    # 脚本不存在时询问用户是否继续
                    reply = QMessageBox.question(
                        dialog, "提示",
                        "权限设置脚本不存在，无法自动设置目录权限。\n\n"
                        "后续可能因为权限问题无法保存配置文件。\n\n"
                        "是否仍要尝试切换到本地配置模式？",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No
                    )
                    if reply == QMessageBox.No:
                        local_config_checkbox.setChecked(current_is_local_mode)
                        return
                elif not sudo_path or not os.path.exists(sudo_path):
                    app_logger.warning(f"MinSudo组件不存在: {sudo_path}")
                    # 组件不存在时询问用户是否继续
                    reply = QMessageBox.question(
                        dialog, "提示",
                        "MinSudo组件不存在，无法自动设置目录权限。\n\n"
                        "后续可能因为权限问题无法保存配置文件。\n\n"
                        "是否仍要尝试切换到本地配置模式？",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No
                    )
                    if reply == QMessageBox.No:
                        local_config_checkbox.setChecked(current_is_local_mode)
                        return
                else:
                    # 显示执行提示
                    perm_msg = QMessageBox(dialog)
                    perm_msg.setWindowTitle("权限设置")
                    perm_msg.setText("正在设置程序目录权限...\n\n如果弹出管理员权限确认窗口，请点击\"是\"确认。")
                    perm_msg.setStandardButtons(QMessageBox.NoButton)
                    perm_msg.show()
                    # 强制刷新界面，确保对话框立即显示
                    QApplication.processEvents()
                    
                    # 使用 QEventLoop 同步等待执行完成
                    from PyQt5.QtCore import QEventLoop, QTimer
                    loop = QEventLoop()
                    
                    # 安全定时器：防止工作线程异常导致QEventLoop永久阻塞
                    # 超时时间比worker的30秒多5秒，正常情况下worker会先完成
                    safety_timer = QTimer()
                    safety_timer.setSingleShot(True)
                    safety_timer.timeout.connect(loop.quit)
                    safety_timer.start(35000)
                    
                    perm_worker = ElevatedScriptWorker("☆file_perm.bat", "设置目录权限", timeout=30)
                    perm_result = {'success': False, 'message': '', 'output': ''}
                    worker_finished_flag = [False]
                    
                    def on_perm_finished(success, message, output):
                        """工作线程完成回调"""
                        worker_finished_flag[0] = True
                        perm_result['success'] = success
                        perm_result['message'] = message
                        perm_result['output'] = output
                        safety_timer.stop()
                        loop.quit()
                    
                    perm_worker.finished.connect(on_perm_finished)
                    perm_worker.start()
                    
                    # 等待执行完成
                    loop.exec_()
                    
                    # 停止安全定时器（如果仍在运行）
                    safety_timer.stop()
                    
                    # 检查是否因安全定时器超时退出（工作线程未正常完成）
                    if not worker_finished_flag[0]:
                        app_logger.warning("权限设置工作线程未在预期时间内完成，可能已超时")
                        perm_result['success'] = False
                        perm_result['message'] = "权限设置操作超时，工作线程未在预期时间内完成"
                    
                    # 关闭提示对话框（检查对象是否仍有效，防止父对话框已关闭导致崩溃）
                    # 注意：必须先调用hide()再调用close()，否则在Windows上close()可能不会立即
                    # 从屏幕上移除窗口，导致后续弹出的对话框下方仍能看到此提示窗口
                    try:
                        from sip import isdeleted
                        if not isdeleted(perm_msg):
                            perm_msg.hide()
                            perm_msg.close()
                            perm_msg.deleteLater()
                    except ImportError:
                        perm_msg.hide()
                        perm_msg.close()
                        perm_msg.deleteLater()
                    except RuntimeError:
                        pass  # 对象已被Qt销毁，忽略
                    # 强制刷新界面，确保对话框立即关闭
                    QApplication.processEvents()
                    
                    if not perm_result['success']:
                        app_logger.warning(f"程序目录权限设置失败: {perm_result['message']}")
                        # 权限设置失败时询问用户是否继续
                        reply = QMessageBox.question(
                            dialog, "提示",
                            f"程序目录权限设置失败，可能无法写入配置文件。\n\n"
                            f"错误信息：{perm_result['message']}\n\n"
                            "是否仍要尝试切换到本地配置模式？",
                            QMessageBox.Yes | QMessageBox.No,
                            QMessageBox.No
                        )
                        if reply == QMessageBox.No:
                            local_config_checkbox.setChecked(current_is_local_mode)
                            return
                    else:
                        app_logger.info("程序目录权限设置成功")
                        # 权限设置成功，直接继续执行后续步骤，不需要额外提示
                
                # 创建 LOCAL_CONFIG 标志文件，使 save_config 使用程序目录
                try:
                    with open(local_config_flag, 'w', encoding='utf-8') as f:
                        f.write("")  # 创建空文件
                    app_logger.info(f"已创建本地配置标志文件: {local_config_flag}")
                except Exception as e:
                    error_msg = (
                        f"创建 LOCAL_CONFIG 文件失败: {e}\n\n"
                        "可能的原因：\n"
                        "- 程序所在目录没有写入权限\n"
                        "- 磁盘空间不足\n"
                        "- 杀毒软件拦截\n\n"
                        "建议：将程序移动到有写入权限的目录。"
                    )
                    QMessageBox.warning(dialog, "警告", error_msg)
                    local_config_checkbox.setChecked(current_is_local_mode)
                    return
                
                # 保存配置到程序目录
                if save_config():
                    QMessageBox.information(dialog, "成功", "已切换到本地配置模式，配置文件将保存在程序所在目录")
                    refresh_config_info()
                else:
                    # 保存失败，删除 LOCAL_CONFIG 标志文件，恢复之前的状态
                    try:
                        os.remove(local_config_flag)
                        app_logger.info(f"配置保存失败，已删除本地配置标志文件: {local_config_flag}")
                    except Exception as e:
                        app_logger.warning(f"删除 LOCAL_CONFIG 文件失败: {e}")
                    error_msg = (
                        "配置文件保存失败，已恢复到之前的配置模式。\n\n"
                        "可能的原因：\n"
                        "- 程序所在目录没有写入权限\n"
                        "- 磁盘空间不足\n"
                        "- 配置文件被其他程序占用\n\n"
                        "建议：将程序移动到有写入权限的目录。"
                    )
                    QMessageBox.warning(dialog, "警告", error_msg)
            else:
                # 用户选择 AppData 配置模式
                # 先删除 LOCAL_CONFIG 标志文件，使 save_config 使用 AppData 目录
                local_config_existed = False
                if current_is_local_mode and local_config_flag and os.path.isabs(local_config_flag):
                    local_config_existed = os.path.isfile(local_config_flag)
                    if local_config_existed:
                        try:
                            os.remove(local_config_flag)
                            app_logger.info(f"已删除本地配置标志文件: {local_config_flag}")
                        except Exception as e:
                            app_logger.warning(f"删除 LOCAL_CONFIG 文件失败: {e}")
                            # 删除失败时无法切换到AppData模式，中止操作
                            QMessageBox.warning(dialog, "警告",
                                f"无法删除本地配置标志文件，无法切换到 AppData 配置模式。\n\n"
                                f"错误信息：{e}")
                            local_config_checkbox.setChecked(True)
                            return
                
                # 保存配置到 AppData 目录
                if save_config():
                    QMessageBox.information(dialog, "成功", "已切换到 AppData 配置模式，配置文件将保存在系统AppData目录")
                    refresh_config_info()
                else:
                    # 保存失败，恢复 LOCAL_CONFIG 标志文件
                    if local_config_existed:
                        try:
                            with open(local_config_flag, 'w', encoding='utf-8') as f:
                                f.write("")
                            app_logger.info(f"配置保存失败，已恢复本地配置标志文件: {local_config_flag}")
                        except Exception as e:
                            app_logger.warning(f"恢复 LOCAL_CONFIG 文件失败: {e}")
                    error_msg = (
                        "配置文件保存失败，已恢复到之前的配置模式。\n\n"
                        "可能的原因：\n"
                        "- AppData 目录没有写入权限\n"
                        "- 磁盘空间不足\n"
                        "- 配置文件被其他程序占用\n\n"
                        "建议：检查 AppData 目录权限，或使用本地配置模式。"
                    )
                    QMessageBox.warning(dialog, "警告", error_msg)
        
        def reset_all_config():
            """重置所有配置为默认值"""
            # 弹出确认对话框
            reply = QMessageBox.question(
                dialog, "确认重置",
                "确定要将所有配置恢复为默认值吗？\n\n"
                "注意：配置保存位置（本地/AppData）不会被改变。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                # 重置全局配置为默认值
                global config
                config = DEFAULT_CONFIG.copy()
                
                # 重置日志级别
                set_log_level(DEFAULT_CONFIG["log_level"])
                
                # 重置分隔符
                CustomTableWidget.row_separator = unescape_separator(DEFAULT_CONFIG["row_separator"])
                CustomTableWidget.col_separator = unescape_separator(DEFAULT_CONFIG["col_separator"])
                
                # 保存配置到文件
                if save_config():
                    app_logger.info("所有配置已重置为默认值")
                    
                    # 更新所有设置界面控件的值
                    # 1. 复制自定义信息格式
                    copy_format_edit.setText(DEFAULT_CONFIG["copy_custom_format"])
                    copy_no_popup_checkbox.setChecked(DEFAULT_CONFIG["copy_custom_no_popup"])
                    
                    # 2. 批量重命名格式
                    rename_format_edit.setText(DEFAULT_CONFIG["rename_format"])
                    include_subdir_checkbox.setChecked(DEFAULT_CONFIG["rename_include_subdir"])
                    auto_number_checkbox.setChecked(DEFAULT_CONFIG["rename_auto_number"])
                    
                    # 3. 分隔符
                    default_row_sep = unescape_separator(DEFAULT_CONFIG["row_separator"])
                    default_col_sep = unescape_separator(DEFAULT_CONFIG["col_separator"])
                    
                    # 更新行间分隔符下拉框
                    found_row = False
                    for i in range(row_sep_combo.count() - 1):
                        if row_sep_combo.itemData(i) == default_row_sep:
                            row_sep_combo.setCurrentIndex(i)
                            found_row = True
                            break
                    if not found_row:
                        row_sep_combo.setCurrentIndex(row_sep_combo.count() - 1)
                        row_sep_custom.setText(default_row_sep)
                    
                    # 更新列间隔符下拉框
                    found_col = False
                    for i in range(col_sep_combo.count() - 1):
                        if col_sep_combo.itemData(i) == default_col_sep:
                            col_sep_combo.setCurrentIndex(i)
                            found_col = True
                            break
                    if not found_col:
                        col_sep_combo.setCurrentIndex(col_sep_combo.count() - 1)
                        col_sep_custom.setText(default_col_sep)
                    
                    # 4. 日志级别
                    log_level_combo.setCurrentText(DEFAULT_CONFIG["log_level"])
                    
                    # 5. Win11新版右键菜单选项（仅在Win11系统上存在此控件）
                    if WINDOWS_BUILD_VERSION >= 22000:
                        try:
                            win11_menu_checkbox.setChecked(DEFAULT_CONFIG["enable_win11_new_menu"])
                        except NameError:
                            pass  # 控件不存在时忽略
                    
                    # 6. 刷新配置信息选项卡
                    refresh_config_info()
                    
                    QMessageBox.information(dialog, "成功", "所有配置已重置为默认值并保存")
                else:
                    QMessageBox.warning(dialog, "警告", "配置保存失败，重置未生效")
        
        refresh_config_btn.clicked.connect(refresh_config_info)
        reset_all_config_btn.clicked.connect(reset_all_config)
        save_config_location_btn.clicked.connect(save_config_location)
        
        # 切换到配置信息选项卡时自动刷新
        def on_main_tab_changed(index):
            """主选项卡切换事件处理"""
            # 配置信息选项卡的索引为2（设置=0, 批量重命名=1, 配置信息=2, 关于=3）
            if index == 2:
                refresh_config_info()
        
        main_tab_widget.currentChanged.connect(on_main_tab_changed)
        
        def select_batch_dir():
            """选择批量重命名目录"""
            dir_path = QFileDialog.getExistingDirectory(dialog, "选择目录", "")
            if dir_path:
                # 转换为Windows风格的路径分隔符
                dir_path = os.path.normpath(dir_path)
                batch_dir_edit.setText(dir_path)
        
        batch_dir_btn.clicked.connect(select_batch_dir)
        
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
                dialog, "保存日志文件", default_filename, "文本文件 (*.txt);;所有文件 (*.*)"
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
        
        def execute_batch_rename():
            """执行批量重命名操作"""
            dir_path = batch_dir_edit.text().strip()
            if not dir_path:
                QMessageBox.warning(dialog, "警告", "请选择目录")
                return
            
            if not os.path.isdir(dir_path):
                QMessageBox.warning(dialog, "警告", "目录不存在")
                return
            
            rename_format = rename_format_edit.text().strip()
            if not rename_format:
                QMessageBox.warning(dialog, "警告", "请输入重命名格式")
                return
            
            include_subdir = include_subdir_checkbox.isChecked()
            auto_number = auto_number_checkbox.isChecked()
            
            apk_files = []
            if include_subdir:
                for root, dirs, files in os.walk(dir_path):
                    for file in files:
                        if file.lower().endswith('.apk'):
                            apk_files.append(os.path.join(root, file))
            else:
                for file in os.listdir(dir_path):
                    if file.lower().endswith('.apk'):
                        apk_files.append(os.path.join(dir_path, file))
            
            if not apk_files:
                QMessageBox.information(dialog, "提示", "未找到APK文件")
                return
            
            app_logger.info(f"开始批量重命名，目录: {dir_path}, 文件数: {len(apk_files)}, 包含子目录: {include_subdir}, 自动编号: {auto_number}")
            
            progress_dialog = QDialog(dialog)
            progress_dialog.setWindowTitle("批量重命名")
            progress_dialog.setMinimumSize(450, 350)
            progress_dialog.resize(500, 400)
            
            progress_layout = QVBoxLayout(progress_dialog)
            
            progress_label = QLabel(f"准备处理... 0/{len(apk_files)}")
            progress_label.setStyleSheet("font-size: 10pt; font-weight: bold;")
            progress_layout.addWidget(progress_label)
            
            progress_text = QTextEdit()
            progress_text.setReadOnly(True)
            progress_layout.addWidget(progress_text)
            
            btn_layout = QHBoxLayout()
            cancel_btn = QPushButton("取消")
            cancel_btn.setFixedWidth(80)
            btn_layout.addStretch()
            btn_layout.addWidget(cancel_btn)
            btn_layout.addStretch()
            progress_layout.addLayout(btn_layout)
            
            result_messages = []
            
            def update_progress(current, total, message):
                progress_label.setText(f"正在处理... {current}/{total}")
                progress_text.append(message)
                progress_text.verticalScrollBar().setValue(progress_text.verticalScrollBar().maximum())
            
            def on_file_processed(filename, status, message):
                if status == "成功":
                    color = "green"
                elif status == "跳过":
                    color = "#888888"
                else:
                    color = "red"
                progress_text.append(f'<span style="color: {color};">[{status}] {filename}: {message}</span>')
                progress_text.verticalScrollBar().setValue(progress_text.verticalScrollBar().maximum())
            
            def on_finished(messages, success, fail, skip):
                if worker.stop_flag:
                    progress_label.setText(f"已取消！成功: {success}, 失败: {fail}, 跳过: {skip}")
                else:
                    progress_label.setText(f"处理完成！成功: {success}, 失败: {fail}, 跳过: {skip}")
                cancel_btn.setText("关闭")
                cancel_btn.setEnabled(True)
                app_logger.info(f"批量重命名完成，成功: {success}, 失败: {fail}, 跳过: {skip}")
            
            worker = BatchRenameWorker(apk_files, rename_format, auto_number)
            worker.progress_update.connect(update_progress)
            worker.file_processed.connect(on_file_processed)
            worker.finished.connect(on_finished)
            
            def on_cancel():
                if worker.isRunning():
                    worker.stop()
                    progress_label.setText("正在取消...")
                    cancel_btn.setText("请稍候...")
                else:
                    progress_dialog.close()
            
            cancel_btn.clicked.connect(on_cancel)
            
            progress_dialog.rejected.connect(lambda: worker.stop() if worker.isRunning() else None)
            
            worker.start()
            progress_dialog.exec_()
            
            if worker.isRunning():
                worker.stop()
                worker.wait(1000)
        
        execute_btn.clicked.connect(execute_batch_rename)
        
        # === 各选项卡保存/恢复默认功能 ===
        
        def save_copy_settings():
            """保存复制设置"""
            copy_format = copy_format_edit.text().strip()
            valid, err_msg = validate_format(copy_format, "格式模板")
            if not valid:
                QMessageBox.warning(dialog, "警告", err_msg)
                return
            config["copy_custom_format"] = copy_format
            config["copy_custom_no_popup"] = copy_no_popup_checkbox.isChecked()
            if save_config():
                app_logger.info(f"复制设置已保存: {copy_format}, 不弹框提示: {copy_no_popup_checkbox.isChecked()}")
                QMessageBox.information(dialog, "成功", "复制设置已保存")
            else:
                QMessageBox.warning(dialog, "警告", "配置保存失败")
        
        def reset_copy_settings():
            """恢复复制设置默认值"""
            copy_format_edit.setText(DEFAULT_CONFIG["copy_custom_format"])
            copy_no_popup_checkbox.setChecked(DEFAULT_CONFIG["copy_custom_no_popup"])
            app_logger.debug("复制设置已恢复默认值")
        
        copy_save_btn.clicked.connect(save_copy_settings)
        copy_reset_btn.clicked.connect(reset_copy_settings)
        
        def save_batch_rename_settings():
            """保存批量重命名设置"""
            rename_format = rename_format_edit.text().strip()
            valid, err_msg = validate_format(rename_format, "重命名格式")
            if not valid:
                QMessageBox.warning(dialog, "警告", err_msg)
                return
            config["rename_format"] = rename_format
            config["rename_include_subdir"] = include_subdir_checkbox.isChecked()
            config["rename_auto_number"] = auto_number_checkbox.isChecked()
            if save_config():
                app_logger.info(f"批量重命名设置已保存: {rename_format}, 自动编号: {auto_number_checkbox.isChecked()}")
                QMessageBox.information(dialog, "成功", "批量重命名设置已保存")
            else:
                QMessageBox.warning(dialog, "警告", "配置保存失败")
        
        def reset_batch_rename_settings():
            """恢复批量重命名设置默认值"""
            rename_format_edit.setText(DEFAULT_CONFIG["rename_format"])
            include_subdir_checkbox.setChecked(DEFAULT_CONFIG["rename_include_subdir"])
            auto_number_checkbox.setChecked(DEFAULT_CONFIG["rename_auto_number"])
            app_logger.debug("批量重命名设置已恢复默认值")
        
        batch_rename_save_btn.clicked.connect(save_batch_rename_settings)
        batch_rename_reset_btn.clicked.connect(reset_batch_rename_settings)
        
        def save_separator_settings():
            """保存分隔符设置"""
            row_sep = row_sep_combo.currentData()
            if row_sep is None:
                row_sep = parse_separator(row_sep_custom.text())
            
            col_sep = col_sep_combo.currentData()
            if col_sep is None:
                col_sep = parse_separator(col_sep_custom.text())
            
            valid, err_msg = validate_separator(row_sep, "行间分隔符")
            if not valid:
                QMessageBox.warning(dialog, "警告", err_msg)
                return
            
            valid, err_msg = validate_separator(col_sep, "列间隔符")
            if not valid:
                QMessageBox.warning(dialog, "警告", err_msg)
                return
            
            CustomTableWidget.row_separator = row_sep
            CustomTableWidget.col_separator = col_sep
            config["row_separator"] = escape_separator(row_sep)
            config["col_separator"] = escape_separator(col_sep)
            
            if save_config():
                app_logger.info(f"分隔符设置已保存: 行间分隔符={repr(row_sep)}, 列间隔符={repr(col_sep)}")
                QMessageBox.information(dialog, "成功", "分隔符设置已保存")
            else:
                QMessageBox.warning(dialog, "警告", "配置保存失败")
        
        def reset_separator_settings():
            """恢复分隔符设置默认值"""
            default_row_sep = unescape_separator(DEFAULT_CONFIG["row_separator"])
            default_col_sep = unescape_separator(DEFAULT_CONFIG["col_separator"])
            
            found_row = False
            for i in range(row_sep_combo.count() - 1):
                if row_sep_combo.itemData(i) == default_row_sep:
                    row_sep_combo.setCurrentIndex(i)
                    found_row = True
                    break
            if not found_row:
                row_sep_combo.setCurrentIndex(row_sep_combo.count() - 1)
                row_sep_custom.setEnabled(True)
                row_sep_custom.setText(default_row_sep)
            
            found_col = False
            for i in range(col_sep_combo.count() - 1):
                if col_sep_combo.itemData(i) == default_col_sep:
                    col_sep_combo.setCurrentIndex(i)
                    found_col = True
                    break
            if not found_col:
                col_sep_combo.setCurrentIndex(col_sep_combo.count() - 1)
                col_sep_custom.setEnabled(True)
                col_sep_custom.setText(default_col_sep)
            
            app_logger.debug("分隔符设置已恢复默认值")
        
        separator_save_btn.clicked.connect(save_separator_settings)
        separator_reset_btn.clicked.connect(reset_separator_settings)
        
        def save_log_settings():
            """保存日志设置"""
            selected_level = log_level_combo.currentText()
            set_log_level(selected_level)
            config["log_level"] = selected_level
            if save_config():
                app_logger.info(f"日志级别已设置为: {selected_level}")
                QMessageBox.information(dialog, "成功", "日志设置已保存")
            else:
                QMessageBox.warning(dialog, "警告", "配置保存失败")
        
        log_save_btn.clicked.connect(save_log_settings)
        
        def reset_log_settings():
            """恢复日志设置默认值"""
            default_level = DEFAULT_CONFIG.get("log_level", "INFO")
            log_level_combo.setCurrentText(default_level)
            app_logger.debug(f"日志级别已恢复默认值: {default_level}")
        
        log_reset_btn.clicked.connect(reset_log_settings)
        
        # 关闭按钮点击事件
        close_btn.clicked.connect(dialog.reject)
        
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
        """验证APK文件是否有效（检查路径是否为文件、是否为ZIP格式并包含AndroidManifest.xml）"""
        # 检查路径是否存在
        if not os.path.exists(apk_path):
            return False, f"解析失败，路径不存在：\n{apk_path}"
        
        # 检查路径是否为目录
        if os.path.isdir(apk_path):
            return False, f"解析失败，路径是目录而非文件：\n{apk_path}"
        
        # 检查路径是否为文件
        if not os.path.isfile(apk_path):
            return False, f"解析失败，路径不是有效的文件：\n{apk_path}"
        
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
            self.copy_custom_info_button.setEnabled(True)    # 复制自定义信息按钮
            self.copy_info_button.setEnabled(True)
            self.save_info_button.setEnabled(True)
            
            # 清理线程资源
            if self.worker_thread:
                self.worker_thread.quit()
                self.worker_thread.wait()
                self.worker_thread = None
            self.worker = None


class LocaleListDialog(QDialog):
    """
    语言列表详情对话框。
    
    显示APK支持的所有语言列表，包含语言代码、语言名称和中文名称。
    支持实时搜索过滤、Ctrl+C快捷键复制和复制选中内容。
    
    Attributes:
        locales: 语言代码列表
        search_input: 搜索输入框
        table: 语言列表表格
    """
    
    def __init__(self, locales, parent=None):
        """
        初始化语言列表对话框。
        
        Args:
            locales: 语言代码列表，如 ['en-US', 'zh-CN', 'ja']
            parent: 父窗口
        """
        super().__init__(parent)
        self.setWindowTitle("支持的语言列表")
        self.setModal(True)
        self.resize(400, 360)
        
        self.locales = locales or []
        
        layout = QVBoxLayout()
        layout.setSpacing(10)
        
        # 顶部说明和搜索框
        top_layout = QHBoxLayout()
        count_label = QLabel(f"共 {len(self.locales)} 种语言")
        count_label.setStyleSheet("font-weight: bold;")
        top_layout.addWidget(count_label)
        
        top_layout.addStretch()
        
        search_label = QLabel("搜索:")
        top_layout.addWidget(search_label)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入语言代码或名称...")
        self.search_input.setFixedWidth(160)
        self.search_input.textChanged.connect(self.filter_table)
        top_layout.addWidget(self.search_input)
        
        layout.addLayout(top_layout)
        
        # 语言列表表格（使用 CustomTableWidget 以支持右键菜单）
        self.table = CustomTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["语言代码", "语言名称", "中文名称"])
        # 允许用户拖拽调整列宽
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        # 设置默认列宽
        self.table.setColumnWidth(0, 100)
        self.table.setColumnWidth(1, 140)
        self.table.setColumnWidth(2, 140)
        self.table.horizontalHeader().setHighlightSections(False)  # 禁用表头在选中时高亮
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(True)  # 显示网格线
        # 启用表头点击排序
        self.table.setSortingEnabled(True)
        # 添加表格样式（包括选中状态和排序指示器）
        
        # 填充表格数据
        self.populate_table()
        
        layout.addWidget(self.table)
        
        # 提示文字（放在按钮上方，居中）
        tip_label = QLabel("提示: 支持某种语言并不代表应用可以正常使用该语言")
        tip_label.setStyleSheet("color: blue; ")
        tip_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(tip_label)
        
        # 底部按钮（居中）
        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()
        
        copy_btn = QPushButton("复制选中")
        copy_btn.setFixedWidth(80)
        copy_btn.setToolTip("复制选中行的语言信息到剪贴板")
        copy_btn.clicked.connect(self.copy_selected)
        bottom_layout.addWidget(copy_btn)
        
        close_btn = QPushButton("关闭")
        close_btn.setFixedWidth(80)
        close_btn.clicked.connect(self.close)
        bottom_layout.addWidget(close_btn)
        
        bottom_layout.addStretch()
        
        layout.addLayout(bottom_layout)
        
        self.setLayout(layout)
        
        # 默认聚焦到搜索框
        self.search_input.setFocus()
    
    def keyPressEvent(self, event):
        """
        键盘事件处理，支持 Ctrl+C 复制选中内容。
        
        Args:
            event: QKeyEvent 键盘事件对象
        """
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_C:
            self.copy_selected()
        else:
            super().keyPressEvent(event)
    
    def populate_table(self, filter_text=""):
        """
        填充语言列表表格。
        
        Args:
            filter_text: 过滤文本，为空则显示全部
        """
        # 填充数据前先禁用排序，避免排序状态与数据不同步导致单元格消失
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        filter_lower = filter_text.lower()
        
        for locale in self.locales:
            # 获取语言名称，未知语言显示"未知"
            if locale in LOCALE_NAME_MAP:
                locale_info = LOCALE_NAME_MAP[locale]
                zh_name = locale_info[0]
                en_name = locale_info[1]
            else:
                # 未知语言代码，显示代码本身
                zh_name = f"未知语言"
                en_name = f"Unknown ({locale})"
            
            # 过滤判断
            if filter_text:
                if (filter_lower not in locale.lower() and 
                    filter_lower not in zh_name.lower() and 
                    filter_lower not in en_name.lower()):
                    continue
            
            # 添加行
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(locale))
            self.table.setItem(row, 1, QTableWidgetItem(en_name))
            self.table.setItem(row, 2, QTableWidgetItem(zh_name))
        
        # 根据内容自动调整所有行高
        self.table.resizeRowsToContents()
        
        # 填充完成后重新启用排序
        self.table.setSortingEnabled(True)
    
    def filter_table(self, text):
        """
        根据搜索文本过滤表格内容。
        
        Args:
            text: 搜索文本
        """
        self.populate_table(text)
    
    def copy_selected(self):
        """
        复制选中行的语言信息到剪贴板。
        
        使用设置的分隔符（CustomTableWidget.row_separator 和 col_separator）。
        格式: 语言代码{col_separator}语言名称{col_separator}中文名称
        """
        selected_rows = self.table.selectedItems()
        if not selected_rows:
            return
        
        # 获取选中的行号（去重）
        rows = set()
        for item in selected_rows:
            rows.add(item.row())
        
        # 获取设置的分隔符
        col_sep = CustomTableWidget.col_separator
        row_sep = CustomTableWidget.row_separator
        
        # 构建复制内容
        lines = []
        for row in sorted(rows):
            # 获取各列数据，添加空值检查防止异常
            locale_item = self.table.item(row, 0)
            en_name_item = self.table.item(row, 1)
            zh_name_item = self.table.item(row, 2)
            
            # 如果任何单元格为空，跳过该行
            if not locale_item or not en_name_item or not zh_name_item:
                app_logger.warning(f"语言列表复制时发现空单元格，跳过行 {row}")
                continue
            
            locale = locale_item.text()
            en_name = en_name_item.text()
            zh_name = zh_name_item.text()
            lines.append(col_sep.join([locale, en_name, zh_name]))
        
        if lines:
            clipboard = QApplication.clipboard()
            clipboard.setText(row_sep.join(lines))
            app_logger.debug(f"已复制 {len(lines)} 条语言信息到剪贴板")


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
            certs: 证书字典列表，每个字典包含 der_data 和 md5 等字段
        """
        if certs:
            for cert in certs:
                try:
                    der_data = cert.get('der_data') if isinstance(cert, dict) else cert
                    if der_data:
                        self.certs_hash.append({
                            "MD5": hashlib.md5(der_data).hexdigest().upper(),
                            "SHA1": hashlib.sha1(der_data).hexdigest().upper(),
                            "SHA256": hashlib.sha256(der_data).hexdigest().upper(),
                            "SHA512": hashlib.sha512(der_data).hexdigest().upper(),
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


def get_apk_basic_info(apk_path):
    """
    获取APK文件的基本信息（用于批量处理）
    
    创建临时的APKParser实例，快速获取APK的基本信息，
    包括包名、应用名、版本号等。适用于批量处理场景。
    
    Args:
        apk_path: APK文件的完整路径
    
    Returns:
        dict: 包含基本信息的字典，格式如下：
            {
                'app_name': str,          # 应用名称（默认标签）
                'chinese_app_name': str,  # 中文名称（如果有）
                'package_name': str,      # 包名
                'version_name': str,      # 版本号
                'version_code': str,      # 内部版本号
                'min_sdk_version': str,   # 最低SDK版本
                'target_sdk_version': str, # 目标SDK版本
                'compile_sdk_version': str, # 编译SDK版本
                'arch_support': str,      # 支持架构
                'permissions_count': int, # 权限数量
                'file_size': str,         # 文件大小
                'file_md5': str,          # 文件MD5值
                'cert_md5': str           # 证书MD5值
            }
        如果解析失败则返回 None
    """
    try:
        parser = APKParser(apk_path)
        basic_info = parser.get_basic_info()
        
        if not basic_info:
            app_logger.warning(f"无法获取APK基本信息: {apk_path}")
            return None
        
        arch_info = parser.analyze_arch_support()
        permissions = parser.get_permissions()
        sig_info = parser.get_signature_info()
        
        file_size = os.path.getsize(apk_path)
        if file_size >= 1024 * 1024:
            file_size_str = f"{file_size / (1024 * 1024):.2f} MB"
        elif file_size >= 1024:
            file_size_str = f"{file_size / 1024:.2f} KB"
        else:
            file_size_str = f"{file_size} B"
        
        md5_hash = hashlib.md5()
        with open(apk_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                md5_hash.update(chunk)
        file_md5_str = md5_hash.hexdigest().upper()
        
        cert_md5 = ''
        certs = sig_info.get('certificates', [])
        if certs and len(certs) > 0:
            cert_md5 = certs[0].get('md5', '')
        
        result = {
            'app_name': basic_info.get('application_label', ''),
            'chinese_app_name': basic_info.get('application_label_zh', ''),
            'package_name': basic_info.get('package_name', ''),
            'version_name': basic_info.get('version_name', ''),
            'version_code': basic_info.get('version_code', ''),
            'min_sdk_version': basic_info.get('sdk_version', ''),
            'target_sdk_version': basic_info.get('target_sdk_version', ''),
            'compile_sdk_version': basic_info.get('compile_sdk_version', ''),
            'arch_support': arch_info.get('display_text', ''),
            'permissions_count': len(permissions),
            'file_size': file_size_str,
            'file_md5': file_md5_str,
            'cert_md5': cert_md5
        }
        
        app_logger.debug(f"成功获取APK基本信息: {apk_path} -> {result.get('package_name', 'unknown')}")
        return result
        
    except Exception as e:
        app_logger.error(f"解析APK基本信息失败: {apk_path}, 错误: {str(e)}")
        return None

def batch_process_directory(directory):
    """
    批量处理目录下所有APK文件
    
    参数:
        directory: APK文件所在目录
    """
    start_time = time.time()
    
    if not os.path.isdir(directory):
        app_logger.error(f"目录不存在: {directory}")
        return
    
    # 递归获取所有APK文件
    apk_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.lower().endswith('.apk'):
                apk_files.append(os.path.join(root, file))
    
    # 按文件名排序
    apk_files = sorted(apk_files, key=lambda x: os.path.basename(x).lower())
    
    if not apk_files:
        app_logger.warning(f"在目录 {directory} 下未找到APK文件")
        return
    
    total_count = len(apk_files)
    success_count = 0
    fail_count = 0
    
    app_logger.info(f"找到 {total_count} 个APK文件")
    app_logger.info(f"开始批量处理目录: {directory}")
    
    for i, apk_path in enumerate(apk_files, 1):
        apk_name = os.path.basename(apk_path)
        app_logger.info("="*60)
        app_logger.info(f"[{i}/{total_count}] 处理: {apk_name}")
        
        apk_start_time = time.time()
        try:
            with APKParser(apk_path) as parser:
                saved_count = parser.save_all_xml_icons()
                apk_elapsed_time = time.time() - apk_start_time
                if saved_count >= 0:
                    success_count += 1
                    app_logger.info(f"  -> 成功，保存了 {saved_count} 个XML图标，耗时: {apk_elapsed_time:.2f}秒")
                else:
                    fail_count += 1
                    app_logger.warning(f"  -> 失败，耗时: {apk_elapsed_time:.2f}秒")
        except Exception as e:
            apk_elapsed_time = time.time() - apk_start_time
            fail_count += 1
            app_logger.error(f"  -> 失败: {e}，耗时: {apk_elapsed_time:.2f}秒")
    
    elapsed_time = time.time() - start_time
    app_logger.info("="*60)
    app_logger.info(f"批量处理完成!")
    app_logger.info(f"总计: {total_count}, 成功: {success_count}, 失败: {fail_count}, 总耗时: {elapsed_time:.2f}秒")


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
    
    # 加载配置文件
    load_config()
    
    # 检测Windows系统build版本号
    global WINDOWS_BUILD_VERSION
    try:
        WINDOWS_BUILD_VERSION = sys.getwindowsversion().build
        app_logger.debug(f"检测到Windows系统build版本号: {WINDOWS_BUILD_VERSION}")
    except Exception as e:
        app_logger.warning(f"获取Windows系统build版本号失败: {e}")
        WINDOWS_BUILD_VERSION = 0
    
    # 应用配置文件中的分隔符设置
    if "row_separator" in config:
        CustomTableWidget.row_separator = unescape_separator(config["row_separator"])
    if "col_separator" in config:
        CustomTableWidget.col_separator = unescape_separator(config["col_separator"])
    
    # 解析命令行参数，支持 -h, --help
    parser = argparse.ArgumentParser(
        description=f'APK文件信息解析工具 {b_ver}-{b_date}',
        formatter_class=ChineseHelpFormatter,
        epilog='''
示例:
  %(prog)s app.apk                    # 解析单个APK文件（启动GUI）
  %(prog)s -b E:\\APK                  # 批量解析该目录下所有APK文件的XML图标（保存所有XML图标到cache目录）
  %(prog)s -l DEBUG app.apk           # 设置日志级别为DEBUG并启动GUI
        '''
    )
    parser.add_argument('apk_file', nargs='?', help='要解析的APK文件路径')
    parser.add_argument('-l', '--log-level', 
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'D', 'I', 'W', 'E'],
                       default=None,
                       help='设置日志级别，覆盖配置文件设置。支持简写: D=DEBUG, I=INFO, W=WARNING, E=ERROR')
    parser.add_argument('-b', '--batch-dir', metavar='DIR',
                       help='批量解析指定目录下所有APK文件的XML图标，并保存所有XML图标到cache目录')
    args = parser.parse_args()
    
    # 确定日志级别（优先级：命令行 > 配置文件 > 默认值）
    log_level_map = {
        'D': 'DEBUG',
        'I': 'INFO',
        'W': 'WARNING',
        'E': 'ERROR'
    }
    
    if args.log_level:
        log_level = args.log_level
        if log_level in log_level_map:
            log_level = log_level_map[log_level]
        app_logger.debug(f"使用命令行指定的日志级别: {log_level}")
    elif "log_level" in config:
        log_level = config["log_level"]
        app_logger.debug(f"使用配置文件中的日志级别: {log_level}")
    else:
        log_level = DEFAULT_LOG_LEVEL
        app_logger.debug(f"使用默认日志级别: {log_level}")
    
    set_log_level(log_level)
    
    # 如果提供了APK文件路径参数，传递给主程序进行处理，这里不做文件路径检测。
    apk_file_path = args.apk_file
    if args.apk_file:
        if os.path.isfile(args.apk_file):
            apk_file_path = os.path.abspath(args.apk_file)
    
    # 批量处理目录模式
    if args.batch_dir:
        batch_process_directory(args.batch_dir)
        sys.exit(0)
    
    # 启用高 DPI 缩放、启用高 DPI 位图支持
    QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    # 更精细的DPI控制，保持原始比例（不四舍五入），确保UI和文字同时按缩放比例缩放
    # 例如125%缩放时，UI和文字都放大1.25倍，不会出现文字超出UI范围的问题
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    
    # 全局禁用 Windows 窗口标题栏上的“上下文帮助按钮”（也就是那个问号按钮）
    QCoreApplication.setAttribute(Qt.AA_DisableWindowContextHelpButton)
    
    app = QApplication(sys.argv)
    
    # 全局样式表：统一设置所有控件的字体大小和字体族，确保高DPI缩放时字体正确显示
    # font-family回退链：宋体 → 微软雅黑 → 黑体 → 系统默认无衬线字体
    # 宋体(SimSun)：所有中文Windows系统自带，兼容性最强
    # 微软雅黑：Windows Vista及以上系统自带，中文显示最佳
    # 黑体(SimHei)：Windows XP及以上系统自带，中文显示良好
    # sans-serif：系统默认无衬线字体，最终回退
    # 使用pt单位可根据系统DPI自动缩放，避免px单位在高DPI下字体大小异常
    # 已有的单独setStyleSheet中的font-size设置会覆盖此全局设置（CSS优先级规则）
    # padding: 上 右 下 左;
    app.setStyleSheet("""
        QLabel { font-family: "SimSun", "Microsoft YaHei", "SimHei", sans-serif; font-size: 9pt; }
        QPushButton { font-family: "SimSun", "Microsoft YaHei", "SimHei", sans-serif; font-size: 9pt; }
        QTextEdit { font-family: "SimSun", "Microsoft YaHei", "SimHei", sans-serif; font-size: 9pt; }
        QLineEdit { font-family: "SimSun", "Microsoft YaHei", "SimHei", sans-serif; font-size: 9pt; }
        QGroupBox { font-family: "SimSun", "Microsoft YaHei", "SimHei", sans-serif; font-size: 9pt; }
        QCheckBox { font-family: "SimSun", "Microsoft YaHei", "SimHei", sans-serif; font-size: 9pt; }
        QComboBox { font-family: "SimSun", "Microsoft YaHei", "SimHei", sans-serif; font-size: 9pt; }
        QTabBar { font-family: "SimSun", "Microsoft YaHei", "SimHei", sans-serif; font-size: 9pt; }
        QMenu { font-family: "SimSun", "Microsoft YaHei", "SimHei", sans-serif; font-size: 9pt; }
        QMessageBox { font-family: "SimSun", "Microsoft YaHei", "SimHei", sans-serif; font-size: 9pt; }
        QToolTip { font-family: "SimSun", "Microsoft YaHei", "SimHei", sans-serif; font-size: 9pt; }
    """)
    
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
