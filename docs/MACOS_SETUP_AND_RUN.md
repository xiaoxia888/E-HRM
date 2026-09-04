# macOS 环境初始化与运行

本文用于在一台新的 macOS 开发机上，从 Git 拉取 E-HRM 项目、创建 Conda
环境并启动桌面软件。

## 1. 环境要求

- macOS 13 或更高版本；
- Intel 或 Apple Silicon 均可；
- Git；
- Miniconda 或 Anaconda；
- 可访问 GitHub、Conda 和 Playwright 浏览器下载地址；
- 至少预留 3 GB 磁盘空间。

不需要单独安装 Node.js、Chrome 或 Chromium。

## 2. 安装基础工具

先确认 Git：

```bash
git --version
```

再确认 Conda：

```bash
conda --version
```

如果终端找不到 Conda，完成 Miniconda 安装后执行：

```bash
conda init zsh
exec zsh
```

## 3. 拉取项目

选择一个工作目录：

```bash
mkdir -p ~/workspace/NJNCC
cd ~/workspace/NJNCC
git clone https://github.com/xiaoxia888/E-HRM.git
cd E-HRM
git switch main
git pull --ff-only origin main
```

确认当前代码状态：

```bash
git status
git log -1 --oneline
```

## 4. 创建 Conda 环境

开发机推荐直接使用组合环境文件，它会安装后端、PySide6 前端和测试依赖：

```bash
conda env create -f environment.yml
conda activate ehrm
```

如果 `ehrm` 环境已经存在，使用：

```bash
conda env update -n ehrm -f environment.yml
conda activate ehrm
```

检查 Python 和关键依赖：

```bash
python --version
python -c "import PySide6, playwright, openpyxl; print('环境检查通过')"
```

Python 应为 `3.11.x`。

## 5. 安装 Playwright Chromium

```bash
python -m playwright install chromium
```

检查浏览器是否安装：

```bash
python -m playwright install --list
```

项目只使用 Chromium，不需要安装 Firefox 和 WebKit。

## 6. 运行测试

首次初始化或更新代码后建议执行：

```bash
python -m pytest -q
```

测试全部通过后再启动桌面软件。

## 7. 启动桌面软件

确保当前位于项目根目录并已激活 `ehrm` 环境：

```bash
conda activate ehrm
cd ~/workspace/NJNCC/E-HRM
python scripts/run_gui.py
```

也可以使用安装到环境中的命令：

```bash
ehrm-gui
```

## 8. 首次使用

### ERP 设置

1. 打开“系统设置”；
2. 进入“账户与连接”；
3. 输入 ERP 用户名和密码；
4. 点击“保存账号”；
5. 点击“测试连接”。

ERP 账号密码保存在应用目录的 `runtime/data/auth.sqlite3`，不会写入项目配置文件。

### NocoBase 设置

1. 打开“系统设置 → 账户与连接 → NocoBase”；
2. 输入账号和密码并保存；
3. 点击“测试连接”，确认登录与 Token 正常。

NocoBase 的账号、密码、JWT 及过期时间与其他系统统一保存在
`runtime/data/auth.sqlite3`。

### 权益单获取

1. 进入“权益单获取”；
2. 下载 Excel 模板；
3. 按模板填写人员和任务编号；
4. 导入 Excel；
5. 选择单独下载或相同条件合并；
6. 点击“获取权益单”；
7. 程序按系统配置完成智慧人社登录和安全验证；
8. 登录完成后程序自动继续查询和下载。

NocoBase 权益申请可在“权益申请”页面分页查询、查看详情并发起打印。

## 9. 用户数据位置

运行数据统一位于程序层级的 `runtime` 目录。源码运行时为项目根目录下：

```text
E-HRM/runtime/
```

其中包括：

- `logs/`：运行日志；
- `data/browser-profile/`：智慧人社浏览器资料；
- `data/erp-browser-profile/`：ERP 浏览器资料；
- `data/preferences.json`：非敏感用户设置。
- `data/auth.sqlite3`：ERP、智慧人社和 NocoBase 的账号及登录会话。

默认下载目录为：

```text
~/Downloads
```

## 10. 更新项目

```bash
cd ~/workspace/NJNCC/E-HRM
git status
git pull --ff-only origin main
conda env update -n ehrm -f environment.yml
conda activate ehrm
python -m playwright install chromium
python -m pytest -q
python scripts/run_gui.py
```

如果 `git pull` 提示本地存在未提交修改，先执行 `git status` 确认内容，不要直接
使用会丢失本地修改的强制覆盖命令。

## 11. 常见问题

### `conda: command not found`

```bash
conda init zsh
exec zsh
```

### Playwright 提示找不到浏览器

```bash
conda activate ehrm
python -m playwright install chromium
```

### 找不到 `ehrm` 模块

确认当前环境和项目安装状态：

```bash
conda activate ehrm
python -m pip install -e .
```

### 终端出现输入法日志

类似下面的 macOS 日志不是程序异常：

```text
IMKCFRunLoopWakeUpReliable
TSM AdjustCapsLockLEDForKeyTransitionHandling
```

如果软件实际崩溃，请在系统设置中打开日志目录并提供最新的 `ehrm.log`。
