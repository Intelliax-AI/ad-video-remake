"""Build a story film from story.json: narration -> timeline -> picture (the stage, frame by frame) -> sound -> mux.

    python build.py --work <dir>                     # the whole film: <dir>/out/<title>.mp4
    python build.py --work <dir> --at 3,24.5,38      # just those frames, as one contact sheet: <dir>/out/at.png
    python build.py --work <dir> --audio-only        # remix the sound onto the last picture
    python build.py --work <dir> --verify            # after building: transcribe the film and compare with the script

<dir> holds story.json and media/ (from fetch_media.py). The first run copies stage.html and fonts/ in from the
skill's templates; edit the copies. Narration, music and effects come from ElevenLabs (ELEVENLABS_API_KEY in the
environment or a .env / .env.local up the tree) and are cached in <dir>/audio, so reruns cost nothing.

Needs: pip install playwright numpy pillow imageio-ffmpeg scipy && python -m playwright install chromium
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import functools
import http.server
import json
import multiprocessing as mp
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import wave
from pathlib import Path

import numpy as np

SKILL = Path(__file__).resolve().parents[1]
SR = 48_000

DEFAULT_SFX = {
    "photo": ("A printed photograph dropped flat onto a wooden desk, single soft paper slap, close and dry", 0.6),
    "type": ("Vintage typewriter, six quick key strikes, close microphone, dry", 1.0),
    "papers": ("Stack of paper sheets sliding and fanning out across a table", 1.2),
    "whoosh": ("Fast airy cinematic whoosh transition, short, clean", 0.8),
    "buzz": ("Smartphone notification vibration buzz on a wooden table, two short pulses", 0.9),
    "scroll": ("Soft glassy smartphone scrolling ticks, quick flicks", 1.6),
    "freeze": ("Tape stop effect, music slowing down and dropping pitch to silence", 1.3),
    "heart": ("Single deep low heartbeat thump, cinematic, with sub bass", 1.0),
    "riser": ("Cinematic tension riser, noise and synth sweeping upward, ending abruptly", 2.6),
    "impact": ("Deep cinematic boom impact with a bright shimmer tail, trailer hit", 2.2),
    "pop": ("Soft bubbly user interface pop, friendly and short", 0.4),
    "glitch": ("Short digital glitch stutter, data corruption blip", 0.6),
    "sting": ("Warm uplifting cinematic brand sting, one wide major synth and piano chord blooming, long reverb tail", 4.0),
}
DEFAULT_GAIN = {"photo": 0.8, "type": 0.55, "whoosh": 0.6, "freeze": 1.0, "impact": 0.8, "sting": 0.9}


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        here = Path.cwd().resolve()
        for d in [here, *here.parents]:
            for name in (".env.local", ".env"):
                f = d / name
                if f.exists():
                    for line in f.read_text(encoding="utf-8").splitlines():
                        if line.strip().startswith("ELEVENLABS_API_KEY="):
                            key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        sys.exit("ELEVENLABS_API_KEY is not set (environment, or a .env / .env.local here or above). The narration needs it.")
    return key


def eleven(path: str, body: dict, out: Path, accept="audio/mpeg", timeout=600) -> Path:
    req = urllib.request.Request(f"https://api.elevenlabs.io{path}", data=json.dumps(body).encode(), method="POST",
                                 headers={"xi-api-key": api_key(), "Content-Type": "application/json", "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out.write_bytes(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"ElevenLabs {path} -> {e.code}: {e.read()[:300].decode(errors='replace')}")
    return out


def duration(p: Path) -> float:
    out = subprocess.run([ffmpeg(), "-i", str(p)], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


# ------------------------------------------------------------------ narration and timeline

def narration(story: dict, work: Path) -> dict:
    """Each line as an mp3 plus its word start times; cached by the line's text."""
    v = story["voice"]; d = work / "audio" / "voice"; d.mkdir(parents=True, exist_ok=True)
    lines = story["lines"]; out = {}
    for i, ln in enumerate(lines):
        mp3, js = d / f"{ln['key']}.mp3", d / f"{ln['key']}.json"
        if not (mp3.exists() and js.exists() and json.loads(js.read_text()).get("text") == ln["text"]):
            body = {"text": ln["text"], "model_id": v.get("model_id", "eleven_multilingual_v2"),
                    "voice_settings": {"stability": v.get("stability", 0.5), "similarity_boost": v.get("similarity", 0.8),
                                       "style": v.get("style", 0.25), "use_speaker_boost": True, "speed": v.get("speed", 0.95)},
                    # the neighbouring lines keep the delivery continuous across separately generated clips
                    "previous_text": lines[i - 1]["text"] if i else None, "next_text": lines[i + 1]["text"] if i + 1 < len(lines) else None}
            raw = work / "audio" / "voice" / f"{ln['key']}.raw.json"
            eleven(f"/v1/text-to-speech/{v['voice_id']}/with-timestamps?output_format=mp3_44100_192", body, raw, accept="application/json")
            r = json.loads(raw.read_text()); raw.unlink()
            mp3.write_bytes(base64.b64decode(r["audio_base64"]))
            a = r["alignment"]; words, cur, start = [], "", 0.0
            for ch, t0 in zip(a["characters"], a["character_start_times_seconds"]):
                if ch.isspace():
                    if cur: words.append([cur, round(start, 3)]); cur = ""
                    continue
                if not cur: start = t0
                cur += ch
            if cur: words.append([cur, round(start, 3)])
            js.write_text(json.dumps({"text": ln["text"], "words": words}))
            print(f"   voice {ln['key']}: {ln['text']}")
        out[ln["key"]] = {"mp3": mp3, "words": json.loads(js.read_text())["words"], "dur": duration(mp3)}
    return out


