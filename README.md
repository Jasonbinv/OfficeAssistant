# 办公文件助手

Windows 桌面工具，在本机处理办公文件，不上传网络。

当前版本提供三个功能：

- **合并 PDF**：按列表顺序把多份 PDF 整份合成一份新文件，不改源文件。
- **删除页面**：按页码或缩略图勾选删除页面；默认另存，覆盖原文件需确认。
- **重命名**：粘贴「一行一个新名字」的名单，或使用 `{原名}_{序号}` 等规则模板；对照表预览后再改名，支持撤销。

发给同事请解压整个 `OfficeAssistant` 文件夹后双击 `OfficeAssistant.exe`。完整说明见 [使用说明.txt](使用说明.txt)。

## 环境要求

- Windows 10 / 11
- 从源码运行需要 Python 3.12 或更高版本

## 从源码运行

```bash
python -m pip install -e ".[dev]"
python -m office_assistant.app
```

## 测试

```bash
python -m pytest
```

无界面环境可加上 `QT_QPA_PLATFORM=offscreen`。

## 打包

```bash
python -m pip install pyinstaller
pyinstaller packaging/office_assistant.spec --noconfirm --distpath dist --workpath build
```

生成目录：`dist/OfficeAssistant/`，入口为 `OfficeAssistant.exe`。请分发整个文件夹，不要只拷贝 exe。

## 许可证

本仓库代码按仓库内说明使用。界面基于 [PySide6](https://pypi.org/project/PySide6/) / Qt（LGPL），完整文本见 [packaging/licenses](packaging/licenses)。
