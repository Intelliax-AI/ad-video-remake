"""Take a reference ad apart: frames to look at, and the numbers behind its sound.

    python analyze_reference.py <youtube-url-or-video-file> --out ref/
    python analyze_reference.py ref/ref.mp4 --out ref/ --range 5.9-10.3 --fps 4     # a closer look at one stretch

Writes to --out:
    ref.mp4             the video (downloaded with yt-dlp when given a URL)
    sheet_NN.png        contact sheets, 12 frames each (default 2 fps, so each sheet is 6 s), time runs left to right
    range.png           with --range: one sheet of just that stretch
    report.json         duration, size, fps, per-second loudness (dB), onsets, tempo estimate, transcript
Prints the report too. Read every sheet before planning a single scene: the storyboard comes from these.

Needs: pip install yt-dlp numpy imageio-ffmpeg   (faster-whisper optional, for the transcript)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def fetch(src: str, out: Path) -> Path:
    if Path(src).exists():
        return Path(src)
    dest = out / "ref.mp4"
    if dest.exists():
        return dest
    subprocess.run([sys.executable, "-m", "yt_dlp", "--js-runtimes", "node", "--ffmpeg-location", ffmpeg(),
                    "-f", "bv*[height<=1080]+ba/b", "--merge-output-format", "mp4", "-o", str(dest), src], check=True)
    return dest


def probe(video: Path) -> dict:
    info = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(video)], capture_output=True, text=True).stderr
    d = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info)
    v = re.search(r"Video: .*?(\d{3,5})x(\d{3,5}).*?([\d.]+) fps", info)
    return {"duration": int(d[1]) * 3600 + int(d[2]) * 60 + float(d[3]) if d else None,
            "width": int(v[1]) if v else None, "height": int(v[2]) if v else None, "fps": float(v[3]) if v else None,
            "has_audio": "Audio:" in info}


def sheets(video: Path, out: Path, fps: float) -> None:
    subprocess.run([ffmpeg(), "-loglevel", "error", "-y", "-i", str(video), "-vf", f"fps={fps},scale=480:-1,tile=4x3",
                    str(out / "sheet_%02d.png")], check=True)


def range_sheet(video: Path, out: Path, a: float, b: float, fps: float) -> None:
    n = max(1, int((b - a) * fps))
    cols = 4
    rows = (n + cols - 1) // cols
    subprocess.run([ffmpeg(), "-loglevel", "error", "-y", "-ss", str(a), "-t", str(b - a), "-i", str(video),
                    "-vf", f"fps={fps},scale=480:-1,tile={cols}x{rows}", "-frames:v", "1", str(out / "range.png")], check=True)


def audio_numbers(video: Path, out: Path) -> dict:
    wav = out / "ref.wav"
    subprocess.run([ffmpeg(), "-loglevel", "error", "-y", "-i", str(video), "-ac", "1", "-ar", "22050", str(wav)], check=True)
    with wave.open(str(wav)) as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(float) / 32768
    hop, win = 512, np.hanning(1024)
    spec = np.array([np.abs(np.fft.rfft(x[i:i + 1024] * win)) for i in range(0, len(x) - 1024, hop)])
    flux = np.maximum(np.diff(np.log1p(spec * 10), axis=0), 0).sum(1)
    flux = (flux - flux.mean()) / (flux.std() + 1e-9)
    t = np.arange(len(flux)) * hop / sr
    onsets = [round(float(t[i]), 2) for i in range(3, len(flux) - 3) if flux[i] > 2.0 and flux[i] == flux[i - 3:i + 4].max()]
    ac = np.correlate(flux, flux, "full")[len(flux) - 1:]
    lags = np.arange(len(ac)) * hop / sr
    m = (lags > 0.25) & (lags < 0.75)                 # one beat, 80-240 bpm
    beat = float(lags[m][np.argmax(ac[m])])
    loud = [round(float(20 * np.log10(np.sqrt((x[s * sr:(s + 1) * sr] ** 2).mean()) + 1e-9)), 1) for s in range(int(len(x) / sr) + 1)]
    return {"onsets": onsets, "tempo_bpm": round(60 / beat, 1), "loudness_db_per_second": loud}


def transcript(out: Path) -> list | None:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    segs, _ = WhisperModel("base", device="cpu", compute_type="int8").transcribe(str(out / "ref.wav"), vad_filter=True)
    return [{"start": round(s.start, 1), "end": round(s.end, 1), "text": s.text.strip()} for s in segs]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("--out", type=Path, default=Path("ref"))
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--range", help="a-b seconds: one sheet of just that stretch")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    video = fetch(a.src, a.out)
    if a.range:
        lo, hi = (float(v) for v in a.range.split("-"))
        range_sheet(video, a.out, lo, hi, a.fps)
        print(a.out / "range.png")
        return
    report = {"video": str(video), **probe(video)}
    sheets(video, a.out, a.fps)
    if report["has_audio"]:
        report.update(audio_numbers(video, a.out))
        report["transcript"] = transcript(a.out)
    (a.out / "report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))
    print(f"sheets: {sorted(p.name for p in a.out.glob('sheet_*.png'))}  ({12 / a.fps:.0f} s each, {1 / a.fps:.2f} s per tile)")


if __name__ == "__main__":
    main()
