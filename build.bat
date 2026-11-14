@echo off
REM Build DouyinDubber.exe tren may Windows
pip install -r requirements.txt pyinstaller
pyinstaller --onefile --noconsole --name DouyinDubber --collect-all yt_dlp --collect-all edge_tts --collect-all gtts --collect-all sherpa_onnx main.py
echo.
echo Xong. Copy ffmpeg.exe va ffprobe.exe vao thu muc dist\ canh DouyinDubber.exe
pause
