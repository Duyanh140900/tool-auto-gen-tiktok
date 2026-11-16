from pathlib import Path
from src.downloader import has_video_stream
p = Path('sample_tikvid.mp4')
with open("test_out.txt", "w", encoding="utf-8") as f:
    f.write(f"File size: {p.stat().st_size}\n")
    f.write(f"Has video stream: {has_video_stream(p)}\n")
print("Done writing test_out.txt")
