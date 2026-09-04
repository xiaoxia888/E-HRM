# E-HRM GitHub 版本发布与安装包维护指南

本文档用于规范 E-HRM Windows 安装程序的版本管理、构建、测试和 GitHub
Release 发布流程。

## 1. 维护方式

E-HRM 采用以下方式分别管理源码和可执行程序：

- 源码通过 Git 提交、分支和标签管理；
- Windows 安装程序通过 GitHub Releases 管理；
- 不要将 EXE、ZIP 和 PyInstaller 构建目录直接提交到 Git 仓库；
- 每个正式发布的安装包必须对应一个不可混用的 Git 标签。

推荐的 Release 结构如下：

```text
Releases
├─ v0.2.1  Latest
│  ├─ E-HRM-Setup-0.2.1.exe
│  └─ E-HRM-0.2.1-windows-x64.zip
└─ v0.2.0
   ├─ E-HRM-Setup-0.2.0.exe
   └─ E-HRM-0.2.0-windows-x64.zip
```

GitHub Release 基于 Git 标签创建，可以附带安装程序、便携版压缩包和版本说明。
GitHub 当前允许每个 Release 最多包含 1000 个附件，每个附件必须小于 2 GiB。

官方文档：

- [About releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)
- [Managing releases](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)

## 2. 版本号规则

版本号统一使用以下格式：

```text
主版本.次版本.修订版本
```

例如：

| 版本 | 使用场景 |
| --- | --- |
| `0.2.0` | 增加阶段性新功能或完成一个新模块 |
| `0.2.1` | 修复问题、小幅优化，不改变主要功能 |
| `0.3.0` | 增加新的完整业务模块 |
| `1.0.0` | 功能稳定并进入正式使用阶段 |

Git 标签统一在版本号前增加 `v`：

```text
安装程序版本：0.2.0
Git 标签：v0.2.0
```

已经正式发布的版本不应覆盖或重新上传。若 `0.2.0` 发布后发现问题，应修复并
发布 `0.2.1`。

## 3. 发布前检查

发布前确认以下事项：

1. 计划发布的代码已经完成并通过测试；
2. ERP 查询与上传、智慧人社登录与下载、NocoBase 查询与打印已经在 Windows 上验证；
3. 配置文件中不存在真实账号、密码、Token 或浏览器登录状态；
4. `preferences.json`、日志、下载文件和浏览器用户目录没有进入安装包；
5. 本次版本号尚未被发布；
6. 发布说明已经准备完成。

## 4. 提交并推送源码

在发布安装程序前，先将本次代码提交并推送到 GitHub：

```powershell
git status
git add .
git commit -m "release: v0.2.0"
git push origin main
```

提交前应检查变更内容，避免把本地账号、密码、日志或测试数据一并提交。

## 5. 在 Windows 上构建安装程序

进入项目目录并激活 Conda 环境：

```powershell
cd D:\workspace\NJNCC\E-HRM
conda activate ehrm
```

执行带版本号的构建命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\build_windows.ps1 `
  -Version 0.2.0
```

构建成功后生成：

```text
dist\
└─ E-HRM-Setup-0.2.0\
   ├─ E-HRM-Setup-0.2.0.exe
   └─ E-HRM-0.2.0-windows-x64.zip
```

其中：

- `E-HRM-Setup-0.2.0.exe` 是提供给普通用户使用的安装程序；
- `E-HRM-0.2.0-windows-x64.zip` 是免安装便携版本，主要用于测试或故障排查。

构建参数会同步设置以下版本信息：

- EXE 文件版本；
- Inno Setup 安装程序版本；
- 软件“关于”页面显示的版本；
- 最终输出目录和文件名。

## 6. 安装验证

不要在构建完成后立即发布。应先在 Windows 测试电脑上进行以下验证：

1. 双击安装程序可以正常选择或使用默认安装目录；
2. 已安装旧版本时，新版本可以识别并覆盖升级；
3. 软件可以正常启动和关闭；
4. 用户配置和系统凭据不会因升级丢失；
5. ERP 登录、查询和附件上传正常；
6. 智慧人社登录、安全验证和权益单下载正常；
7. NocoBase 登录、分页查询、详情查看和分组打印正常；
8. 低分辨率和 Windows 缩放环境下页面能够正常操作；
9. 卸载程序可以正常运行。

若验证失败，不要使用已经准备的版本号发布，应修复后重新构建和测试。

