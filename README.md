# Windows 实验室截图监控交付包

这个项目用于实验室值守场景：

- 定时截图并推送到飞书或企业微信
- 可选监控相机画面中的激光亮点
- 亮点明显变暗、变小或消失时自动报警

当前交付目标是 Windows 实验室电脑源码部署，不包含 exe、Windows 服务或自动启动配置。

## 项目结构

- [`screenshot_sender`](/Users/wangsiyuan/编程/小项目/自动截屏发送飞书/screenshot_sender)：主程序包
- [`config.example.json`](/Users/wangsiyuan/编程/小项目/自动截屏发送飞书/config.example.json)：配置模板
- [`scripts/windows/install.ps1`](/Users/wangsiyuan/编程/小项目/自动截屏发送飞书/scripts/windows/install.ps1)：安装依赖
- [`scripts/windows/check.bat`](/Users/wangsiyuan/编程/小项目/自动截屏发送飞书/scripts/windows/check.bat)：环境检查
- [`scripts/windows/select_roi.bat`](/Users/wangsiyuan/编程/小项目/自动截屏发送飞书/scripts/windows/select_roi.bat)：框选 ROI
- [`scripts/windows/send_once.bat`](/Users/wangsiyuan/编程/小项目/自动截屏发送飞书/scripts/windows/send_once.bat)：发送一次验收截图
- [`scripts/windows/start.bat`](/Users/wangsiyuan/编程/小项目/自动截屏发送飞书/scripts/windows/start.bat)：正式启动

## 环境要求

- Windows 10/11
- Python 3.10+
- 有桌面会话的登录用户
- 被监控机器允许截图

注意：

- 程序依赖桌面会话，锁屏、无桌面远程环境、某些权限受限场景下可能无法截图
- ROI 框选依赖 OpenCV 窗口能力，第一次部署建议在本机桌面环境直接操作

## 安装步骤

1. 将项目目录复制到实验室电脑
2. 打开 PowerShell，进入项目根目录
3. 执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\install.ps1
```

如果你确定最终使用飞书，也可以显式安装飞书依赖：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\install.ps1 -Provider feishu
```

如果使用企业微信：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\install.ps1 -Provider wecom
```

## 配置文件

1. 复制模板：

```powershell
Copy-Item .\config.example.json .\config.local.json
```

2. 编辑 `config.local.json`

推荐只改这几个字段：

- `PUSH_PROVIDER`：`feishu` 或 `wecom`
- `APP_ID` / `APP_SECRET` / `RECEIVE_ID_TYPE` / `RECEIVE_ID`：飞书使用
- `WECOM_WEBHOOK_URL`：企业微信使用
- `INTERVAL_SECONDS`：定时截图间隔
- `SAVE_DIR`：截图落盘目录，默认 `runtime/screenshots`
- `LOG_LEVEL`：建议先用 `INFO`

ROI 相关字段：

- `ROI`：整屏截图区域，可留 `null`
- `CAMERA_ROI`：相机窗口区域
- `SPOT_SEARCH_ROI`：激光亮点区域

如果暂时不启用激光检测：

- `CAMERA_ROI` 和 `SPOT_SEARCH_ROI` 都保持 `null`

如果启用激光检测：

- `CAMERA_ROI` 和 `SPOT_SEARCH_ROI` 必须同时配置

## 首次部署流程

1. 安装依赖

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\install.ps1
```

2. 复制并填写配置

```powershell
Copy-Item .\config.example.json .\config.local.json
```

3. 运行环境检查

```bat
scripts\windows\check.bat
```

检查会验证：

- 配置是否合法
- 推送渠道依赖是否可用
- 截图能力是否可用
- ROI 是否能在当前截图中正确裁切

4. 如果要启用激光检测，框选 ROI

```bat
scripts\windows\select_roi.bat
```

5. 发送一次验收截图

```bat
scripts\windows\send_once.bat
```

验收标准：

- 群里收到一条文本和一张截图
- 项目目录下生成 `runtime/sender.log`
- 如果配置了 `SAVE_DIR`，截图文件落到对应目录

6. 正式启动

```bat
scripts\windows\start.bat
```

## 日常运维

### 启动

```bat
scripts\windows\start.bat
```

### 停止

- 在运行窗口中按 `Ctrl + C`

### 修改配置

1. 停止程序
2. 修改 `config.local.json`
3. 如果改动了 ROI 或截图区域，重新执行：

```bat
scripts\windows\check.bat
```

### 重新框选 ROI

```bat
scripts\windows\select_roi.bat
```

### 查看日志

默认日志文件：

```text
runtime/sender.log
```

日志会同时输出到终端和文件，启动时会打印：

- 运行模式
- 推送渠道
- 截图间隔
- 激光检测是否启用
- 配置文件路径
- 日志文件路径

## 命令行接口

项目正式入口是：

```bash
python -m screenshot_sender
```

支持的参数：

- `--config <path>`：指定配置文件
- `--check`：检查后退出
- `--once`：发送一次截图后退出
- `--select-roi`：交互式框选 ROI

示例：

```bash
python -m screenshot_sender --config config.local.json --check
python -m screenshot_sender --config config.local.json --once
python -m screenshot_sender --config config.local.json --select-roi
```

## 常见故障排查

### 1. 提示缺少依赖模块

现象：

- `缺少依赖模块: mss`
- `缺少依赖模块: cv2`
- `缺少依赖模块: lark_oapi`

处理：

- 重新运行 `scripts\windows\install.ps1`
- 如果是飞书，确认安装时使用了 `-Provider feishu`，或者 `config.local.json` 中的 `PUSH_PROVIDER` 已正确填写

### 2. `--check` 失败，提示 ROI 配置错误

现象：

- `CAMERA_ROI 和 SPOT_SEARCH_ROI 必须同时配置`
- `SPOT_SEARCH_ROI 超出图像范围`

处理：

- 两个 ROI 要么都为空，要么都有效
- 修改窗口布局后需要重新运行 `select_roi.bat`

### 3. 可以启动，但收不到消息

处理：

- 先运行 `send_once.bat`
- 检查 `PUSH_PROVIDER` 是否与凭据匹配
- 飞书检查 `APP_ID`、`APP_SECRET`、`RECEIVE_ID_TYPE`、`RECEIVE_ID`
- 企业微信检查 `WECOM_WEBHOOK_URL`
- 查看 `runtime/sender.log` 中的发送失败信息

### 4. 截图失败

处理：

- 确认当前用户处于已登录桌面会话
- 确认程序运行时没有锁屏
- 在本机桌面环境重新执行 `check.bat`

## 测试

当前仓库包含单元测试，覆盖：

- 激光亮点检测
- 配置覆盖和默认回落
- 推送渠道配置校验
- CLI 的 `--check` / `--once` 基本行为

运行方式：

```bash
python -m unittest tests/test_laser_spot_monitor.py -v
```
