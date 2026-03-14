# Windows 实验室截图监控

定时截图并推送到飞书或企业微信，可选监控相机画面中的激光亮点，亮点异常时自动报警。

> 当前交付目标是 Windows 实验室电脑源码部署，不包含 exe、Windows 服务或自动启动配置。

## 快速开始

将项目目录复制到实验室电脑后，双击根目录的 **`安装.bat`**，按提示完成全部配置：

```
══════════════════════════════════════
  自动截屏发送 - 安装向导
══════════════════════════════════════

[1/5] 检查 Python 环境...
  √ Python 3.11.0

[2/5] 配置推送设置
  选择推送渠道：
    1. 企业微信（推荐，配置简单）
    2. 飞书
  请输入 [1/2]：

  企业微信 Webhook URL：...

[3/5] 安装 Python 依赖...
[4/5] 环境检查...
[5/5] 可选操作
  是否发送一次测试截图验收？ [Y/n]：

══════════════════════════════════════════
  安装完成！日常使用请双击根目录的 菜单.bat
══════════════════════════════════════════
```

安装完成后，日常使用双击 **`菜单.bat`**：

```
╔══════════════════════════════════════╗
║      自动截屏发送 - 操作菜单         ║
╠══════════════════════════════════════╣
║  1. 启动（正式运行）                 ║
║  2. 环境检查                         ║
║  3. 重新框选 ROI 区域                ║
║  4. 发送一次测试截图                 ║
║  5. 查看日志                         ║
║  6. 重新安装 / 修改配置              ║
║  0. 退出                             ║
╚══════════════════════════════════════╝
```

## 环境要求

- Windows 10 / 11
- Python 3.10+（`py` 或 `python` 命令可用）
- 有桌面会话的登录用户（锁屏状态下无法截图）

## 项目结构

```
├── 安装.bat                    # 首次使用，双击运行
├── 菜单.bat                    # 日常使用，双击运行
├── config.example.json         # 配置模板（勿直接修改）
├── config.local.json           # 实际配置（由安装向导生成，git 忽略）
├── screenshot_sender/          # 主程序包
└── scripts/windows/
    ├── setup.ps1               # 安装向导（被 安装.bat 调用）
    ├── menu.ps1                # 操作菜单（被 菜单.bat 调用）
    ├── install.ps1             # 依赖安装
    ├── check.bat               # 环境检查
    ├── select_roi.bat          # 框选 ROI
    ├── send_once.bat           # 发送一次测试截图
    └── start.bat               # 正式启动
```

## 配置说明

安装向导会交互式填写并生成 `config.local.json`，通常不需要手动编辑。如需手动调整，参考下表：

### 推送渠道

| 字段 | 说明 |
|------|------|
| `PUSH_PROVIDER` | `wecom` 或 `feishu` |
| `WECOM_WEBHOOK_URL` | 企业微信群机器人 Webhook 地址 |
| `APP_ID` / `APP_SECRET` | 飞书应用凭证 |
| `RECEIVE_ID_TYPE` | 飞书接收者类型：`chat_id`（群）或 `open_id`（个人） |
| `RECEIVE_ID` | 飞书接收者 ID |

### 截图设置

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `INTERVAL_SECONDS` | 定时截图间隔（秒） | `1800`（30 分钟）|
| `TEXT_PREFIX` | 消息文本前缀 | `实验截图` |
| `SAVE_DIR` | 截图本地保存目录 | `runtime/screenshots` |
| `ROI` | 截图区域 `[left, top, width, height]`，`null` 为全屏 | `null` |

### 激光亮点检测（可选）

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `CAMERA_ROI` | 相机窗口区域（相对于 ROI）| `null` |
| `SPOT_SEARCH_ROI` | 激光亮点搜索区域（相对于 CAMERA_ROI）| `null` |
| `DETECT_INTERVAL_SECONDS` | 检测频率（秒）| `5` |
| `INTENSITY_DROP_RATIO_THRESHOLD` | 亮度下降报警阈值 | `0.05` |
| `AREA_DROP_RATIO_THRESHOLD` | 面积下降报警阈值 | `0.05` |
| `ALERT_CONSECUTIVE_FRAMES` | 连续异常帧数才触发报警 | `3` |
| `ALERT_COOLDOWN_SECONDS` | 报警冷却时间（秒）| `300` |

启用激光检测时，`CAMERA_ROI` 和 `SPOT_SEARCH_ROI` 必须同时配置，可通过菜单选项 3 框选生成。

## 日常运维

| 操作 | 方式 |
|------|------|
| 启动 | 双击 `菜单.bat` → 选 1 |
| 停止 | 在运行窗口按 `Ctrl + C` |
| 修改配置 | 双击 `菜单.bat` → 选 6 |
| 重新框选 ROI | 双击 `菜单.bat` → 选 3 |
| 查看日志 | 双击 `菜单.bat` → 选 5（用记事本打开）|

日志默认路径：`runtime/sender.log`

## 命令行接口

高级用法，直接调用主程序：

```bash
python -m screenshot_sender --config config.local.json           # 正式运行
python -m screenshot_sender --config config.local.json --check   # 环境检查
python -m screenshot_sender --config config.local.json --once    # 发送一次截图
python -m screenshot_sender --config config.local.json --select-roi  # 框选 ROI
```

## 常见问题

### 提示缺少依赖模块

重新运行安装：双击 `菜单.bat` → 选 6，或双击 `安装.bat`。

如果使用飞书，确认安装时已选择渠道 2（飞书），飞书需要额外安装 `lark-oapi`。

### `--check` 失败，提示 ROI 配置错误

`CAMERA_ROI` 和 `SPOT_SEARCH_ROI` 要么都为空（不启用激光检测），要么都有效。修改窗口布局后需重新框选：`菜单.bat` → 选 3。

### 可以启动，但收不到消息

1. 通过菜单选 4 发送一次测试截图，观察终端输出
2. 检查 `PUSH_PROVIDER` 与填写的凭据是否匹配
3. 查看 `runtime/sender.log` 中的详细错误

### 截图失败

确认当前用户处于已登录桌面会话（程序运行期间不能锁屏）。

### 框选 ROI 时提示 OpenCV 窗口功能不可用

当前安装的是 `opencv-python-headless`（无 GUI）。重新运行安装即可自动替换为带 GUI 的版本。

## 测试

```bash
python -m unittest tests/test_laser_spot_monitor.py -v
```
