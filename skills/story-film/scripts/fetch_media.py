"""Pictures for a story film: archival photos, paper first pages, stock clips cut to frames. Plus two finders.

    python fetch_media.py --work <dir>                         # fetch everything story.json's "media" lists
    python fetch_media.py search "Grace Hopper UNIVAC"          # Wikimedia Commons: titles, sizes, licences
    python fetch_media.py probe 8070886 --span 40 --out sheet.png
        # a Pexels shoot is uploaded as consecutive ids: preview the videos around one clip to find
        # more shots of the same actor, so the character has one face

Writes <dir>/media/photos, papers, video/<clip>/NNNN.jpg (30 fps), manifest.json (what the stage reads) and
CREDITS.md (attribution for the description or end card). Cached: delete a file to fetch it again.
Needs: pip install pillow imageio-ffmpeg pymupdf
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

UA = {"User-Agent": "story-film/1.0 (Claude Code skill; https://github.com/Intelliax-AI/ad-video-remake)"}
BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
CLIP_FPS = 30


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def get(url: str, headers=UA, timeout=120) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout).read()


def commons(params: dict) -> dict:
    q = urllib.parse.urlencode({"action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": 1600, **params})
    return json.loads(get("https://commons.wikimedia.org/w/api.php?" + q))


def search(query: str, n: int = 8) -> None:
    pages = commons({"generator": "search", "gsrsearch": query, "gsrnamespace": 6, "gsrlimit": n}).get("query", {}).get("pages", {})
    for p in sorted(pages.values(), key=lambda p: p["index"]):
        ii = p["imageinfo"][0]; lic = ii.get("extmetadata", {}).get("LicenseShortName", {}).get("value")
        print(f"{p['title']}  |  {ii['width']}x{ii['height']}  |  {lic}".encode("ascii", "replace").decode())


def pexels_url(vid: int) -> str | None:
    """Pexels' download link redirects to the clip's largest rendition; photos redirect to images.pexels.com."""
    req = urllib.request.Request(f"https://www.pexels.com/download/video/{vid}/", headers=BROWSER, method="HEAD")
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    try:
        urllib.request.build_opener(NoRedirect).open(req, timeout=30)
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location", "")
        return loc if "video-files" in loc else None
    except Exception:
        return None
    return None


def probe(vid: int, span: int, out: Path) -> None:
    from PIL import Image, ImageDraw
    ids = range(vid - span, vid + span + 1)
    with ThreadPoolExecutor(16) as ex:
        urls = dict(zip(ids, ex.map(pexels_url, ids)))
    found = [(i, u) for i, u in urls.items() if u]
    print(f"{len(found)} videos between {ids[0]} and {ids[-1]}")
    tmp = out.parent / f"probe_{vid}"; tmp.mkdir(parents=True, exist_ok=True)
    def grab(iu):
        i, u = iu; f = tmp / f"{i}.jpg"
        subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-user_agent", BROWSER["User-Agent"], "-ss", "3", "-i", u, "-frames:v", "1", "-update", "1",
                        "-vf", "scale=480:270:force_original_aspect_ratio=decrease", str(f)])
        return i, f
    with ThreadPoolExecutor(8) as ex:
        shots = [(i, f) for i, f in ex.map(grab, found) if f.exists()]
    cols = 6; rows = -(-len(shots) // cols) or 1
    sheet = Image.new("RGB", (480 * cols, 270 * rows), "white")
    for k, (i, f) in enumerate(shots):
        im = Image.open(f).convert("RGB"); d = ImageDraw.Draw(im); d.rectangle([0, 0, 90, 16], fill="black"); d.text((3, 2), str(i), fill="yellow")
        sheet.paste(im, ((k % cols) * 480, (k // cols) * 270))
    sheet.save(out); print(f"sheet: {out}  (ids are printed on each tile; use them in story.json media.clips)")


def fetch(work: Path) -> None:
    story = json.loads((work / "story.json").read_text(encoding="utf-8"))
    media = story.get("media", {}); root = work / "media"
    man_path = root / "manifest.json"
    man = json.loads(man_path.read_text()) if man_path.exists() else {}
    man.setdefault("photo_files", {}); man.setdefault("frames", {}); man.setdefault("tall", {}); man.setdefault("credits", {})

    pdir = root / "photos"; pdir.mkdir(parents=True, exist_ok=True)
    for key, title in media.get("photos", {}).items():
        if key in man["photo_files"] and (pdir / man["photo_files"][key]).exists():
            continue
        page = next(iter(commons({"titles": title})["query"]["pages"].values()))
        if "imageinfo" not in page:
            sys.exit(f"photo {key}: no such file on Commons: {title} (try: fetch_media.py search \"...\")")
        ii = page["imageinfo"][0]; meta = ii["extmetadata"]; src = ii.get("thumburl") or ii["url"]
        ext = ".png" if src.lower().endswith(".png") else ".jpg"
        (pdir / f"{key}{ext}").write_bytes(get(src))
        strip = lambda s: re.sub("<[^>]+>", "", s or "").strip()
        man["photo_files"][key] = f"{key}{ext}"
        man["credits"][key] = {"what": title[5:], "page": ii["descriptionurl"], "license": meta.get("LicenseShortName", {}).get("value"), "author": strip(meta.get("Artist", {}).get("value"))[:120]}
        print(f"   photo {key}: {man['credits'][key]['license']}")
        time.sleep(0.4)

    if media.get("papers"):
        import fitz  # PyMuPDF
        adir = root / "papers"; adir.mkdir(parents=True, exist_ok=True)
        for key, url in media["papers"].items():
            if not (adir / f"{key}.png").exists():
                fitz.open(stream=get(url, BROWSER), filetype="pdf")[0].get_pixmap(dpi=150).save(str(adir / f"{key}.png"))
                man["credits"]["paper:" + key] = {"what": "first page", "page": url, "license": "quoted for commentary", "author": ""}
                print(f"   paper {key}")

    raw = root / "raw"; raw.mkdir(parents=True, exist_ok=True)
    for name, (vid, t0, secs) in media.get("clips", {}).items():
        out = root / "video" / name
        if out.exists() and any(out.glob("*.jpg")) and name in man["frames"]:
            continue
        src = raw / f"{vid}.mp4"
        if not src.exists():
            src.write_bytes(get(f"https://www.pexels.com/download/video/{vid}/", BROWSER, timeout=900))
        dims = re.search(r"(\d{3,5})x(\d{3,5})", subprocess.run([ffmpeg(), "-i", str(src)], capture_output=True, text=True).stderr)
        w, h = int(dims.group(1)), int(dims.group(2))
        out.mkdir(parents=True, exist_ok=True)
        vf = f"fps={CLIP_FPS}," + ("scale=1920:-2,crop='min(iw,1920)':'min(ih,1080)'" if w >= h else "scale=-2:1080")
        subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-ss", str(t0), "-i", str(src), "-t", str(secs), "-vf", vf, "-q:v", "3", str(out / "%04d.jpg")], check=True)
        man["frames"][name] = len(list(out.glob("*.jpg"))); man["tall"][name] = h > w
        man["credits"]["clip:" + name] = {"what": f"Pexels video {vid}", "page": f"https://www.pexels.com/video/{vid}/", "license": "Pexels licence (no attribution required)", "author": ""}
        print(f"   clip {name}: {man['frames'][name]} frames{' (portrait)' if h > w else ''}")

    man_path.write_text(json.dumps(man, indent=1))
    lines = ["# Credits", "", "| what | author | licence | source |", "| --- | --- | --- | --- |"]
    lines += [f"| {c['what']} | {c['author'] or '-'} | {c['license']} | {c['page']} |" for c in man["credits"].values()]
    (root / "CREDITS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"== media ready: {root} (credits in CREDITS.md)")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("-n", type=int, default=8)
    p = sub.add_parser("probe"); p.add_argument("id", type=int); p.add_argument("--span", type=int, default=30); p.add_argument("--out", default="probe.png")
    ap.add_argument("--work", default=".")
    a = ap.parse_args()
    if a.cmd == "search":
        search(a.query, a.n)
    elif a.cmd == "probe":
        probe(a.id, a.span, Path(a.out).resolve())
    else:
        fetch(Path(a.work).resolve())


if __name__ == "__main__":
    main()
