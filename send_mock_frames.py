#!/usr/bin/env python3
"""
Simulated hardware: POST IMU frames to LD_backend /api/imu/frame.
Wire format matches LD_innovation cat_predict.parse_frame (accel ×10 on wire).
"""

import argparse
import os
import random
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Literal, Optional, Tuple

import pandas as pd
import requests

SenderMode = Literal["status_cycle", "status_random"]

# Seconds between POSTs; override with env MOCK_FRAME_INTERVAL or --interval.
_DEFAULT_POST_INTERVAL = float(os.environ.get("MOCK_FRAME_INTERVAL", "1.0"))

# 与 LD_innovation 训练管线一致（见 src/cat_realtime_classifier.py、src/build_cat_dog_acc_dataset.py）
_BEHAVIOUR_CLASSES = ("Rest", "Sleep", "Feed", "Walk", "Groom", "Shake")
_SCRIPT_DIR = Path(__file__).resolve().parent
_DEFAULT_CAT_CSV = _SCRIPT_DIR / "cat_100hz.csv"


def build_frame(
    header_ts: float,
    seq: int,
    rows: List[Tuple[float, float, float, float, float, float, float]],
) -> str:
    """
    Each row: offset_t, raw_ax, raw_ay, raw_az, gx, gy, gz
    (raw_a* are wire values; server divides by 10.)
    """
    lines = [f"FRAME,TS:{header_ts:.6f},SEQ:{seq},LEN:{len(rows)}"]
    for offset_t, rax, ray, raz, gx, gy, gz in rows:
        lines.append(f"{offset_t},{rax},{ray},{raz},{gx},{gy},{gz}")
    lines.append("END")
    return "\n".join(lines) + "\n"


def load_rows_by_behaviour(
    path: str, limit: Optional[int],
) -> Dict[str, List[Tuple[float, float, float, float, float, float, float]]]:
    df = pd.read_csv(path)
    if not all(c in df.columns for c in ("AccX", "AccY", "AccZ", "Behaviour")):
        raise SystemExit("CSV must include AccX,AccY,AccZ,Behaviour columns")
    if all(c in df.columns for c in ("AccX", "AccY", "AccZ")):
        acc = ["AccX", "AccY", "AccZ"]
        gyr = ["GyrX", "GyrY", "GyrZ"] if all(c in df.columns for c in ("GyrX", "GyrY", "GyrZ")) else None
        use_csv_time = "Time" in df.columns
    n = len(df) if limit is None else min(len(df), limit)
    out: Dict[str, List[Tuple[float, float, float, float, float, float, float]]] = {}
    for idx in range(n):
        row = df.iloc[idx]
        beh = str(row["Behaviour"]).strip()
        out.setdefault(beh, [])
        rax = float(row[acc[0]]) * 10.0
        ray = float(row[acc[1]]) * 10.0
        raz = float(row[acc[2]]) * 10.0
        if gyr:
            gx, gy, gz = float(row[gyr[0]]), float(row[gyr[1]]), float(row[gyr[2]])
        else:
            gx = gy = gz = 0.0
        t_abs = float(row["Time"]) if use_csv_time else float(idx) * 0.01
        out[beh].append((t_abs, rax, ray, raz, gx, gy, gz))
    out = {k: v for k, v in out.items() if v}
    if not out:
        raise SystemExit("CSV has no valid rows grouped by Behaviour")
    return out


def take_rows_for_behaviour(
    rows: List[Tuple[float, float, float, float, float, float, float]],
    start_idx: int,
    chunk: int,
) -> Tuple[List[Tuple[float, float, float, float, float, float, float]], int]:
    if not rows:
        return [], start_idx
    picked: List[Tuple[float, float, float, float, float, float, float]] = []
    t0 = rows[start_idx][0]
    idx = start_idx
    for _ in range(chunk):
        t_abs, rax, ray, raz, gx, gy, gz = rows[idx]
        picked.append((t_abs - t0, rax, ray, raz, gx, gy, gz))
        idx = (idx + 1) % len(rows)
    return picked, idx


