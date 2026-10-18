# 桌面项目管理器

长期分支：`projects/project-manager`。

完整源码位于 `source/`；已有 Windows x64 单文件夹运行包位于 `release/windows-x64/`。两者在同一个长期分支维护。

Windows 完整下载后双击 `release/windows-x64/START.cmd`，保留整个 windows-x64 文件夹。原有 CPython、Tcl/Tk、应用和校验文件均原样保留；未新增其他系统运行包。

原始说明和清单在 `source/README.md`、`source/SOURCE-MANIFEST.json`、`docs/original-runtime-README.md` 和运行包的 `RUNTIME-MANIFEST.json`。这些文件中的旧分支名、源提交与现场验收属于历史记录，当前入口以本说明为准。

## 历史与核对

原始提交通过 `snapshot/20261018-before-consolidation/` 下的同名标签保留，详见 `docs/CONSOLIDATION.json`。本次整理保持原有应用文件和已有运行包字节不变，不将历史平台验收记录冒称本次验收。
