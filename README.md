# Douyin Dubber

Dán nội dung chia sẻ Douyin -> tự tách link -> tải video -> nhận dạng lời thoại (Groq Whisper)
-> đọc toàn bộ để tóm tắt cốt truyện, lập danh sách nhân vật + cách xưng hô -> dịch có ngữ cảnh
-> lồng tiếng Edge TTS -> burn phụ đề -> xóa metadata -> đổi pitch/tempo.

## Cấu trúc file

| File | Nội dung |
|---|---|
| `main.py` | điểm vào, chỉ mở giao diện |
| `ui.py` | giao diện Tkinter, nút Kiểm tra key / Tìm model |
| `pipeline.py` | chạy tuần tự các bước |
| `douyin.py` | lấy link chuẩn và tải video (trang chia sẻ, dự phòng yt-dlp) |
| `transcribe.py` | nhận dạng lời thoại bằng Groq Whisper |
| `translate.py` | tạo ngữ cảnh (cốt truyện, nhân vật, xưng hô) và dịch |
| `tts.py` | Edge TTS và ghép track lồng tiếng |
| `ffmpeg_utils.py` | tách âm thanh, đổi wav, render (phụ đề, pitch/tempo, xóa metadata) |
| `groq_api.py` | gọi Groq, xoay vòng nhiều key, kiểm tra key, tìm model |
| `common.py` | hằng số, ngôn ngữ/giọng, hàm dùng chung |
| `build.bat` | build .exe trên máy Windows |
| `.github/workflows/build.yml` | build .exe tự động trên GitHub |

Muốn sửa việc gì thì mở đúng file đó: ví dụ prompt dịch -> `translate.py`, lệnh ffmpeg -> `ffmpeg_utils.py`.

## Nhiều Groq API key

Dán mỗi dòng một key. Mỗi request dùng key kế tiếp (1 -> 2 -> 3 -> 1 ...). Key lỗi 401 tự bị loại,
key bị 429 thì request sau sang key khác. Nút **Kiểm tra key** test từng key; nút **Tìm model chạy được**
thử từng model Groq và chỉ giữ model dùng được trong hai ô model.

## Chạy từ mã nguồn

1. Cài Python 3.10+ (tick "Add to PATH") và ffmpeg (`winget install Gyan.FFmpeg`).
2. `pip install -r requirements.txt` rồi `python main.py`.

## Build .exe

- Trên máy: chạy `build.bat`, rồi copy ffmpeg.exe, ffprobe.exe vào `dist\`.
- Trên GitHub: tab **Actions** -> **Build Windows EXE** -> **Run workflow** -> tải artifact
  `DouyinDubber-win64` (đã kèm ffmpeg). Đẩy tag `v1.0.0` để tự tạo Release.

## Ghi chú

- Douyin hay bắt cookies: nếu tải lỗi, chọn "Lấy cookies từ trình duyệt" (đã đăng nhập Douyin),
  hoặc dùng cookies.txt, hoặc nút "Chọn video có sẵn".
- Mỗi video có thư mục riêng: `segments_zh.json`, `context.json`, `sub.srt`, `dub.wav`, `final_*.mp4`.
- `settings.json` chứa API key của bạn và đã được chặn trong `.gitignore`.
- Chỉ dùng với video bạn có quyền sử dụng/đăng lại.
