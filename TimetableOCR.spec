# -*- mode: python ; coding: utf-8 -*-
import os

import winrt.windows.globalization

binaries = []
_globalization = os.path.dirname(winrt.windows.globalization.__file__)
_winrt_root = os.path.dirname(os.path.dirname(_globalization))
_msvcp = os.path.join(_winrt_root, "msvcp140.dll")
if os.path.exists(_msvcp):
    binaries.append((_msvcp, "."))

hiddenimports = [
    'winrt.runtime',
    'winrt.system',
    'winrt.windows.foundation',
    'winrt.windows.foundation.collections',
    'winrt.windows.globalization',
    'winrt.windows.graphics.imaging',
    'winrt.windows.media.ocr',
    'winrt.windows.storage',
    'winrt.windows.storage.streams',
]

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=binaries,
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch', 'matplotlib', 'scipy', 'pandas', 'sympy', 'tensorflow',
        'onnxruntime', 'rapidocr_onnxruntime', 'cv2', 'numpy', 'shapely',
        'pyclipper', 'tkinter',
        'PyQt5.QtWebEngine', 'PyQt5.QtWebEngineWidgets', 'PyQt5.QtQml',
        'PyQt5.QtQuick', 'PyQt5.QtMultimedia', 'PyQt5.QtSql',
        'PyQt5.QtTest', 'PyQt5.QtBluetooth', 'PyQt5.QtNfc',
    ],
    noarchive=False,
    optimize=0,
)

# 纯 Widgets 应用不需要 OpenGL 软件渲染、Qt Quick/QML、ANGLE、网络、DBus、SVG，
# 也不需要 WebP/TIFF/TGA/WBMP/ICNS 图片插件和 Pillow 的字体/WebP/色彩管理模块。
_DROP_BINARIES = (
    'PyQt5/Qt5/bin/opengl32sw.dll',
    'PyQt5/Qt5/bin/Qt5Quick',
    'PyQt5/Qt5/bin/Qt5Qml',
    'PyQt5/Qt5/bin/d3dcompiler_47.dll',
    'PyQt5/Qt5/bin/libGLESv2.dll',
    'PyQt5/Qt5/bin/libEGL.dll',
    'PyQt5/Qt5/bin/Qt5Network.dll',
    'PyQt5/Qt5/bin/Qt5DBus.dll',
    'PyQt5/Qt5/bin/Qt5WebSockets.dll',
    'PyQt5/Qt5/bin/Qt5Svg.dll',
    'PyQt5/Qt5/plugins/platforms/qminimal.dll',
    'PyQt5/Qt5/plugins/platforms/qoffscreen.dll',
    'PyQt5/Qt5/plugins/platforms/qwebgl.dll',
    'PyQt5/Qt5/plugins/platformthemes/qxdgdesktopportal.dll',
    'PyQt5/Qt5/plugins/imageformats/qwebp.dll',
    'PyQt5/Qt5/plugins/imageformats/qtiff.dll',
    'PyQt5/Qt5/plugins/imageformats/qicns.dll',
    'PyQt5/Qt5/plugins/imageformats/qsvg.dll',
    'PyQt5/Qt5/plugins/imageformats/qtga.dll',
    'PyQt5/Qt5/plugins/imageformats/qwbmp.dll',
    'PyQt5/Qt5/plugins/iconengines/qsvgicon.dll',
    'PIL/_avif',
    'PIL/_imagingft',
    'PIL/_webp',
    'PIL/_imagingcms',
)
a.binaries = [
    entry for entry in a.binaries
    if not entry[0].replace('\\', '/').startswith(_DROP_BINARIES)
]

# Qt 自带翻译文件本应用未加载（没有 QTranslator），全部移除以减小体积
a.datas = [
    entry for entry in a.datas
    if not entry[0].replace('\\', '/').lower().endswith('.qm')
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TimetableOCR',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TimetableOCR',
)