## 7. 创建并推送 Git 标签

安装验证通过后，为本次源码提交创建标签：

```powershell
git tag -a v0.2.0 -m "E-HRM v0.2.0"
git push origin v0.2.0
```

检查标签：

```powershell
git show v0.2.0
```

标签用于确保 GitHub Release 中的安装程序能够追溯到准确的源码版本。

## 8. 通过 GitHub 网页发布

1. 打开 GitHub 仓库 `xiaoxia888/E-HRM`；
2. 进入 `Releases`；
3. 点击 `Draft a new release`；
4. 选择已经推送的标签 `v0.2.0`；
5. 标题填写 `E-HRM v0.2.0`；
6. 上传以下文件：
   - `E-HRM-Setup-0.2.0.exe`
   - `E-HRM-0.2.0-windows-x64.zip`
7. 填写版本更新说明；
8. 确认附件和标签无误后点击 `Publish release`。

建议先保存为 Draft，检查完成后再正式发布。

## 9. 通过 GitHub CLI 发布

首次使用 GitHub CLI 时登录：

```powershell
gh auth login
```

创建 Release 并上传两个文件：

```powershell
gh release create v0.2.0 `
  ".\dist\E-HRM-Setup-0.2.0\E-HRM-Setup-0.2.0.exe" `
  ".\dist\E-HRM-Setup-0.2.0\E-HRM-0.2.0-windows-x64.zip" `
  --title "E-HRM v0.2.0" `
  --generate-notes `
  --verify-tag
```

其中：

- `--generate-notes` 根据两个版本之间的提交自动生成发布说明；
- `--verify-tag` 确保远端标签已经存在，防止错误关联到其他提交。

GitHub CLI 官方文档：

- [gh release create](https://cli.github.com/manual/gh_release_create)
- [gh release upload](https://cli.github.com/manual/gh_release_upload)

## 10. Release 更新说明模板

```markdown
## E-HRM v0.2.0

### 新增

- 支持从 ERP 获取人力资源事务申请
- 支持通过大模型解析人员及查询年月
- 支持人员库匹配身份证、单位和部门
- 支持自动下载单位权益单
- 支持自动上传权益单至 ERP

### 优化

- 优化 Windows 低分辨率页面适配
- 优化智慧人社页面加载等待
- 优化 Windows 安装和版本升级流程

### 修复

- 修复批量下载时页面加载过快的问题
- 修复 ERP 登录状态校验问题

### 安装说明

- 新用户直接运行 `E-HRM-Setup-0.2.0.exe`
- 已安装旧版本的用户直接运行新安装程序完成覆盖升级
```

## 11. 私有仓库注意事项

如果 GitHub 仓库是私有仓库：

- 只有获得仓库读取权限的 GitHub 用户才能查看和下载 Release；
- 没有 GitHub 权限的人事用户无法直接使用私有 Release 下载链接；
- 可以由管理员从 GitHub 下载后，通过公司网盘、共享目录或内部软件平台分发。

如果仓库调整为公开仓库，源码和 Release 通常都会公开。不要为了公开下载安装包而
意外公开包含业务逻辑的私有项目。

## 12. 安全要求

发布前必须确认安装包和源码中不包含：

- ERP 用户名和密码；
- 江苏智慧人社单位编号、手机号码和密码；
- NocoBase 账号和密码；
- Token、Cookie 和浏览器登录状态；
- `preferences.json`；
- 本地日志、截图和实际业务 Excel；
- 本地下载的权益单或其他包含个人信息的文件。

程序运行时的账号、密码和会话保存在 `runtime/data/auth.sqlite3`。该运行数据库不得
提交到 GitHub、打入安装包或随 Release 分发。

## 13. 后续自动化方向

当前阶段推荐使用“Windows 本地打包、人工验证、手动发布 Release”的方式。

发布流程稳定后，可以增加 GitHub Actions：

1. 推送 `v0.2.1` 格式的标签；
2. GitHub 启动 Windows 构建环境；
3. 自动安装 Python、项目依赖、Playwright Chromium 和 Inno Setup；
4. 自动执行测试和 Windows 打包脚本；
5. 自动创建 GitHub Release；
6. 自动上传安装程序和便携版 ZIP。

自动发布仍应保留版本号校验、测试和敏感信息检查，不能仅以“构建成功”作为正式
发布标准。
