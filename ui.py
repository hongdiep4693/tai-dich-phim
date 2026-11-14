"""Giao diện Tkinter."""
import json
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from common import LANGS, SETTINGS_FILE
from groq_api import check_keys, find_working_models
from pipeline import pipeline


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Douyin Dubber")
        self.geometry("860x860")
        self.q = queue.Queue()
        self.vars = {}
        self.local_video = ""
        s = self.load()
        pad = {"padx": 8, "pady": 3}

        # --- nguồn
        f = ttk.LabelFrame(self, text="Nguồn")
        f.pack(fill="x", **pad)
        ttk.Label(f, text="Dán nội dung chia sẻ Douyin:").pack(anchor="w", padx=6)
        self.txt = tk.Text(f, height=4, wrap="word")
        self.txt.pack(fill="x", padx=6, pady=3)
        row = ttk.Frame(f); row.pack(fill="x", padx=6, pady=3)
        ttk.Button(row, text="Chọn video có sẵn…", command=self.pick_video).pack(side="left")
        self.lv = ttk.Label(row, text="(không dùng)"); self.lv.pack(side="left", padx=8)

        # --- Groq
        g = ttk.LabelFrame(self, text="Groq & dịch")
        g.pack(fill="x", **pad)
        ttk.Label(g, text="Groq API keys (mỗi dòng 1 key, dùng xoay vòng từ trên xuống):").pack(anchor="w", padx=6)
        self.keys_txt = tk.Text(g, height=4, wrap="none")
        self.keys_txt.pack(fill="x", padx=6, pady=2)
        self.keys_txt.insert("1.0", s.get("api_key", ""))
        br = ttk.Frame(g); br.pack(fill="x", padx=6, pady=2)
        self.btn_keys = ttk.Button(br, text="Kiểm tra key", command=self.test_keys)
        self.btn_keys.pack(side="left")
        self.btn_models = ttk.Button(br, text="Tìm model chạy được", command=self.find_models)
        self.btn_models.pack(side="left", padx=6)
        self.model_cb = self.combo(g, "model", "Model dịch/ngữ cảnh", s.get("model", "llama-3.3-70b-versatile"))
        self.whisper_cb = self.combo(g, "whisper", "Model nhận dạng", s.get("whisper", "whisper-large-v3"))
        r = ttk.Frame(g); r.pack(fill="x", padx=6, pady=2)
        ttk.Label(r, text="Ngôn ngữ đích", width=22).pack(side="left")
        self.vars["lang"] = tk.StringVar(value=s.get("lang", "Tiếng Việt"))
        cb = ttk.Combobox(r, textvariable=self.vars["lang"], values=list(LANGS), state="readonly", width=20)
        cb.pack(side="left"); cb.bind("<<ComboboxSelected>>", self.on_lang)

        # --- TTS
        t = ttk.LabelFrame(self, text="Giọng đọc (Edge TTS)")
        t.pack(fill="x", **pad)
        r = ttk.Frame(t); r.pack(fill="x", padx=6, pady=2)
        ttk.Label(r, text="Giọng", width=22).pack(side="left")
        self.vars["voice"] = tk.StringVar(value=s.get("voice", "vi-VN-HoaiMyNeural"))
        self.voice_cb = ttk.Combobox(r, textvariable=self.vars["voice"], width=28,
                                     values=LANGS[self.vars["lang"].get()][1])
        self.voice_cb.pack(side="left")
        self.scale(t, "tts_rate", "Tốc độ đọc TTS (%)", -50, 50, s.get("tts_rate", 0), int)
        self.scale(t, "tts_pitch", "Cao độ TTS (Hz)", -50, 50, s.get("tts_pitch", 0), int)
        self.scale(t, "max_speedup", "Tăng tốc tối đa để khớp thời lượng", 1.0, 2.0, s.get("max_speedup", 1.5), float)
        self.scale(t, "orig_vol", "Âm lượng tiếng gốc (0 = tắt)", 0.0, 1.0, s.get("orig_vol", 0.0), float)

        # --- video đầu ra
        v = ttk.LabelFrame(self, text="Video đầu ra")
        v.pack(fill="x", **pad)
        self.check(v, "burn", "Burn phụ đề đã dịch", s.get("burn", True))
        self.field(v, "font", "Font phụ đề", s.get("font", "Arial"))
        self.scale(v, "fontsize", "Cỡ chữ phụ đề", 8, 48, s.get("fontsize", 18), int)
        self.scale(v, "margin", "Khoảng cách đáy", 0, 200, s.get("margin", 40), int)
        self.check(v, "strip_meta", "Xóa metadata", s.get("strip_meta", True))
        self.scale(v, "pitch", "Pitch (1.0 = giữ nguyên)", 0.8, 1.25, s.get("pitch", 1.0), float)
        self.scale(v, "tempo", "Tempo video+audio (1.0 = giữ nguyên)", 0.8, 1.25, s.get("tempo", 1.0), float)

        # --- thư mục / cookies
        d = ttk.LabelFrame(self, text="Tải về / thư mục")
        d.pack(fill="x", **pad)
        self.field(d, "outdir", "Thư mục lưu", s.get("outdir", str(Path.home() / "DouyinDubber")))
        self.field(d, "cookies", "cookies.txt (tuỳ chọn)", s.get("cookies", ""))
        r = ttk.Frame(d); r.pack(fill="x", padx=6, pady=2)
        ttk.Label(r, text="Lấy cookies từ trình duyệt", width=22).pack(side="left")
        self.vars["browser"] = tk.StringVar(value=s.get("browser", "none"))
        ttk.Combobox(r, textvariable=self.vars["browser"], width=12, state="readonly",
                     values=["none", "chrome", "edge", "firefox"]).pack(side="left")

        self.btn = ttk.Button(self, text="BẮT ĐẦU", command=self.start)
        self.btn.pack(pady=6)
        self.pb = ttk.Progressbar(self, maximum=100); self.pb.pack(fill="x", padx=8)
        self.lbl = ttk.Label(self, text="Sẵn sàng"); self.lbl.pack(anchor="w", padx=8)
        self.logbox = scrolledtext.ScrolledText(self, height=10, state="disabled")
        self.logbox.pack(fill="both", expand=True, **pad)
        self.after(100, self.poll)

    # ------------------------------------------------------------ widget helpers
    def field(self, parent, key, label, default, show=None):
        r = ttk.Frame(parent); r.pack(fill="x", padx=6, pady=2)
        ttk.Label(r, text=label, width=22).pack(side="left")
        self.vars[key] = tk.StringVar(value=default)
        ttk.Entry(r, textvariable=self.vars[key], show=show or "").pack(side="left", fill="x", expand=True)

    def combo(self, parent, key, label, default):
        r = ttk.Frame(parent); r.pack(fill="x", padx=6, pady=2)
        ttk.Label(r, text=label, width=22).pack(side="left")
        self.vars[key] = tk.StringVar(value=default)
        cb = ttk.Combobox(r, textvariable=self.vars[key], values=[default])
        cb.pack(side="left", fill="x", expand=True)
        return cb

    def scale(self, parent, key, label, lo, hi, default, typ):
        r = ttk.Frame(parent); r.pack(fill="x", padx=6, pady=2)
        ttk.Label(r, text=label, width=34).pack(side="left")
        var = tk.DoubleVar(value=default)
        self.vars[key] = var
        val = ttk.Label(r, width=6); val.pack(side="right")

        def upd(_=None):
            x = var.get()
            val.config(text=str(int(round(x))) if typ is int else f"{x:.2f}")
        ttk.Scale(r, from_=lo, to=hi, variable=var, command=upd).pack(side="left", fill="x", expand=True)
        upd()
        self.vars[key + "_typ"] = typ

    def check(self, parent, key, label, default):
        self.vars[key] = tk.BooleanVar(value=default)
        ttk.Checkbutton(parent, text=label, variable=self.vars[key]).pack(anchor="w", padx=6)

    def on_lang(self, _=None):
        voices = LANGS[self.vars["lang"].get()][1]
        self.voice_cb["values"] = voices
        self.vars["voice"].set(voices[0])

    def pick_video(self):
        p = filedialog.askopenfilename(filetypes=[("Video", "*.mp4 *.mov *.mkv *.webm")])
        if p:
            self.local_video = p
            self.lv.config(text=Path(p).name)

    # ------------------------------------------------------------ kiểm tra key / model
    def _bg(self, fn):
        self.btn_keys.config(state="disabled")
        self.btn_models.config(state="disabled")

        def run_it():
            try:
                fn()
            except Exception as e:
                self.q.put(("log", f"LỖI: {e}"))
            finally:
                self.q.put(("buttons", None))
        threading.Thread(target=run_it, daemon=True).start()

    def test_keys(self):
        keys = self.keys_txt.get("1.0", "end").strip()
        log = lambda m: self.q.put(("log", m))

        def job():
            log("— Kiểm tra key —")
            good = check_keys(keys, log)
            log(f"Kết quả: {len(good)} key dùng được.")
        self._bg(job)

    def find_models(self):
        keys = self.keys_txt.get("1.0", "end").strip()
        log = lambda m: self.q.put(("log", m))

        def job():
            log("— Tìm model chạy được (có thể mất 1-2 phút) —")
            w, c = find_working_models(keys, log)
            log(f"Nhận dạng chạy được: {', '.join(w) or 'không có'}")
            log(f"Dịch chạy được: {', '.join(c) or 'không có'}")
            self.q.put(("models", (w, c)))
        self._bg(job)

    # ------------------------------------------------------------ cấu hình
    def load(self):
        try:
            return json.loads(SETTINGS_FILE.read_text("utf-8"))
        except Exception:
            return {}

    def collect(self):
        c = {}
        for k, v in self.vars.items():
            if k.endswith("_typ"):
                continue
            val = v.get()
            typ = self.vars.get(k + "_typ")
            if typ is int:
                val = int(round(val))
            elif typ is float:
                val = round(float(val), 3)
            c[k] = val
        c["api_key"] = self.keys_txt.get("1.0", "end").strip()
        c["text"] = self.txt.get("1.0", "end").strip()
        c["local_video"] = self.local_video
        return c

    # ------------------------------------------------------------ chạy
    def start(self):
        c = self.collect()
        if not c["text"] and not c["local_video"]:
            return messagebox.showwarning("Thiếu dữ liệu", "Hãy dán link Douyin hoặc chọn video có sẵn.")
        saved = {k: v for k, v in c.items() if k not in ("text", "local_video")}
        try:
            SETTINGS_FILE.write_text(json.dumps(saved, ensure_ascii=False, indent=1), "utf-8")
        except Exception:
            pass
        self.btn.config(state="disabled")
        self.pb["value"] = 0
        threading.Thread(target=self.work, args=(c,), daemon=True).start()

    def work(self, c):
        try:
            final = pipeline(c, lambda m: self.q.put(("log", m)),
                             lambda n, p: self.q.put(("step", (n, p))))
            self.q.put(("done", str(final)))
        except Exception as e:
            self.q.put(("error", str(e)))

    def poll(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "log":
                    self.log(data)
                elif kind == "step":
                    self.lbl.config(text=data[0]); self.pb["value"] = data[1]; self.log(f"▶ {data[0]}")
                elif kind == "done":
                    self.btn.config(state="normal")
                    if messagebox.askyesno("Xong", f"{data}\n\nMở thư mục chứa file?") and os.name == "nt":
                        os.startfile(Path(data).parent)
                elif kind == "buttons":
                    self.btn_keys.config(state="normal")
                    self.btn_models.config(state="normal")
                elif kind == "models":
                    w, c = data
                    for cb, var, lst in ((self.whisper_cb, "whisper", w), (self.model_cb, "model", c)):
                        if lst:
                            cb["values"] = lst
                            if self.vars[var].get() not in lst:
                                self.vars[var].set(lst[0])
                                self.log(f"Đã đổi {var} sang: {lst[0]}")
                elif kind == "error":
                    self.btn.config(state="normal"); self.lbl.config(text="Lỗi")
                    self.log("LỖI: " + data)
                    messagebox.showerror("Lỗi", data[:1500])
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def log(self, m):
        self.logbox.config(state="normal")
        self.logbox.insert("end", m + "\n")
        self.logbox.see("end")
        self.logbox.config(state="disabled")