def run_sender_loop(
    *,
    base_url: str,
    interval: float,
    rows_per_frame: int,
    mode: SenderMode,
    device_id: str,
    csv_path: Optional[str] = None,
    csv_limit: Optional[int] = None,
    seed: Optional[int] = None,
    stop_event: Optional[threading.Event] = None,
    log_fn: Callable[[str], None] = print,
) -> None:
    """
    POST IMU frames until ``stop_event`` is set (GUI).
    """
    url = base_url.rstrip("/") + "/api/imu/frame"
    seq = 0
    rng = random.Random(seed)

    def stopped() -> bool:
        return stop_event is not None and stop_event.is_set()

    if not device_id:
        raise ValueError("device_id is required")
    if not csv_path:
        raise ValueError("csv_path is required")
    rows_by_beh = load_rows_by_behaviour(csv_path, csv_limit)
    ordered = [b for b in _BEHAVIOUR_CLASSES if b in rows_by_beh]
    behaviour_order = ordered if ordered else sorted(rows_by_beh.keys())
    cursor_by_beh = {beh: 0 for beh in behaviour_order}

    while stop_event is None or not stop_event.is_set():
        if mode == "status_random":
            beh = rng.choice(behaviour_order)
        else:
            beh = behaviour_order[seq % len(behaviour_order)]
        rows, next_idx = take_rows_for_behaviour(rows_by_beh[beh], cursor_by_beh[beh], rows_per_frame)
        cursor_by_beh[beh] = next_idx

        payload = build_frame(time.time(), seq, rows)
        seq += 1
        try:
            r = requests.post(
                url,
                json={"payload": payload, "device_id": device_id},
                timeout=30,
            )
            log_fn(f"[{device_id}] seq={seq - 1} {beh} -> {r.status_code} {r.json()}")
        except Exception as e:
            log_fn(f"POST error: {e}")
        if stopped():
            break
        end = time.time() + interval
        while time.time() < end:
            if stopped():
                break
            time.sleep(min(0.05, max(0.0, end - time.time())))
    log_fn("Sender stopped.")


def main():
    p = argparse.ArgumentParser(description="POST mock IMU frames to LD_backend")
    p.add_argument("--base-url", default=os.environ.get("BASE_URL", "http://127.0.0.1:5000"))
    p.add_argument(
        "--interval",
        type=float,
        default=_DEFAULT_POST_INTERVAL,
        help="seconds between POSTs (default 1.0 = 1 POST/s; use MOCK_FRAME_INTERVAL env to override)",
    )
    p.add_argument("--rows-per-frame", type=int, default=50)
    p.add_argument(
        "--csv",
        type=str,
        default=str(_DEFAULT_CAT_CSV) if _DEFAULT_CAT_CSV.is_file() else None,
        help="CSV path (must include AccX/AccY/AccZ/Behaviour; default: cat_100hz.csv if present)",
    )
    p.add_argument(
        "--device-id",
        type=str,
        default=os.environ.get("MOCK_DEVICE_ID", "DEV-001"),
        help="target device_id for POST /api/imu/frame (default DEV-001 or MOCK_DEVICE_ID env)",
    )
    p.add_argument("--limit", type=int, default=None)
    p.add_argument(
        "--mode",
        type=str,
        default="status_cycle",
        choices=["status_cycle", "status_random"],
        help="status_cycle: loop Rest..Shake; status_random: random status each frame",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="optional RNG seed for status_random reproducibility",
    )
    args = p.parse_args()
    mode: SenderMode = "status_random" if args.mode == "status_random" else "status_cycle"

    run_sender_loop(
        base_url=args.base_url,
        interval=args.interval,
        rows_per_frame=args.rows_per_frame,
        mode=mode,
        device_id=args.device_id,
        csv_path=args.csv,
        csv_limit=args.limit,
        seed=args.seed,
        stop_event=None,
        log_fn=print,
    )


if __name__ == "__main__":
    main()
