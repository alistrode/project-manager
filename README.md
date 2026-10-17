# ProjectManager：完整 Windows x64 运行包

双击 `windows-x64/START.cmd`。包内包含应用、CPython 3.11.9、全部标准库、原生 DLL、Tcl/Tk 8.6.12 和许可，无须另装 Python。Python 使用 `python311._pth` 隔离全局安装与第三方 site-packages。

- 运行分支：`delivery/project-manager-runtime-20261017`
- 对应源码：[`delivery/project-manager-source-20261017`](https://github.com/trlstdin/rororororo/tree/delivery/project-manager-source-20261017)
- 源码提交：`790898b47e88932097dbdd77a155a8066b3d7f62`
- `windows-x64/app/project_manager.pyw` 与源码分支的 `src/project_manager/app.py` 字节一致。
- `windows-x64/python/` 为第三方运行依赖，不是应用源码。
- `windows-x64/RUNTIME-MANIFEST.json` 是交付文件的逐项 SHA-256 清单。
- `windows-x64/VALIDATION.json` 记录 Acer Windows 原生隔离运行结果。

Acer 上的本地运行目录为 `C:\Users\Acer\AppData\LocalLow\ProjectManager\runtime\windows-x64`，主机 `LAPTOP-MCMQHDN4`。本地 `data-location.json` 指向原有 ProjectManager 数据目录。仓库不上传真实项目清单、会话备份、日志、中继凭据或本地数据目录配置；首次独立解压时应用从空清单开始。

需要使用另一数据目录时，在 `windows-x64/data-location.json` 写入 `{"data_directory":"完整路径或相对配置文件的路径"}`。应用只在本机 `127.0.0.1:18762` 提供接口。已有窗口监听此端口时，请使用已有窗口。

SSH 项目资料发送是可选功能，需要原有连接配置；连接密钥不在此运行包内。内置核心功能可离线使用。没有执行系统重启或开机启动验收。

CPython 许可：`windows-x64/python/LICENSE.txt`；Tcl/Tk 的许可保留于对应 tcl 子目录。运行包构建方法在源码分支的 `tools/build_runtime.py`，构建辅助脚本与应用源码分别存放。