def resolve(spec, cues: dict, end: float | None = None) -> float:
    """The stage's time specs, in Python: 12.5 | "n3" | "n3+1.2" | "n9@roadmap-0.1" | "n6.end+1" | "END"."""
    if isinstance(spec, (int, float)):
        return float(spec)
    m = re.match(r"^\s*([A-Za-z]\w*)(?:@([^+\-\s]+)|\.(end))?\s*([+-]\s*[\d.]+)?\s*$", str(spec))
    if not m:
        return float(spec)
    key, word, is_end, off = m.groups()
    if key == "END":
        at = end
    else:
        c = cues[key]; at = c["at"] + (c["dur"] if is_end else 0)
        if word:
            norm = lambda s: re.sub(r"[^\w]", "", s.lower())
            at = c["at"] + next(w[1] for w in c["words"] if norm(w[0]).startswith(norm(word)))
    return at + (float(off.replace(" ", "")) if off else 0.0)


def timeline(story: dict, voice: dict) -> dict:
    cues, t = {}, 0.0
    for ln in story["lines"]:
        v = voice[ln["key"]]
        at = t + ln.get("gap", 0.5)
        cues[ln["key"]] = {"at": round(at, 3), "dur": round(v["dur"], 3), "words": v["words"]}
        t = at + v["dur"]
    return {"cues": cues, "end": round(resolve(story["end"], cues), 3)}


# ------------------------------------------------------------------ the stage, served and filmed

def serve(root: Path) -> tuple[http.server.ThreadingHTTPServer, int]:
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Quiet, directory=str(root)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


async def open_stage(p, port: int, size):
    b = await p.chromium.launch(args=["--force-color-profile=srgb"])
    page = await b.new_page(viewport={"width": size[0], "height": size[1]})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    await page.goto(f"http://127.0.0.1:{port}/stage.html", wait_until="load")
    try:
        await page.evaluate("window.ready")
    except Exception as e:
        sys.exit(f"the stage failed to start: {e} {errors}")
    return b, page


