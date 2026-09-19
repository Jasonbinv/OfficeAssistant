办公文件助手 — 第三方许可说明

本绿色包内含 Python 运行时及下列开源组件。Qt / PySide6 以动态库方式链接（.dll），
未静态编入可执行文件。许可全文见本目录；打包时另通过 PyInstaller collect_all
收集 PySide6 自带的 LICENSE 文件。

1. Python
   许可：PSF License
   用途：解释器与标准库

2. PySide6（Qt for Python）
   许可：LGPL v3（Qt 为动态库）
   用途：桌面界面
   说明：随包分发 Qt6*.dll / PySide6 模块；LGPL 文本及 Qt 相关许可见同目录
   及 PySide6 自带 LICENSE。

3. pypdf
   许可：BSD
   用途：PDF 合并、删页、加密探测

4. pypdfium2
   许可：见其发行许可（基于 PDFium，许可较为宽松）
   用途：PDF 页面缩略图

5. Pillow
   许可：HPND-style（PIL License）
   用途：将缩略图位图保存为 PNG
