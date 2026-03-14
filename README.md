# 自动截屏发送飞书

一个用于实验室值守的监控脚本。

脚本会定时截取电脑屏幕并发送到飞书，同时支持对相机画面中的激光反光点做异常检测。如果亮点明显变暗、变小或直接消失，会立即报警，减少人工盯屏时间。

## 功能

- 定时截屏并发送到飞书
- 可选的激光亮点异常检测
- 连续多帧确认，降低瞬时噪声误报
- 报警冷却时间，避免短时间重复刷屏
- 支持交互式框选 ROI，不需要手动填写坐标

## 依赖

- Python 3.10+
- `numpy`
- `opencv-python-headless`
- `mss`
- `lark-oapi`

推荐用 `uv` 创建虚拟环境。

## 安装

```bash
uv venv .venv
source .venv/bin/activate
UV_CACHE_DIR=.uv-cache uv pip install --python .venv/bin/python numpy opencv-python-headless mss lark-oapi
```

如果是在 Windows 实验室电脑上，一般改成：

```powershell
uv venv .venv
.venv\Scripts\activate
$env:UV_CACHE_DIR=".uv-cache"
uv pip install --python .venv\Scripts\python.exe numpy opencv-python-headless mss lark-oapi
```

## 配置说明

主配置写在 [`feishu_screenshot_sender.py`](/Users/wangsiyuan/编程/小项目/自动截屏发送飞书/feishu_screenshot_sender.py) 的 `CONFIG` 里。

重点配置项：

- `APP_ID` / `APP_SECRET`：飞书应用凭据
- `RECEIVE_ID_TYPE` / `RECEIVE_ID`：消息接收对象
- `INTERVAL_SECONDS`：定时发送整屏截图的间隔
- `ROI`：整屏截图区域，`None` 表示全屏
- `CAMERA_ROI`：相机窗口区域
- `SPOT_SEARCH_ROI`：激光亮点搜索区域
- `DETECT_INTERVAL_SECONDS`：激光点检测频率
- `INTENSITY_DROP_RATIO_THRESHOLD`：亮度下降阈值
- `AREA_DROP_RATIO_THRESHOLD`：面积下降阈值
- `ALERT_CONSECUTIVE_FRAMES`：连续异常多少帧后报警
- `ALERT_COOLDOWN_SECONDS`：报警冷却时间

`CAMERA_ROI` 和 `SPOT_SEARCH_ROI` 可以不用手填，直接交互式框选。

## 交互式选择 ROI

第一次部署到实验室电脑时，建议先运行：

```bash
python feishu_screenshot_sender.py --select-roi
```

脚本会：

1. 截取当前屏幕
2. 让你框选 `CAMERA_ROI`
3. 在相机窗口里继续框选 `SPOT_SEARCH_ROI`
4. 把结果保存到 `config.local.json`

之后正常运行时会自动读取 `config.local.json`，不需要再改代码。

说明：

- `CAMERA_ROI` 是相对于 `ROI` 截图结果的坐标
- `SPOT_SEARCH_ROI` 是相对于 `CAMERA_ROI` 的坐标
- 如果 `ROI` 保持 `None`，那就是相对于整屏截图

## 正常运行

```bash
python feishu_screenshot_sender.py
```

运行逻辑：

- 按 `INTERVAL_SECONDS` 发送一张整屏截图到飞书
- 按 `DETECT_INTERVAL_SECONDS` 检查一次激光亮点
- 检测到连续异常后，立刻发送报警文本和标注图

如果没有配置 `CAMERA_ROI` 和 `SPOT_SEARCH_ROI`，脚本仍然会保留原来的定时截图功能，只是不启用激光点检测。

## 异常检测逻辑

当前版本的检测思路比较保守，优先追求稳定：

1. 在小范围 `SPOT_SEARCH_ROI` 内寻找最亮区域
2. 建立一段正常状态的基线
3. 监控亮点的面积和总亮度
4. 当亮点连续多帧明显变暗、变小或消失时报警

这比直接比较整张屏幕更适合实验场景，因为左侧曲线、时间戳和软件界面本身会变化。

## 输出文件

运行时会在 `SAVE_DIR` 下生成：

- 定时截图
- 异常报警截图
- `sender.log`

如果用过交互式 ROI 选择，还会在项目根目录生成：

- `config.local.json`

## 测试

当前有一组基于合成图像的单元测试，覆盖：

- 正常亮点检测
- 亮点变暗报警
- 亮点变小报警
- 亮点消失报警
- 单帧异常恢复
- 冷却时间抑制重复报警
- 配置覆盖和 ROI 序列化

运行：

```bash
python -m unittest tests/test_laser_spot_monitor.py -v
```

## 建议的实际部署顺序

1. 在实验室电脑装好 Python 和依赖
2. 先确认飞书发送功能正常
3. 运行 `python feishu_screenshot_sender.py --select-roi`
4. 先在有人值守时观察一段时间，看是否误报
5. 再根据实验画面微调阈值和检测频率

## 已知限制

- 当前 ROI 框选依赖 OpenCV 的窗口能力，建议在有桌面环境的实验室电脑上操作
- 第一版默认假设激光亮点位置基本固定
- 如果实验过程中亮点本来就会大幅漂移或周期性变暗，需要再做第二版策略
