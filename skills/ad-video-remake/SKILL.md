---
name: ad-video-remake
description: "Remake a reference ad or product launch video (usually a YouTube link) for another brand: same timeline, same motion and animation style, same sound structure, with the brand's own name and content. Draws every shot in an HTML stage, films it frame by frame with Playwright, and scores it with ElevenLabs music and sound effects (or synthesised stand-ins). Use when the user shares a video and asks for 'the same video / same animation / same sound for <brand>', a 'launch video', 'promo video', 'product ad', 'motion graphics ad', 'explainer like this', or asks to redo, retime or rebrand one made this way."
---

# Ad video remake

Turn a reference ad into the user's own: the same beats at the same seconds, the same kind of motion, a soundtrack
with the same shape, but their brand, their product and their facts. The result is a 1080p MP4 (16:9 by default)
built from a single HTML file, so every shot can be tweaked and re-rendered in about 30 seconds.

Everything the skill needs is next to this file:

| path | what it is |
| --- | --- |
| `scripts/analyze_reference.py` | downloads the reference; contact sheets, tempo, onsets, per-second loudness, transcript |
| `scripts/build.py` | films a stage into frames, scores it, muxes; `--at` for quick contact sheets |
| `templates/stage.html` | a complete worked example (the Skillmaxing launch ad, 33 s, nine scenes) with every helper you need |
| `templates/config.json` | that example's timing: sound cues, effect prompts, music sections and lyrics |
| `reference/techniques.md` | the details that took iteration to get right. Read it before building a stage |

Setup, once: `pip install playwright numpy pillow imageio-ffmpeg yt-dlp` and `python -m playwright install chromium`
(`faster-whisper` optional). Work in a scratch or `out/` folder; never commit the reference video.

## 1. Take the reference apart

```
python scripts/analyze_reference.py "<url>" --out <work>/ref
```

Read **every** `sheet_NN.png` (12 tiles each, 0.5 s per tile, left to right). For anything with complex motion
(3D moves, a ring of devices, a morph) take a closer look before building it:
`--range 5.9-10.3 --fps 4`, and pull a full-size still with ffmpeg if a layout is unclear. Getting a shot's geometry
wrong is the most expensive mistake, so look properly the first time (a phone "tunnel" is a closed ring of phones
lying on the walls of a tunnel, not phones scattered in 3D).

From `report.json` note: duration, whether there is narration or only music (the transcript tells you; lyrics
are not narration), tempo, where the drop is, where it goes quiet, and the loudness per second. Those numbers become
the sound plan.

## 2. Map the beats

Write a table: time range, what the reference shows, what ours shows. Keep **the same seconds** for every beat,
so the sound structure (and the reference audio, if the user insists on it) lands on our picture. Swap every piece
of their content for the brand's real content at the same weight: their headline word for ours, their app screens
for ours, their feature button for the brand's feature, their logo sting for the brand's mark.

Pull the brand before writing copy: name and domain, colours, fonts, logo (SVG), and real product facts. Numbers
(lesson counts, users, prices) come from the brand's own site or repo, never guessed. If the brand's copy is
ambiguous, check it rather than inventing it. Show the user the table briefly, then build; do not wait for sign-off
unless something is genuinely theirs to decide.

## 3. Build the stage

Copy `templates/stage.html` (and `templates/fonts/`) into the work folder and rewrite its scenes. Keep the helpers:
easing (`E`, `P`, `K` keyframes), `ws()` word blur-in and out, `Line` (a row that re-centres as words arrive),
`css()`, the cursor, `card()`, the window chrome, the `ART` diagram library, the phone ring, the confetti, the sparkle
trail and the logo lockup. Each scene is a function of `t` that shows or hides its own layer.

Rules that are not negotiable (why: `reference/techniques.md`):
- `render(t)` is **pure**: every value from `t`, no transitions, no timers, no state carried between calls. Frames
  are filmed out of order by several pages at once.
- Hide a scene's layer with `display:none`, never `visibility` (a child set to visible shows through a hidden parent).
- **Draw everything.** No screenshots of the brand's website or app. Build screens, windows, cards and diagrams in
  HTML/SVG in the brand's palette, the way the folder and the phone screens are built in the template. Users have
  rejected screenshots as looking bad in the video.
- Measure text in `window.ready`, after `document.fonts.ready`.
- A handover between two scenes must match on the frame where it happens (same size, same place), or the eye sees
  two of something.

Check as you go, scene by scene:

```
python scripts/build.py --stage <work>/stage.html --config <work>/config.json --out <work>/out --at 0.3,1.5,3.4,4.6,5.1
```

and read the sheet. Compare against the reference sheet at the same seconds. When every scene looks right, sheet the
**handovers** (the last and first frames of each pair of scenes); that is where most bugs hide.

## 4. Score it

Put the sound plan in `config.json`: `cues` (seconds and an effect kind, on every visible hit: a word landing, a
click, a pop, a whoosh on each camera move, a riser under a count-up, a chime and confetti on success, a shimmer
on a sparkle, an impact on the logo), `sfx` (an ElevenLabs prompt, seconds and mix level per kind), and `music`
(bpm and drop from the report, sections matching the reference's shape: quiet intro, drop, body, breakdown, final hit
and ring-out, plus original lyrics if the reference has vocals).

The reference's own soundtrack is almost always licensed music. Do not lift it by default: compose the bed to the
same structure instead, and say so in one line. If the user explicitly asks for the reference audio anyway, it is
their call: make it a **separate** file with `--audio-from <ref.mp4>` (keep the composed version too), and tell them
once, briefly, that they need a licence before publishing (Content ID will mute or claim it).

ElevenLabs: the key comes from `ELEVENLABS_API_KEY` or a `.env` / `.env.local` up the tree. Look for it before
saying it is missing; if it is missing, finish with the synthesised stand-ins and tell the user exactly where to put
the key and the one command to rerun (`--audio-only`). Results are cached, so reruns cost nothing.

Narration is optional: add a voice only if the reference has one or the user asks.

## 5. Render and deliver

```
python scripts/build.py --stage <work>/stage.html --config <work>/config.json --out <work>/out
```

Around 30 s for 33 s of 1080p with six workers. Then check: frame count, duration, `yuv420p (tv, bt709)`,
loudness about -14 LUFS, and the per-second loudness against the reference's. Read the contact sheet.

Give the user the path, and open it for them in a browser (`file:///...mp4` in Chrome or Edge): the default Windows
player can fail silently. Mention what was swapped for what, what the sound is, and anything left for them to do.

When they ask for changes, edit the stage, re-sheet the affected seconds with `--at`, and rebuild.
