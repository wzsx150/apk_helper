

### APK文件信息解析工具-APK Helper

一个可以解析安卓安装包apk信息的工具（仅支持Windows系统），主要借助aapt2工具对apk进行解析。通过将python脚本打包成exe程序，可以部署到Windows系统中，并可以关联apk文件，实现双击apk文件查看相关信息。其中比较复杂的部分是对安卓各种类型图标的读取解析，占了很大一部分，由于手头样例有限，应该还存在一些无法正确解析图标的情况。



#### 前言

本程序主要是受X-Star大佬制作的 APK文件信息解析工具APK Helper 3.3 的启发，一直在用他的这个工具（old_apk_helper目录下），已经不太适应新版apk。因为大佬已经不再更新，所以仿照他的工具，编写了这个工具。大佬的旧版工具截图如下：

<img src="README.assets/apk helper-3.3.png" alt="apk helper-3.3" style="zoom:50%;" />



#### 本工具主要功能

- 查看应用图标（多种图标类型）和基本信息
- 查看应用权限
- 查看签名信息
- 复制应用信息的文本
- 保存应用信息的文本
- 保存应用图标
- 比较签名证书哈希值，查看是不是同一个作者制作
- 支持拖拽APK文件到窗口

本工具截图如下：



<img src="README.assets/apk helper-new.png" style="zoom:50%;" />

#### 使用方法

1. 直接运行python3脚本

环境依赖请查看后面章节

```python
python apk_helper.py
```

注：另外，apk_helper_test_androguard.py是androguard版，使用 androguard 库进行解析，功能没有 aapt2 版完整，基本也能使用。其他.py文件基本都为测试文件。



2. 运行独立版exe版程序

从release中下载制作好的exe程序绿色版压缩包，解压后，运行apk_helper.exe。该程序自带python依赖，无须在系统中安装python和依赖库。

也可以命令行里调用，直接解析某一个apk：

```
apk_helper.exe 1.apk
```



其他命令：

```cmd
py3.8_32 apk_helper.py -b E:\APP -l DEBUG > logs\20260306-11.txt
```



#### 环境依赖

如果直接运行python脚本，则需要安装python环境。如果直接下载exe程序，则不需要安装python环境。

操作系统：Windows 7+

python版本：python 3.8+

python库：（pillow和PyQt5是必须）

```cmd
pip install pillow PyQt5  nuitka androguard asn1crypto  -i https://pypi.tuna.tsinghua.edu.cn/simple/
```

aapt2工具版本：2.19 (build-tools_r33.0.3内置的版本，32位)



#### 打包成exe程序

python 3.8.10是python支持win7的最后一个版本，所以这里选用python 3.8 32位的python进行打包生成exe程序。

python 3.8 32位版仅支持androguard-4.0.1，更高版本的androguard需要新版python。

打包成独立版exe的命令（aapt2版）：

```cmd
py3.8_32 -m nuitka --standalone --assume-yes-for-downloads --windows-console-mode=disable --output-dir=dist --enable-plugin=pyqt5 --windows-icon-from-ico=1.ico --include-data-files=1.ico=./ --include-data-files=aapt2.exe=./ --include-data-files=*.bat=./ --include-raw-dir=translations=translations apk_helper.py
```

或如下androguard版（不推荐）：

```
py3.8_32 -m nuitka --standalone --assume-yes-for-downloads --windows-console-mode=disable --output-dir=dist --enable-plugin=pyqt5 --include-package-data=androguard --windows-icon-from-ico=1.ico --include-data-files=1.ico=./ --include-data-files=aapt2.exe=./ --include-data-files=*.bat=./ --include-raw-dir=translations=translations apk_helper_test_androguard.py
```



#### Windows关联apk文件

使用bat脚本关联apk文件，Windows系统注册表关联.apk文件的相关表项：

```reg
HKCR\ApkFile.apkhelper
HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.apk
```

具体实现，参考☆reg_apk.bat、☆unreg_apk.bat文件



#### 相关算法源码参考

tools/aapt2 - platform/frameworks/base - Git at Google  https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android13-release/tools/aapt2/

graphics/java/android/graphics/drawable - platform/frameworks/base - Git at Google  https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android16-release/graphics/java/android/graphics/drawable

core/res/res/values - platform/frameworks/base - Git at Google  https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android16-release/core/res/res/values/

core/res/res/color - platform/frameworks/base - Git at Google  https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android16-release/core/res/res/color/

libs/hwui - platform/frameworks/base - Git at Google  https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android16-release/libs/hwui/

libs/androidfw - platform/frameworks/base - Git at Google  https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android16-release/libs/androidfw/

core/java/android/util/PathParser.java - platform/frameworks/base - Git at Google  https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android16-release/core/java/android/util/PathParser.java



Drawable resources  |  App architecture  |  Android Developers  https://developer.android.google.cn/guide/topics/resources/drawable-resource

android.graphics.drawable  |  API reference  |  Android Developers  https://developer.android.google.cn/reference/android/graphics/drawable/package-summary



##### 注意

- 当前目录下的apk_helper.exe文件是演示程序，是other目录下apk_helper.bat使用Bat_To_Exe_Converter工具转化成exe。仅作为关联apk文件的演示功能。


- 从release中下载制作好的exe程序绿色版压缩包，解压后，运行apk_helper.exe。该程序自带python依赖，无须在系统中安装python和依赖库。


- 打包生成的exe是32位还是64位，主要是看打包exe时使用的python的版本。如果python是32位版则打包出来的是32位exe成，64位同理。

- 解析的图标可能不一定准确，甚至有些无法解析，可能存在不兼容或者不适配的情况。

- aapt2-android13-release 目录是存放的从官方下载的aapt2的源码。

- android16-release 目录是存放的从官方下载的安卓部分源码。

- androguard-4.0.1需要修改androguard库中 <Python安装目录>\Lib\site-packages\androguard\core\apk\__init__.py 的源码，解决部分apk解析时报错的问题，将两行代码的raise ResParserError改成logger.warning。修改完成后的代码如下：

  ```
  class ARSCResTypeSpec:
  '''......'''
          if self.res0 != 0:
              logger.warning("res0 must be zero!")
          if self.res1 != 0:
              logger.warning("res1 must be zero!")
  '''......'''
  ```

  







