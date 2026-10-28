"""Arena demo. No network calls are made on import."""

import sys

# CPython 3.12 的 platform.system() 会触发同步 WMI 查询；本机已实测该查询挂起。
# 在本应用进程中禁用可选的 _wmi 模块，让 stdlib 使用原有的 Win32 API 回退。
# 不修改 Windows WMI 服务，也不更改 Python 安装目录。
if sys.platform == "win32" and sys.version_info[:2] == (3, 12):
    sys.modules.setdefault("_wmi", None)  # type: ignore[arg-type]  # ImportError sentinel
