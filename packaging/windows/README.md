# Windows 打包

Windows 版本采用 **PyInstaller onedir + Inno Setup 安装程序**：

- `build/windows-dist/E-HRM/` 是构建过程中的实际运行目录；
- `dist/E-HRM-Setup-<版本>/` 是该版本的最终交付目录；
- 最终目录中同时包含免安装 ZIP 和安装程序 EXE。

这不是 PyInstaller 的 onefile 模式。安装程序虽然是单个 EXE，但安装后会保留
Qt、QML、Playwright 和 Chromium 的运行目录，启动速度和稳定性更适合本项目。

## 构建机准备

必须在 64 位 Windows 上构建，不能在 macOS 上直接生成 Windows EXE。

```powershell
conda env create -f environment.backend.yml
conda env update -n ehrm -f environment.frontend.yml
conda env update -n ehrm -f environment.windows-build.yml
conda activate ehrm
```

如需生成安装程序，请安装 Inno Setup 6。没有安装时，脚本仍会生成可运行目录
和 ZIP 便携版。

## 一键构建

在项目根目录打开 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -Version 0.2.0
```

最终目录结构：

```text
dist\
└─ E-HRM-Setup-0.2.0\
   ├─ E-HRM-Setup-0.2.0.exe
   └─ E-HRM-0.2.0-windows-x64.zip
```

`-Version` 支持 `0.2.0` 或 `0.2.0.0` 格式。不传时继续读取项目内置版本号。

常用参数：

```powershell
# 暂时跳过测试
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -Version 0.2.0 -SkipTests

# 只生成目录版和 ZIP，不调用 Inno Setup
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -Version 0.2.0 -SkipInstaller

# 调试构建：启动软件时保留控制台窗口
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -Version 0.2.0 -Console
```

构建脚本会自动完成：

1. 校验 Python 和构建依赖；
2. 执行测试；
3. 下载并内置当前 Playwright 版本对应的 Chromium；
4. 生成 Windows 图标和版本信息；
5. 生成 onedir 冻结包；
6. 校验配置、QML、Playwright Driver 和 Chromium 是否完整；
7. 生成 ZIP，并在可用时生成安装程序 EXE。

## 发布前验证

请在一台没有安装 Python、Conda 和 Playwright 的 Windows 电脑上验证：

1. 软件可以启动且不出现控制台窗口；
2. 智慧人社浏览器能够打开并完成人工安全验证；
3. 权益单可以下载到指定目录；
4. ERP 凭据能够写入 Windows 凭据管理器；
5. ERP 可以静默登录并上传附件；
6. 正常关闭软件时没有崩溃提示。

个人账号、密码、浏览器资料、日志和下载结果不会进入安装包。
