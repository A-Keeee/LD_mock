# LD_mock

向 `LD_backend` 发送 IMU 文本数据帧（`POST /api/imu/frame`）。数据格式匹配 `LD_innovation/src/cat_predict.py`（传输中的加速度值是模型内部使用的 g 值的 10 倍）。

每个 POST 请求必须包含已注册的 `device_id`，以便后端能够将推理请求路由到特定设备的正确处理管道中。

## 安装与配置

```powershell
cd LD_mock
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 运行

首先启动 `LD_backend`，然后注册设备并发送模拟数据帧：

```powershell
.\.venv\Scripts\Activate.ps1
# 1) 注册设备 (返回用于小程序配对的 pairing_code )
curl -X POST http://127.0.0.1:5000/api/devices/register -H "Content-Type: application/json" -d "{\"device_id\":\"DEV-001\"}"

# 2) 为该设备发送 IMU 数据帧
python send_mock_frames.py --device-id DEV-001 --rows-per-frame 50

# 用于多设备测试的第二台设备
curl -X POST http://127.0.0.1:5000/api/devices/register -H "Content-Type: application/json" -d "{\"device_id\":\"DEV-002\"}"
python send_mock_frames.py --device-id DEV-002 --mode status_random
```

可选环境变量配置：

```powershell
$env:BASE_URL = "http://127.0.0.1:5000"
$env:MOCK_DEVICE_ID = "DEV-001"
$env:MOCK_FRAME_INTERVAL = "2"
```

### 命令行选项 (CLI options)

| 参数 | 默认值 | 备注 |
|------|---------|-------|
| `--device-id` | `DEV-001` | 目标设备（必须通过 `/api/devices/register` 提前注册） |
| `--base-url` | `http://127.0.0.1:5000` | 后端 URL |
| `--interval` | `1.0` | 两次 POST 请求之间的间隔（秒） |
| `--rows-per-frame` | `50` | 每帧的样本行数 |
| `--mode` | `status_cycle` | `status_cycle` （循环状态）或 `status_random` （随机状态） |

### 桌面端 GUI

```powershell
python mock_gui.py
```

GUI 中包含了 **Device ID**（设备 ID） 字段（预设了 `DEV-001` / `DEV-002`）、**注册设备** 和 **刷新列表** 按钮以及设备列表面板（点击行即可选择对应设备），并将 `device_id` 传递到发送循环中。**刷新列表** 会调用 `GET /api/devices/registry` 从 MongoDB 加载所有已注册设备。

## 与小程序进行端到端测试

1. 启动 `LD_backend` 和 MongoDB。
2. 注册设备：使用 `{"device_id":"DEV-001"}` 请求 `POST /api/devices/register` → 记下返回的 `pairing_code`（配对码）。
3. 微信小程序：登录 → **设置** (Settings) 卡片 → 输入配对码 → 绑定设备。
4. 运行模拟设备程序：`python send_mock_frames.py --device-id DEV-001`。
5. 小程序首页：开启 **云端同步** → 状态将仅跟随 `DEV-001` 的数据进行更新。

回放包含行为列信息的 CSV 文件：

```powershell
python send_mock_frames.py --device-id DEV-001 --csv D:\path\to\data.csv --rows-per-frame 50 --limit 500
```