def render_part(args) -> str:
    port, size, fps, f0, f1, out = args
    from playwright.async_api import async_playwright

    async def run():
        async with async_playwright() as p:
            b, page = await open_stage(p, port, size)
            enc = subprocess.Popen([ffmpeg(), "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-",
                                    "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(fps), out], stdin=subprocess.PIPE)
            for f in range(f0, f1):
                await page.evaluate("t => window.seek(t)", f / fps)
                enc.stdin.write(await page.screenshot(type="jpeg", quality=94))
            enc.stdin.close(); enc.wait(); await b.close()
    asyncio.run(run())
    return out


def picture(work: Path, port: int, size, fps: int, total: float, workers: int) -> Path:
    n = int(round(total * fps)); step = -(-n // workers)
    parts = work / "out" / "parts"; parts.mkdir(parents=True, exist_ok=True)
    jobs = [(port, size, fps, i, min(n, i + step), str(parts / f"part{k}.mp4")) for k, i in enumerate(range(0, n, step))]
    with mp.get_context("spawn").Pool(len(jobs)) as pool:
        done = pool.map(render_part, jobs)
    (parts / "list.txt").write_text("".join(f"file '{Path(p).as_posix()}'\n" for p in done))
    video = work / "out" / "picture.mp4"
    subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(parts / "list.txt"), "-c", "copy", str(video)], check=True)
    return video


async def stage_info(port: int, size, stills: list[float] | None, work: Path) -> list:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b, page = await open_stage(p, port, size)
        cues = await page.evaluate("window.SFX")
        if stills:
            from PIL import Image, ImageDraw
            shots = []
            for t in stills:
                await page.evaluate("t => window.seek(t)", t)
                f = work / "out" / f"at_{t:07.2f}.png"; await page.screenshot(path=str(f)); shots.append((t, f))
            cols = min(4, len(shots)); rows = -(-len(shots) // cols); w, h = 640, 360
            sheet = Image.new("RGB", (w * cols, h * rows), "white")
            for i, (t, f) in enumerate(shots):
                im = Image.open(f).convert("RGB"); im.thumbnail((w, h)); ImageDraw.Draw(im).text((6, 4), f"{t:.2f}s", fill="yellow")
                sheet.paste(im, ((i % cols) * w, (i // cols) * h))
            sheet.save(work / "out" / "at.png"); print(f"   sheet: {work / 'out' / 'at.png'} (full frames beside it)")
        await b.close()
    return cues


# ------------------------------------------------------------------ sound

def decode(p: Path) -> np.ndarray:
    raw = subprocess.run([ffmpeg(), "-loglevel", "error", "-i", str(p), "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype="<f4").reshape(-1, 2).astype(np.float64)


def place(bus, sig, at, gain=1.0):
    i = int(round(at * SR))
    if i >= len(bus): return
    if i < 0: sig, i = sig[-i:], 0
    j = min(len(bus), i + len(sig)); bus[i:j] += gain * sig[: j - i]


def fade(sig, fin=0.0, fout=0.0):
    sig = sig.copy()
    if fin: k = min(len(sig), int(fin * SR)); sig[:k] *= np.linspace(0, 1, k)[:, None]
    if fout: k = min(len(sig), int(fout * SR)); sig[len(sig) - k:] *= np.linspace(1, 0, k)[:, None]
    return sig


def envelope(x, attack=0.02, release=0.35):
    m = np.abs(x).max(axis=1); hop = 480
    fr = m[: len(m) // hop * hop].reshape(-1, hop).max(axis=1); out = np.zeros_like(fr)
    a, r = np.exp(-hop / (attack * SR)), np.exp(-hop / (release * SR)); v = 0.0
    for i, s in enumerate(fr):
        v = a * v + (1 - a) * s if s > v else r * v + (1 - r) * s; out[i] = v
    e = np.repeat(out, hop); return np.pad(e, (0, len(m) - len(e)), mode="edge")


def sound(story: dict, work: Path, tl: dict, voice: dict, cues: list, total: float) -> Path:
    n = int(total * SR) + SR
    vbus, mbus, fbus = np.zeros((n, 2)), np.zeros((n, 2)), np.zeros((n, 2))
    for k, c in tl["cues"].items():
        v = decode(voice[k]["mp3"]); place(vbus, v / max(1e-6, np.abs(v).max()) * 0.7, c["at"])
    # the underscore: composed once for the story, started where its sound begins, cut dead at `until`
    mu = story["music"]; mdir = work / "audio"; mdir.mkdir(parents=True, exist_ok=True)
    mp3 = mdir / "music.mp3"; meta = mdir / "music.json"
    if not (mp3.exists() and meta.exists() and json.loads(meta.read_text()).get("prompt") == mu["prompt"]):
        eleven("/v1/music?output_format=mp3_44100_192", {"prompt": mu["prompt"], "music_length_ms": mu.get("length_ms", 46000), "model_id": mu.get("model_id", "music_v1")}, mp3, timeout=900)
        meta.write_text(json.dumps({"prompt": mu["prompt"]})); print("   music: composed")
    m = decode(mp3)
    loud = np.where(np.abs(m).max(axis=1) > 10 ** (-40 / 20))[0]
    offset = mu.get("offset", (loud[0] / SR - 0.2) if len(loud) else 0.0)  # skip a silent opening
    until = resolve(mu["until"], tl["cues"], tl["end"]) if mu.get("until") else total
    seg = m[int(max(0, offset) * SR): int((max(0, offset) + until + 0.12) * SR)]
    place(mbus, fade(seg, fin=0.6, fout=0.12) * mu.get("level", 0.55), 0.0)
    # effects: one generated sound per kind, laid on every cue the stage asked for
    kinds = {**DEFAULT_SFX, **{k: tuple(v) for k, v in story.get("sfx", {}).items()}}
    sdir = mdir / "sfx"; sdir.mkdir(exist_ok=True); cache = {}
    for at, kind, gain in cues:
        if kind not in kinds: continue
        if kind not in cache:
            f = sdir / f"{kind}.mp3"
            if not f.exists():
                text, secs = kinds[kind]
                eleven("/v1/sound-generation?output_format=mp3_44100_128", {"text": text, "duration_seconds": max(0.5, secs), "prompt_influence": 0.6}, f)
                print(f"   sfx {kind}: generated")
            s = decode(f); cache[kind] = s / max(1e-6, np.abs(s).max())
        place(fbus, cache[kind], at, 0.32 * gain)
    duck = 1 - 0.62 * np.clip(envelope(vbus) / 0.25, 0, 1)
    mix = (vbus + mbus * duck[:, None] + fbus)[: int(total * SR)]
    path = work / "out" / "mix.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(mix / max(1.0, np.abs(mix).max() / 0.95), -1, 1) * 32767).astype("<i2").tobytes())
    return path


def mux(video: Path, mix: Path, final: Path, total: float) -> None:
    subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-i", str(video), "-i", str(mix), "-filter_complex", "[1:a]loudnorm=I=-14:TP=-1.5:LRA=11[a]",
                    "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-tune", "film", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-t", f"{total:.3f}", "-movflags", "+faststart", str(final)], check=True)
    subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-i", str(final), "-vf", f"fps=1/{total / 24:.3f},scale=384:-1,tile=6x4", "-frames:v", "1",
                    str(final.with_name("contact.png"))], check=True)


def checks(final: Path, story: dict, verify: bool) -> None:
    """What to look at before handing over: length, loudness, hard jumps, and (with --verify) the words."""
    err = subprocess.run([ffmpeg(), "-i", str(final), "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True).stderr
    lufs = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    raw = subprocess.run([ffmpeg(), "-loglevel", "error", "-i", str(final), "-vf", "scale=160:90,format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
    f = np.frombuffer(raw, np.uint8).reshape(-1, 90, 160).astype(np.float32); d = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2))
    fps = story.get("fps", 60); top = np.argsort(d)[-5:][::-1]
    print(f"== {final.name}: {duration(final):.1f}s, {lufs[-1] if lufs else '?'} LUFS")
    print("   biggest frame-to-frame changes (a hard cut shows as 35+; check any you did not mean):",
          ", ".join(f"{(i + 1) / fps:.2f}s={d[i]:.0f}" for i in top))
    if verify:
        wav = final.with_suffix(".check.mp3")
        subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-i", str(final), "-vn", "-ac", "1", "-b:a", "96k", str(wav)], check=True)
        boundary = "----storyfilm"
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"model_id\"\r\n\r\nscribe_v1\r\n--{boundary}\r\n"
                f"Content-Disposition: form-data; name=\"file\"; filename=\"a.mp3\"\r\nContent-Type: audio/mpeg\r\n\r\n").encode() + wav.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request("https://api.elevenlabs.io/v1/speech-to-text", data=body, method="POST",
                                     headers={"xi-api-key": api_key(), "Content-Type": f"multipart/form-data; boundary={boundary}"})
        heard = json.loads(urllib.request.urlopen(req, timeout=300).read())["text"]; wav.unlink()
        norm = lambda s: re.sub(r"[^a-z0-9 ]", "", s.lower().replace("-", " ")).split()
        want = [w for ln in story["lines"] for w in norm(ln["text"])]; got = set(norm(heard)); joined = "".join(norm(heard))
        missing = [w for w in want if w not in got and w not in joined]  # "Skill maxing" still counts as "skillmaxing"
        print(f"   heard: {heard}")
        print("   every scripted word is in the mix" if not missing else f"   words not heard (check pronunciation or mix): {missing}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=".", help="folder with story.json and media/")
    ap.add_argument("--at", help="comma-separated seconds: a contact sheet of just those frames")
    ap.add_argument("--audio-only", action="store_true")
    ap.add_argument("--verify", action="store_true", help="transcribe the finished film and check every scripted word is heard")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    work = Path(a.work).resolve(); story = json.loads((work / "story.json").read_text(encoding="utf-8"))
    for name in ("stage.html", "fonts"):  # the editable copies live in the work folder
        src, dst = SKILL / "templates" / name, work / name
        if not dst.exists():
            (shutil.copytree if src.is_dir() else shutil.copy)(src, dst); print(f"   copied {name} into {work}")
    if not (work / "media" / "manifest.json").exists():
        sys.exit("no media/manifest.json: run scripts/fetch_media.py --work <dir> first")
    (work / "out").mkdir(exist_ok=True)
    voice = narration(story, work)
    tl = timeline(story, voice); (work / "timeline.json").write_text(json.dumps(tl, indent=1))
    total, size, fps = tl["end"], tuple(story.get("size", [1920, 1080])), story.get("fps", 60)
    print(f"== {total:.1f}s: " + "  ".join(f"{k}@{c['at']:.2f}" for k, c in tl["cues"].items()))
    srv, port = serve(work)
    try:
        if a.at:
            asyncio.run(stage_info(port, size, [float(x) for x in a.at.split(",")], work)); return
        cues = asyncio.run(stage_info(port, size, None, work))
        video = work / "out" / "picture.mp4"
        if not a.audio_only or not video.exists():
            video = picture(work, port, size, fps, total, a.workers)
        final = work / "out" / f"{story.get('title', 'story-film')}.mp4"
        mux(video, sound(story, work, tl, voice, cues, total), final, total)
        checks(final, story, a.verify)
        print(f"== done: {final}")
    finally:
        srv.shutdown()


if __name__ == "__main__":
    main()
