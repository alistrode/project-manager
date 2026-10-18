# 交付核验

Acer Windows 主机：LAPTOP-MCMQHDN4，用户 Acer。
源码导出：C:\Users\Acer\AppData\LocalLow\ProjectManager\source
运行包：C:\Users\Acer\AppData\LocalLow\ProjectManager\runtime\windows-x64
现有数据：C:\Users\Acer\AppData\LocalLow\ProjectManager

本地导出通过清单逐文件核对，不宣称导出目录就是 Git checkout。云端另保留两个对应的 Git checkout，实际主机名和提交号写入交付回执及项目条目。

便携运行时实测包括 Python 隔离路径、标准库、Tk 根窗口、项目管理器界面载入和本地只读 API；未执行操作系统重启测试。SSH 项目资料发送是可选功能，需要用户既有中继配置；连接凭据不会打入上传包。
