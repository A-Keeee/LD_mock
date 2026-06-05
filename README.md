# LD_mock

Sends IMU text frames to `LD_backend` (`POST /api/imu/frame`). Wire format matches `LD_innovation/src/cat_predict.py` (acceleration on the wire is 10× the g values used inside the model).

Each POST must include a registered `device_id` so the backend routes inference to the correct per-device pipeline.

## Setup

```powershell
cd LD_mock
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

Start `LD_backend` first, then register a device and send mock frames:

```powershell
.\.venv\Scripts\Activate.ps1
# 1) Register device (returns pairing_code for miniprogram pairing)
curl -X POST http://127.0.0.1:5000/api/devices/register -H "Content-Type: application/json" -d "{\"device_id\":\"DEV-001\"}"

# 2) Send IMU frames for that device
python send_mock_frames.py --device-id DEV-001 --rows-per-frame 50

# second device for multi-device testing
curl -X POST http://127.0.0.1:5000/api/devices/register -H "Content-Type: application/json" -d "{\"device_id\":\"DEV-002\"}"
python send_mock_frames.py --device-id DEV-002 --mode status_random
```

Optional env overrides:

```powershell
$env:BASE_URL = "http://127.0.0.1:5000"
$env:MOCK_DEVICE_ID = "DEV-001"
$env:MOCK_FRAME_INTERVAL = "2"
```

### CLI options

| Flag | Default | Notes |
|------|---------|-------|
| `--device-id` | `DEV-001` | Target device (must be registered via `/api/devices/register`) |
| `--base-url` | `http://127.0.0.1:5000` | Backend URL |
| `--interval` | `1.0` | Seconds between POSTs |
| `--rows-per-frame` | `50` | Samples per frame |
| `--mode` | `status_cycle` | `status_cycle` or `status_random` |

### Desktop GUI

```powershell
python mock_gui.py
```

The GUI adds a **Device ID** field (with presets `DEV-001` / `DEV-002`), **注册设备** and **刷新列表** buttons, a device list panel (click a row to select that device), and passes `device_id` into the sender loop. **刷新列表** calls `GET /api/devices/registry` to load all devices from MongoDB.

## End-to-end with miniprogram

1. Start `LD_backend` and MongoDB.
2. Register device: `POST /api/devices/register` with `{"device_id":"DEV-001"}` → note `pairing_code`.
3. Miniprogram: login → **设置** tab → enter pairing code → bind device.
4. Run mock: `python send_mock_frames.py --device-id DEV-001`.
5. Miniprogram home: enable **云端同步** → status follows `DEV-001` only.

Replay a CSV with behaviour columns:

```powershell
python send_mock_frames.py --device-id DEV-001 --csv D:\path\to\data.csv --rows-per-frame 50 --limit 500
```
