"""Film an HTML stage into an ad, and score it: picture, sound effects on the hit points, a music bed, mux.

    python build.py --stage stage.html --config config.json --out out/             # everything
    python build.py --stage stage.html --config config.json --out out/ --at 1,3.2  # contact sheet of those moments
    python build.py ... --audio-only                                                # redo the sound, keep the picture
    python build.py ... --audio-only --audio-from other.mp4                         # lay another file's audio under it

The stage contract (see templates/stage.html): a page at the config's width x height that defines
    window.ready   a promise that resolves once fonts and images are loaded and layout is measured
    window.render  render(t) draws the exact state at t seconds, from t alone (no CSS transitions, no timers)
Frames are filmed by several pages at once, out of order, so render(t) must never depend on the previous call.

Sound: with ELEVENLABS_API_KEY (environment, or a .env / .env.local in the working directory or any parent) the
bed is Eleven Music, laid out section by section, and each effect kind is one ElevenLabs sound effect; both are
cached in <out>/audio. Without a key both are synthesised here, following the same sections and cues.

Needs: pip install playwright numpy pillow imageio-ffmpeg && python -m playwright install chromium
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import wave
from pathlib import Path

import numpy as np

SR = 44100


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def api_key() -> str | None:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if key:
        return key
    here = Path.cwd().resolve()
    for d in [here, *here.parents]:
        for name in (".env.local", ".env"):
            f = d / name
            if f.exists():
                for line in f.read_text(encoding="utf-8").splitlines():
                    if line.strip().startswith("ELEVENLABS_API_KEY="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    return None


# ------------------------------------------------------------------ picture
async def _film(stage: Path, times: list[float], dest: Path, workers: int, size: tuple[int, int]) -> None:
    from playwright.async_api import async_playwright
    dest.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--allow-file-access-from-files"])

        async def run(chunk: list[tuple[int, float]]) -> None:
            page = await browser.new_page(viewport={"width": size[0], "height": size[1]}, device_scale_factor=1)
            await page.goto(stage.as_uri())
            await page.evaluate("window.ready")
            for i, t in chunk:
                await page.evaluate(f"render({t:.5f})")
                await page.screenshot(path=str(dest / f"{i:05d}.jpg"), type="jpeg", quality=93)
            await page.close()

        jobs = list(enumerate(times))
        workers = max(1, min(workers, len(jobs)))
        await asyncio.gather(*(run(jobs[k::workers]) for k in range(workers)))
        await browser.close()


def film_picture(stage: Path, cfg: dict, work: Path, workers: int) -> Path:
    frames = work / "frames"
    for f in frames.glob("*.jpg") if frames.exists() else []:
        f.unlink()
    fps, total = cfg["fps"], cfg["total"]
    asyncio.run(_film(stage, [i / fps for i in range(int(round(total * fps)))], frames, workers, (cfg["width"], cfg["height"])))
    video = work / "picture.mp4"
    # screenshots are full-range JPEG: convert to TV range BT.709, or players show it washed out
    subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(frames / "%05d.jpg"),
                    "-vf", "scale=in_range=pc:out_range=tv:out_color_matrix=bt709,format=yuv420p", "-c:v", "libx264", "-preset", "slow",
                    "-crf", "16", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv", str(video)],
                   check=True)
    return video


def sheet(stage: Path, cfg: dict, work: Path, times: list[float]) -> Path:
    from PIL import Image, ImageDraw
    tmp = work / "at"
    for f in tmp.glob("*.jpg") if tmp.exists() else []:
        f.unlink()
    asyncio.run(_film(stage, times, tmp, 4, (cfg["width"], cfg["height"])))
    cols = 3 if len(times) > 4 else len(times)
    rows = (len(times) + cols - 1) // cols
    W, H = 640, round(640 * cfg["height"] / cfg["width"])
    out = Image.new("RGB", (W * cols, H * rows), "white")
    d = ImageDraw.Draw(out)
    for i, t in enumerate(times):
        out.paste(Image.open(tmp / f"{i:05d}.jpg").resize((W, H), Image.LANCZOS), ((i % cols) * W, (i // cols) * H))
        d.text(((i % cols) * W + 8, (i // cols) * H + 6), f"{t:.2f}s", fill=(200, 0, 60))
    p = work / "at.png"
    out.save(p)
    return p


# ------------------------------------------------------------------ sound effects
def eleven_sfx(key: str, kind: str, spec: list, cache: Path) -> Path | None:
    out = cache / f"sfx-{kind}.mp3"
    if out.exists() and out.stat().st_size > 2000:
        return out
    prompt, secs = spec[0], max(0.5, float(spec[1]))
    req = urllib.request.Request("https://api.elevenlabs.io/v1/sound-generation?output_format=mp3_44100_128",
                                 data=json.dumps({"text": prompt, "duration_seconds": secs, "prompt_influence": 0.55}).encode(),
                                 headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            out.write_bytes(r.read())
        print(f"   sfx {kind}: ElevenLabs")
        return out
    except urllib.error.HTTPError as e:
        print(f"   sfx {kind}: ElevenLabs {e.code} {e.read()[:160].decode(errors='replace')}")
    except Exception as e:
        print(f"   sfx {kind}: ElevenLabs failed: {e}")
    return None


def decode(path: Path) -> np.ndarray:
    raw = subprocess.run([ffmpeg(), "-loglevel", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768


def _env(n, a, d):
    t = np.arange(n) / SR
    return np.minimum(t / max(a, 1e-4), 1.0) * np.exp(-np.maximum(t - a, 0) / d)


def _sweep(n, lo, hi, rng):
    """Noise through a low-pass that climbs from lo to hi Hz, differenced: an airy band that rises."""
    x = rng.standard_normal(n)
    a = 1 - np.exp(-2 * np.pi * np.geomspace(lo, hi, n) / SR)
    out, acc = np.zeros(n), 0.0
    for i in range(n):
        acc += a[i] * (x[i] - acc)
        out[i] = acc
    return np.diff(out, prepend=0) * 6


def synth_sfx(kind: str) -> np.ndarray:
    """Stand-ins for when there is no ElevenLabs key. Kinds not listed here fall back to a soft whoosh."""
    rng = np.random.default_rng(sum(map(ord, kind)))
    if kind == "tick":
        n = int(.06 * SR); t = np.arange(n) / SR
        return np.sin(2 * np.pi * 2400 * t) * _env(n, .0008, .012) * .5
    if kind == "click":
        n = int(.08 * SR); t = np.arange(n) / SR
        return (np.sin(2 * np.pi * 1700 * t) * _env(n, .0005, .01) + rng.standard_normal(n) * _env(n, .0003, .004) * .5) * .7
    if kind == "pop":
        n = int(.16 * SR); t = np.arange(n) / SR; f = 420 + 700 * np.exp(-t * 40)
        return np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(n, .002, .05) * .7
    if kind == "ding":
        n = int(1.4 * SR); t = np.arange(n) / SR
        return sum(a * np.sin(2 * np.pi * f * t) * _env(n, .002, d) for f, a, d in ((1318.5, .5, .5), (1975.5, .3, .35), (2637, .15, .2))) * .6
    if kind == "confetti":
        n = int(1.2 * SR); x = np.zeros(n)
        for _ in range(40):
            i = int(rng.uniform(0, .5) ** 1.8 * SR); m = int(.03 * SR)
            x[i:i + m] += rng.standard_normal(m) * _env(m, .0005, .006) * rng.uniform(.1, .4)
        return x + _sweep(n, 3000, 5000, rng) * _env(n, .005, .25) * .15
    if kind == "riser":
        n = int(1.75 * SR); t = np.arange(n) / SR; u = t / t[-1]
        return (np.sin(2 * np.pi * np.cumsum(220 * 2 ** (2 * u)) / SR) * .3 + _sweep(n, 400, 8000, rng) * .25) * u ** 1.6
    if kind == "shimmer":
        n = int(1.4 * SR); x = np.zeros(n); t = np.arange(n) / SR
        for k, f in enumerate((2637, 3136, 3520, 3951, 4699, 3520, 5274)):
            i = int(k * .07 * SR)
            x[i:] += np.sin(2 * np.pi * f * t[:n - i]) * _env(n - i, .002, .25) * .18
        return x
    if kind == "impact":
        n = int(2.4 * SR); t = np.arange(n) / SR
        boom = np.sin(2 * np.pi * np.cumsum(90 * np.exp(-t * 6) + 42) / SR) * _env(n, .003, .45)
        return boom * .8 + rng.standard_normal(n) * _env(n, .001, .05) * .3 + np.pad(synth_sfx("ding"), (0, n))[:n] * .5
    secs, lo, hi = {"whoosh_big": (.8, 300, 9000), "swoosh": (.9, 150, 1800)}.get(kind, (.55, 500, 6000))
    n = int(secs * SR); u = np.linspace(0, 1, n)
    x = _sweep(n, lo, hi, rng) * np.sin(np.pi * u ** 0.7) ** 2
    return x / (np.max(np.abs(x)) + 1e-9) * .6


def sfx_track(cfg: dict, key: str | None, cache: Path) -> np.ndarray:
    n = int((cfg["total"] + 1) * SR)
    out = np.zeros(n)
    clips = {}
    for kind, spec in cfg["sfx"].items():
        p = eleven_sfx(key, kind, spec, cache) if key else None
        clips[kind] = (decode(p), True) if p else (synth_sfx(kind), False)
    for at, kind in cfg["cues"]:
        sig, generated = clips[kind]
        sig = sig * cfg["sfx"][kind][2]
        if generated and np.max(np.abs(sig)) > 0:   # generated effects open with air: start where the sound does
            lead = int(np.argmax(np.abs(sig) > 0.02 * np.max(np.abs(sig))))
            sig = sig[max(0, lead - int(.01 * SR)):]
        i = int(at * SR); j = min(n, i + len(sig))
        out[i:j] += sig[: j - i]
    return out


# ------------------------------------------------------------------ music bed
def eleven_music(cfg: dict, key: str, cache: Path) -> Path | None:
    out = cache / "music.mp3"
    if out.exists() and out.stat().st_size > 20000:
        return out
    m = cfg["music"]
    plan = {"positive_global_styles": m["positive"], "negative_global_styles": m.get("negative", []),
            "sections": [{"section_name": name, "positive_local_styles": [style], "negative_local_styles": [],
                          "duration_ms": int(round((b - a) * 1000)), "lines": m.get("lyrics", {}).get(name, [])}
                         for name, a, b, style in m["sections"]]}
    bodies = [{"composition_plan": plan, "model_id": "music_v1"}]
    if m.get("prompt"):
        bodies.append({"prompt": m["prompt"], "music_length_ms": int(cfg["total"] * 1000), "model_id": "music_v1"})
    for body in bodies:
        req = urllib.request.Request("https://api.elevenlabs.io/v1/music?output_format=mp3_44100_192", data=json.dumps(body).encode(),
                                     headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                data = r.read()
            if len(data) > 20000:
                out.write_bytes(data)
                print(f"   music: Eleven Music ({'plan' if 'composition_plan' in body else 'prompt'}), {len(data) / 1e6:.1f} MB")
                return out
        except urllib.error.HTTPError as e:
            print(f"   music: Eleven Music {e.code} {e.read()[:200].decode(errors='replace')}")
        except Exception as e:
            print(f"   music: Eleven Music failed: {e}")
    return None


def synth_music(cfg: dict) -> np.ndarray:
    """A bright pop bed, I-V-vi-IV, following the config's sections: drums run in every section except intro,
    breakdown and ending; the last two seconds of the breakdown are a snare build; the ending opens on one big hit."""
    total, bpm, drop = cfg["total"], cfg["music"]["bpm"], cfg["music"]["drop"]
    secs = {name: (a, b) for name, a, b, _ in cfg["music"]["sections"]}
    quiet = [secs[k] for k in ("intro", "breakdown", "ending") if k in secs]
    hit = secs.get("ending", (total - 4, total))[0]
    build = (secs["breakdown"][1] - 1.9, secs["breakdown"][1]) if "breakdown" in secs else None
    n = int((total + 1) * SR)
    mix = np.zeros(n)
    beat = 60 / bpm
    grid0 = drop - 8 * beat

    def put(sig, at, g=1.0):
        i = int(at * SR)
        if i < 0:
            sig, i = sig[-i:], 0
        j = min(n, i + len(sig))
        if j > i:
            mix[i:j] += g * sig[: j - i]

    def tone(f, dur, a=.004, d=.3, bright=.35):
        m = int(dur * SR); t = np.arange(m) / SR
        return (np.sin(2 * np.pi * f * t) + bright * np.sin(4 * np.pi * f * t) + bright * .4 * np.sin(6 * np.pi * f * t)) * _env(m, a, d)

    def kick():
        m = int(.4 * SR); t = np.arange(m) / SR
        return np.sin(2 * np.pi * np.cumsum(150 * np.exp(-t * 22) + 48) / SR) * _env(m, .001, .16)

    rng = np.random.default_rng(3)
    clap = rng.standard_normal(int(.2 * SR)) * _env(int(.2 * SR), .002, .05)
    hat = np.diff(rng.standard_normal(int(.05 * SR)), prepend=0) * _env(int(.05 * SR), .0005, .012)
    E3 = 164.81
    chords = [(1, 5 / 4, 3 / 2), (3 / 2, 15 / 8, 9 / 4), (5 / 3, 2, 5 / 2), (4 / 3, 5 / 3, 2)]
    roots = [1, 3 / 4, 5 / 6, 2 / 3]
    drums_on = lambda t0: drop - .01 <= t0 < hit and not any(a <= t0 < b for a, b in quiet)
    nb = int((total - grid0) / beat) + 2
    for b in range(-2, nb):
        t0 = grid0 + b * beat
        if t0 > hit + 1:
            break
        bar = (b // 4) % 4
        ch = chords[bar]
        if drums_on(t0):
            put(kick(), t0, .9)
            if b % 2 == 1:
                put(clap, t0, .35)
            put(hat, t0 + beat / 2, .22)
            for e in range(2):
                put(tone(E3 / 2 * roots[bar], beat / 2 * .9, .003, .18, .6), t0 + e * beat / 2, .35)
        if build and build[0] <= t0 < build[1]:
            k = int((t0 - build[0]) / beat)
            for s in range(2 if k < 2 else 4):
                put(clap[: int(.08 * SR)], t0 + s * beat / (2 if k < 2 else 4), .12 + .06 * k)
        if t0 < hit:
            soft = "breakdown" in secs and secs["breakdown"][0] <= t0 < secs["breakdown"][1]
            for q in range(4):
                put(tone(E3 * 2 * ch[(b * 4 + q) % 3] * (2 if q == 3 else 1), beat / 4 * .95, .002, .07, .25), t0 + q * beat / 4,
                    (.16 if t0 < drop else .2) * (.7 if soft else 1))
            if drums_on(t0):
                for f in ch:
                    put(tone(E3 * f, beat * .45, .003, .12, .5), t0 + beat / 2, .07)
            if b % 4 == 0:
                for f in ch:
                    m = int(beat * 4.2 * SR); t = np.arange(m) / SR
                    pad = sum(np.sin(2 * np.pi * E3 * f * (1 + c) * t) for c in (-.003, 0, .003)) / 3
                    put(pad * np.minimum(t / .3, 1) * np.exp(-t / 3), t0, .09)
    for f in (1, 5 / 4, 3 / 2, 2, 5 / 2):
        put(tone(E3 * f, 4.5, .004, 1.5, .4), hit + .05, .12)
    put(tone(E3 / 2, 4.0, .004, 1.2, .8), hit + .05, .25)
    put(kick(), hit + .05, 1.0)
    # the intro opens up: a low-pass that climbs into the drop
    i1 = int(drop * SR)
    a = 1 - np.exp(-2 * np.pi * np.geomspace(500, 12000, i1) / SR)
    acc = 0.0
    for i in range(i1):
        acc += a[i] * (mix[i] - acc)
        mix[i] = acc
    duck = np.ones(n)                       # sidechain: dip after each kick
    for b in range(nb):
        t0 = grid0 + b * beat
        if drums_on(t0):
            i = int(t0 * SR); j = min(n, i + int(.2 * SR))
            duck[i:j] *= np.linspace(.45, 1, j - i) ** .6
    mix *= duck
    return mix / (np.max(np.abs(mix)) + 1e-9) * .6


def write_wav(path: Path, sig: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(sig, -1, 1) * 32767).astype("<i2").tobytes())


# ------------------------------------------------------------------ mux
def mux(cfg: dict, video: Path, bed: Path, sfx: Path, final: Path, eleven: bool) -> None:
    total = cfg["total"]
    subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-i", str(video), "-i", str(bed), "-i", str(sfx), "-filter_complex",
                    f"[1:a]aformat=sample_rates={SR}:channel_layouts=stereo,apad=whole_dur={total},atrim=0:{total},"
                    f"afade=t=out:st={total - 2.2:.2f}:d=2.2,volume={0.8 if eleven else 0.9}[m];"
                    f"[2:a]aformat=sample_rates={SR}:channel_layouts=stereo,volume=0.9[s];"
                    "[m][s]amix=inputs=2:normalize=0,alimiter=limit=0.95,loudnorm=I=-14:TP=-1.5:LRA=9[a]",
                    "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                    "-t", f"{total}", "-movflags", "+faststart", str(final)], check=True)


def mux_track(cfg: dict, video: Path, track: Path, final: Path) -> None:
    subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-i", str(video), "-i", str(track), "-map", "0:v", "-map", "1:a:0",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", f"{cfg['total']}", "-movflags", "+faststart",
                    str(final)], check=True)


def contact(final: Path, cfg: dict) -> Path:
    p = final.with_name(final.stem + "-contact.png")
    subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-i", str(final), "-vf", f"fps=1/{cfg['total'] / 15:.3f},scale=320:-1,tile=5x3",
                    "-frames:v", "1", str(p)], check=True)
    return p


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", type=Path, required=True)
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("out"))
    ap.add_argument("--name", default=None, help="output file name without extension (default: config 'name')")
    ap.add_argument("--at", help="comma-separated seconds: a contact sheet of just those moments")
    ap.add_argument("--audio-only", action="store_true")
    ap.add_argument("--audio-from", type=Path, help="use this file's audio as the soundtrack instead of composing one")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    cfg = json.loads(a.config.read_text(encoding="utf-8"))
    cfg.setdefault("fps", 30); cfg.setdefault("width", 1920); cfg.setdefault("height", 1080)
    stage = a.stage.resolve()
    work = a.out / "work"
    work.mkdir(parents=True, exist_ok=True)
    if a.at:
        print(sheet(stage, cfg, work, [float(x) for x in a.at.split(",")]))
        return
    name = a.name or cfg.get("name", "ad")
    video = work / "picture.mp4"
    if not a.audio_only or not video.exists():
        video = film_picture(stage, cfg, work, a.workers)
        print(f"== picture {video}")
    if a.audio_from:
        final = a.out / f"{name}-{a.audio_from.stem}-audio.mp4"
        mux_track(cfg, video, a.audio_from, final)
    else:
        cache = a.out / "audio"
        cache.mkdir(parents=True, exist_ok=True)
        key = api_key()
        if not key:
            print("   no ELEVENLABS_API_KEY: synthesising the bed and the effects")
        bed = eleven_music(cfg, key, cache) if key else None
        if bed is None:
            bed = cache / "music-synth.wav"
            write_wav(bed, synth_music(cfg))
        sfx = cache / "sfx.wav"
        write_wav(sfx, sfx_track(cfg, key, cache))
        final = a.out / f"{name}.mp4"
        mux(cfg, video, bed, sfx, final, bed.suffix == ".mp3")
    print(f"== {final} ({final.stat().st_size / 1e6:.1f} MB); sheet {contact(final, cfg)}")


if __name__ == "__main__":
    main()
