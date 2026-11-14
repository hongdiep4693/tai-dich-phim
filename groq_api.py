"""Gọi Groq: xoay vòng nhiều API key, kiểm tra key, tìm model chạy được."""
import io
import json
import re
import threading
import time
import wave

import requests

GROQ = "https://api.groq.com/openai/v1"


class KeyPool:
    """Danh sách API key, xoay vòng theo thứ tự: mỗi request dùng key kế tiếp."""

    def __init__(self, text):
        keys = [k.strip() for k in re.split(r"[\s,;]+", text) if k.strip()]
        self.keys = list(dict.fromkeys(keys))  # bỏ trùng, giữ thứ tự
        if not self.keys:
            raise ValueError("Chưa nhập Groq API key (mỗi dòng một key).")
        self.i = 0
        self.lock = threading.Lock()

    def get(self):
        with self.lock:
            if not self.keys:
                raise RuntimeError("Tất cả API key đều không hợp lệ.")
            k = self.keys[self.i % len(self.keys)]
            self.i += 1
            return k

    def disable(self, k):
        with self.lock:
            if k in self.keys:
                self.keys.remove(k)

    def __len__(self):
        return len(self.keys)


def groq_request(pool, endpoint, retries=None, **kw):
    retries = retries or max(6, len(pool) * 3)
    for a in range(retries):
        k = pool.get()  # key kế tiếp trong vòng xoay
        r = requests.post(f"{GROQ}/{endpoint}", headers={"Authorization": f"Bearer {k}"},
                          timeout=300, **kw)
        if r.status_code == 401:  # key sai/bị thu hồi -> loại khỏi vòng xoay
            pool.disable(k)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            # key này hết hạn mức -> request sau tự sang key kế tiếp;
            # chỉ nghỉ khi đã đi hết một vòng mà vẫn bị giới hạn
            if (a + 1) % max(len(pool), 1) == 0:
                time.sleep(5 * ((a + 1) // max(len(pool), 1)))
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"Groq {r.status_code}: {r.text[:500]}")
        return r
    raise RuntimeError("Groq: tất cả key đều quá giới hạn/lỗi, thử lại sau.")


def groq_json(pool, model, system, user):
    """Gọi chat ở chế độ JSON, trả về dict."""
    for _ in range(3):
        r = groq_request(pool, "chat/completions", json={
            "model": model, "temperature": 0.3,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}]})
        try:
            return json.loads(r.json()["choices"][0]["message"]["content"])
        except Exception:
            continue
    raise RuntimeError("Groq trả JSON không hợp lệ.")


# ----------------------------------------------------------- kiểm tra key / model
def check_keys(keys_text, log):
    """Kiểm tra từng key bằng GET /models. Trả về danh sách key dùng được."""
    good = []
    for n, k in enumerate(KeyPool(keys_text).keys, 1):
        tag = f"Key #{n} (…{k[-4:]})"
        try:
            r = requests.get(f"{GROQ}/models", headers={"Authorization": f"Bearer {k}"}, timeout=30)
        except Exception as e:
            log(f"{tag}: lỗi mạng - {e}")
            continue
        if r.status_code == 200:
            log(f"{tag}: OK")
            good.append(k)
        elif r.status_code == 401:
            log(f"{tag}: SAI hoặc đã bị thu hồi")
        elif r.status_code == 429:
            log(f"{tag}: hợp lệ nhưng đang bị giới hạn tốc độ/hạn mức")
            good.append(k)
        else:
            log(f"{tag}: HTTP {r.status_code} - {r.text[:150]}")
    return good


def _silent_wav(sec=1, sr=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"\x00\x00" * sr * sec)
    return buf.getvalue()


def _try_model(pool, kind, model):
    """Gọi thử 1 request nhỏ. Trả về (ok, thông báo)."""
    for _ in range(3):
        k = pool.get()
        h = {"Authorization": f"Bearer {k}"}
        try:
            if kind == "whisper":
                r = requests.post(f"{GROQ}/audio/transcriptions", headers=h, timeout=90,
                                  files={"file": ("t.wav", _silent_wav(), "audio/wav")},
                                  data={"model": model, "response_format": "verbose_json",
                                        "language": "zh"})
            else:  # chat: app cần chế độ JSON nên thử luôn json_object
                r = requests.post(f"{GROQ}/chat/completions", headers=h, timeout=90, json={
                    "model": model, "max_tokens": 20,
                    "response_format": {"type": "json_object"},
                    "messages": [{"role": "user", "content": 'Reply with JSON: {"ok": true}'}]})
        except Exception as e:
            return False, f"lỗi mạng: {e}"
        if r.status_code == 200:
            return True, "chạy được"
        if r.status_code == 429:
            time.sleep(3)
            continue
        try:
            msg = r.json()["error"]["message"]
        except Exception:
            msg = r.text
        return False, f"HTTP {r.status_code}: {msg[:120]}"
    return False, "bị giới hạn tốc độ (429), chưa kiểm tra được"


def find_working_models(keys_text, log):
    """Thử từng model Groq. Trả về (model nhận dạng chạy được, model dịch chạy được)."""
    good = check_keys(keys_text, log)
    if not good:
        raise RuntimeError("Không có key nào dùng được.")
    pool = KeyPool("\n".join(good))
    r = requests.get(f"{GROQ}/models", headers={"Authorization": f"Bearer {pool.get()}"}, timeout=30)
    r.raise_for_status()
    ids = sorted(m["id"] for m in r.json().get("data", []) if m.get("active", True))
    log(f"Groq có {len(ids)} model. Đang thử từng model…")
    skip = ("guard", "tts", "orpheus", "playai", "embed", "safeguard", "allam")
    whisper = [m for m in ids if "whisper" in m]
    chat = [m for m in ids if "whisper" not in m and not any(x in m for x in skip)]
    w_ok, c_ok = [], []
    for m in whisper:
        ok, msg = _try_model(pool, "whisper", m)
        log(f"  [nhận dạng] {m}: {msg}")
        if ok:
            w_ok.append(m)
    for m in chat:
        ok, msg = _try_model(pool, "chat", m)
        log(f"  [dịch] {m}: {msg}")
        if ok:
            c_ok.append(m)
    # ưu tiên: whisper-large-v3 trước; model dịch lớn (70b/120b) trước
    w_ok.sort(key=lambda m: (m != "whisper-large-v3", m))
    c_ok.sort(key=lambda m: (not any(x in m for x in ("70b", "120b")), m))
    return w_ok, c_ok
