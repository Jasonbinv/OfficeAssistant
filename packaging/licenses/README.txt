办公文件助手 — 第三方许可说明

本绿色包内含 Python 运行时及下列开源组件。Qt / PySide6 以动态库方式链接（.dll），
未静态编入可执行文件。

本目录（_internal/licenses/）随包分发的文件：
  - README.txt   — 本说明
  - LGPL-3.0.txt — GNU LGPL v3 全文（官方文本，https://www.gnu.org/licenses/lgpl-3.0.txt）
  - NOTICE.txt   — PySide6 / Qt 与 LGPL 的简要声明

解压包根目录另有 使用说明.txt（与 OfficeAssistant.exe 同级）。

1. Python
   许可：PSF License
   用途：解释器与标准库

2. PySide6（Qt for Python）
   许可：LGPL v3（Qt 为动态库）
   用途：桌面界面
   说明：随包分发 Qt6*.dll / PySide6 模块；LGPL 全文见本目录 LGPL-3.0.txt。
   PySide6 发行包自带的许可文件位于 _internal 内各 pyside6*.dist-info/licenses/。

3. pypdf
   许可：BSD
   用途：PDF 合并、删页、加密探测
   说明：许可文本未单独收录于本目录；见 pypdf 项目发行说明。

4. pypdfium2
   许可：Apache-2.0、BSD-3-Clause 等（见 _internal/pypdfium2*.dist-info/licenses/）
   用途：PDF 页面缩略图

5. Pillow
   许可：HPND-style（PIL License）
   用途：将缩略图位图保存为 PNG
   说明：见 _internal/pillow*.dist-info/licenses/LICENSE
