# ProjectManager / 项目管理器

Windows Python/Tk 桌面项目管理器。支持项目概述、主机和性质分组、主次 / 依赖树、最近加入快捷框、时间排序、置顶、删除、项目内 Codex 会话索引、只读查询接口及明确点击触发的 SSH 项目资料交付。

## 文件角色

- `src/project_manager/app.py`：完整桌面应用实现。源自 Acer 正在使用的项目管理器，保留其界面和接口功能。
- `tools/cloud_project_receiver.py`：云端接收辅助脚本，不属于桌面应用核心源码。
- `tools/build_runtime.py`：运行包构建脚本，不属于应用核心源码。
- `docs/`：交付及数据说明。
- Python、标准库、Tcl/Tk 是第三方运行依赖，位于运行时分支，不冒称应用源码。

源码分支：`delivery/project-manager-source-20261017`。
完整 Windows x64 运行时分支：`delivery/project-manager-runtime-20261017`。
仓库：`https://github.com/trlstdin/rororororo`（私有）。两个分支独立交付，不合并到 main。

## 运行和构建

源码可由含 Tk 的 Python 3.11 执行：`python src/project_manager/app.py`。完整运行包自带 Python/Tk，无需另装 Python。其 `START.cmd` 启动桌面应用；监听仅限 `127.0.0.1:18762`。

用已安装的 Windows Python 3.11（必须含 Tcl/Tk）构建：

```powershell
python tools/build_runtime.py --python-home D:\Python311 --output windows-x64
```

运行包中的 `app/project_manager.pyw` 与这里的 `src/project_manager/app.py` 字节相同。构建脚本完整复制 CPython 执行文件、DLL、标准库和 Tcl/Tk，排除 site-packages 与缓存，使用 `python311._pth` 隔离全局 Python 环境。版本、逐文件 SHA-256 和原始安装来源记录在运行包的清单中。

## 业务数据与位置

默认数据位于应用文件所在目录。运行包根目录可提供 `data-location.json`：

```json
{"data_directory":"../../"}
```

相对路径以该配置文件所在目录计算。Acer 上的本地配置指向既有的 `C:\Users\Acer\AppData\LocalLow\ProjectManager`，继续使用原有项目清单、会话索引、偏好和 handoff 状态。源码与运行包上传时不包含真实项目清单、会话备份、连接密钥、remote.json、日志或私密状态。

历史索引的 tar 路径及索引截止时间只描述历史备份。当前会话引用可记录在项目元数据中，明确标为“未归档”，不修改历史备份范围。
