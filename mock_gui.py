#!/usr/bin/env python3
"""
LD_mock 桌面 GUI：切换发送模式、开始/停止 POST、查看日志。
依赖同目录 send_mock_frames.run_sender_loop；请在 LD_mock 目录下运行:
  python mock_gui.py
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Optional

import requests

from send_mock_frames import SenderMode, run_sender_loop

_GUI_DIR = Path(__file__).resolve().parent
_DEFAULT_CAT_CSV = _GUI_DIR / "cat_100hz.csv"


class MockSenderApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("LD_mock — IMU 模拟发送")
        self.geometry("720x640")
        self.minsize(640, 480)

        self._stop = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._log_q: queue.Queue[str] = queue.Queue()

        self._build()
        self.after(120, self._drain_log_queue)
        self.after(300, self._fetch_device_list)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)

        row0 = ttk.Frame(frm)
        row0.pack(fill=tk.X, **pad)
        ttk.Label(row0, text="Base URL").pack(side=tk.LEFT)
        self.var_url = tk.StringVar(value="http://127.0.0.1:5000")
        ttk.Entry(row0, textvariable=self.var_url, width=48).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))

        row0b = ttk.Frame(frm)
        row0b.pack(fill=tk.X, **pad)
        ttk.Label(row0b, text="Device ID").pack(side=tk.LEFT)
        self.var_device = tk.StringVar(value="DEV-001")
        self.device_combo = ttk.Combobox(
            row0b,
            textvariable=self.var_device,
            values=("DEV-001", "DEV-002"),
            width=18,
        )
        self.device_combo.pack(side=tk.LEFT, padx=(6, 8))
        ttk.Button(row0b, text="注册设备", command=self._register_device).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(row0b, text="刷新列表", command=self._fetch_device_list).pack(side=tk.LEFT)

        row0c = ttk.LabelFrame(frm, text="数据库设备", padding=6)
        row0c.pack(fill=tk.BOTH, **pad)
        self.device_list = tk.Listbox(row0c, height=4, font=("Consolas", 9))
        self.device_list.pack(fill=tk.BOTH, expand=True)
        self.device_list.bind("<<ListboxSelect>>", self._on_device_list_select)

        row1 = ttk.Frame(frm)
        row1.pack(fill=tk.X, **pad)
        ttk.Label(row1, text="间隔 (s)").pack(side=tk.LEFT)
        self.var_interval = tk.StringVar(value="1.0")
        ttk.Entry(row1, textvariable=self.var_interval, width=8).pack(side=tk.LEFT, padx=(4, 16))
        ttk.Label(row1, text="每帧行数").pack(side=tk.LEFT)
        self.var_rows = tk.StringVar(value="50")
        ttk.Entry(row1, textvariable=self.var_rows, width=6).pack(side=tk.LEFT, padx=(4, 16))
        ttk.Label(row1, text="随机种子 (可空)").pack(side=tk.LEFT)
        self.var_seed = tk.StringVar(value="")
        ttk.Entry(row1, textvariable=self.var_seed, width=10).pack(side=tk.LEFT, padx=(4, 0))

        row2 = ttk.LabelFrame(frm, text="发送模式", padding=6)
        row2.pack(fill=tk.X, **pad)
        _csv_default = _DEFAULT_CAT_CSV.is_file()
        self.var_mode = tk.StringVar(value="status_cycle")
        modes = [
            ("status_cycle", "状态循环发送（按 Rest..Shake）"),
            ("status_random", "状态随机发送"),
        ]
        for val, label in modes:
            ttk.Radiobutton(row2, text=label, value=val, variable=self.var_mode, command=self._on_mode_change).pack(
                anchor=tk.W
            )

        row4 = ttk.Frame(frm)
        row4.pack(fill=tk.X, **pad)
        ttk.Label(row4, text="CSV 路径").pack(side=tk.LEFT)
        self.var_csv = tk.StringVar(value=str(_DEFAULT_CAT_CSV) if _csv_default else "")
        self.entry_csv = ttk.Entry(row4, textvariable=self.var_csv, width=52)
        self.entry_csv.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 4))
        ttk.Button(row4, text="浏览…", command=self._browse_csv).pack(side=tk.LEFT)
        ttk.Label(row4, text="行数上限").pack(side=tk.LEFT, padx=(12, 0))
        self.var_limit = tk.StringVar(value="")
        ttk.Entry(row4, textvariable=self.var_limit, width=10).pack(side=tk.LEFT, padx=(4, 0))

        row5 = ttk.Frame(frm)
        row5.pack(fill=tk.X, pady=10)
        self.btn_start = ttk.Button(row5, text="开始发送", command=self._start)
        self.btn_start.pack(side=tk.LEFT)
        self.btn_stop = ttk.Button(row5, text="停止", command=self._stop_send, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(row5, text="清空日志", command=self._clear_log).pack(side=tk.LEFT, padx=(16, 0))

        ttk.Label(frm, text="日志").pack(anchor=tk.W, **pad)
        self.log = scrolledtext.ScrolledText(frm, height=18, wrap=tk.WORD, font=("Consolas", 10))
        self.log.pack(fill=tk.BOTH, expand=True, **pad)

        self._on_mode_change()

    def _on_mode_change(self) -> None:
        self.entry_csv.configure(state=tk.NORMAL)

    def _format_registry_line(self, item: dict) -> str:
        device_id = item.get("device_id") or "?"
        if item.get("bound"):
            phone = item.get("phone") or "-"
            status = f"已绑定 {phone}"
        else:
            code = item.get("pairing_code") or "-"
            status = f"未绑定 配对码:{code}"
        last_seen = item.get("last_seen_at") or "从未上线"
        return f"{device_id} | {status} | 最后在线: {last_seen}"

    def _fetch_device_list(self) -> None:
        url = self.var_url.get().strip().rstrip("/") + "/api/devices/registry"
        try:
            r = requests.get(url, timeout=15)
            body = r.json()
            if r.status_code >= 400 or not body.get("success"):
                self._append_log(f"获取设备列表失败: {body.get('message') or body}")
                messagebox.showerror("获取失败", str(body.get("message") or body))
                return
            devices = (body.get("data") or {}).get("devices") or []
            device_ids = [d.get("device_id") for d in devices if d.get("device_id")]

            self.device_list.delete(0, tk.END)
            for item in devices:
                self.device_list.insert(tk.END, self._format_registry_line(item))

            if device_ids:
                self.device_combo["values"] = tuple(device_ids)

            self._append_log(f"--- 设备列表共 {len(devices)} 条 ---")
            for item in devices:
                self._append_log(self._format_registry_line(item))
            if not devices:
                self._append_log("（数据库中暂无设备）")
        except Exception as e:
            self._append_log(f"获取设备列表异常: {e}")
            messagebox.showerror("获取失败", str(e))

    def _on_device_list_select(self, _event: object) -> None:
        selection = self.device_list.curselection()
        if not selection:
            return
        line = self.device_list.get(selection[0])
        device_id = line.split(" | ", 1)[0].strip()
        if device_id:
            self.var_device.set(device_id)

    def _browse_csv(self) -> None:
        path = filedialog.askopenfilename(title="选择 CSV", filetypes=[("CSV", "*.csv"), ("All", "*.*")])
        if path:
            self.var_csv.set(path)
            self._on_mode_change()

    def _clear_log(self) -> None:
        self.log.delete("1.0", tk.END)

    def _append_log(self, line: str) -> None:
        self.log.insert(tk.END, line + "\n")
        self.log.see(tk.END)

    def _drain_log_queue(self) -> None:
        try:
            while True:
                msg = self._log_q.get_nowait()
                if msg == "__THREAD_DONE__":
                    self._on_worker_finished()
                else:
                    self._append_log(msg)
        except queue.Empty:
            pass
        self.after(120, self._drain_log_queue)

    def _on_worker_finished(self) -> None:
        self.btn_start.configure(state=tk.NORMAL)
        self.btn_stop.configure(state=tk.DISABLED)
        self._worker = None

    def _parse_optional_int(self, s: str) -> Optional[int]:
        s = s.strip()
        if not s:
            return None
        return int(s)

    def _register_device(self) -> None:
        device_id = self.var_device.get().strip()
        if not device_id:
            messagebox.showerror("校验失败", "请填写 Device ID。")
            return
        url = self.var_url.get().strip().rstrip("/") + "/api/devices/register"
        try:
            r = requests.post(url, json={"device_id": device_id, "name": device_id}, timeout=15)
            body = r.json()
            code = (body.get("data") or {}).get("pairing_code", "")
            if body.get("success"):
                self._append_log(f"设备 {device_id} 已注册，配对码: {code}")
                messagebox.showinfo("注册成功", f"设备 {device_id}\n配对码: {code}")
                self._fetch_device_list()
                return
            if body.get("message") == "device_already_registered" and code:
                self._append_log(f"设备 {device_id} 已存在，配对码: {code}")
                messagebox.showinfo(
                    "设备已注册",
                    f"设备 {device_id} 已注册，无需重复注册。\n当前配对码: {code}",
                )
                self._fetch_device_list()
                return
            messagebox.showerror("注册失败", str(body.get("message") or body))
        except Exception as e:
            messagebox.showerror("注册失败", str(e))

    def _start(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            messagebox.showinfo("提示", "发送任务已在运行。")
            return

        try:
            interval = float(self.var_interval.get().strip())
            rows = int(self.var_rows.get().strip())
        except ValueError:
            messagebox.showerror("校验失败", "间隔须为数字，每帧行数须为整数。")
            return

        if interval <= 0 or rows <= 0:
            messagebox.showerror("校验失败", "间隔与每帧行数须为正。")
            return

        mode_key = self.var_mode.get()
        seed_s = self.var_seed.get().strip()
        seed: Optional[int] = None
        if seed_s:
            try:
                seed = int(seed_s)
            except ValueError:
                messagebox.showerror("校验失败", "随机种子须为整数或留空。")
                return

        mode: SenderMode
        csv_path: Optional[str] = None
        csv_limit: Optional[int] = None

        if mode_key == "status_cycle":
            mode = "status_cycle"
        elif mode_key == "status_random":
            mode = "status_random"
        else:
            messagebox.showerror("校验失败", f"未知模式: {mode_key}")
            return

        csv_path = self.var_csv.get().strip()
        if not csv_path:
            messagebox.showerror("校验失败", "请填写 CSV 文件路径。")
            return
        try:
            csv_limit = self._parse_optional_int(self.var_limit.get())
        except ValueError:
            messagebox.showerror("校验失败", "行数上限须为整数或留空。")
            return

        device_id = self.var_device.get().strip()
        if not device_id:
            messagebox.showerror("校验失败", "请填写 Device ID。")
            return

        self._stop.clear()
        self.btn_start.configure(state=tk.DISABLED)
        self.btn_stop.configure(state=tk.NORMAL)
        self._append_log(
            f"--- 开始 device={device_id} mode={mode_key} url={self.var_url.get().strip()} interval={interval} rows={rows} ---"
        )

        def worker() -> None:
            try:
                run_sender_loop(
                    base_url=self.var_url.get().strip(),
                    interval=interval,
                    rows_per_frame=rows,
                    mode=mode,
                    device_id=device_id,
                    csv_path=csv_path,
                    csv_limit=csv_limit,
                    seed=seed,
                    stop_event=self._stop,
                    log_fn=self._log_q.put,
                )
            except Exception as e:
                self._log_q.put(f"发送线程异常: {e}")
            finally:
                self._log_q.put("__THREAD_DONE__")

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def _stop_send(self) -> None:
        self._stop.set()
        self._append_log("--- 请求停止 ---")

    def _on_close(self) -> None:
        self._stop.set()
        self.destroy()


def main() -> None:
    app = MockSenderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
