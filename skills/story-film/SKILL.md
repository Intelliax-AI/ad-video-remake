---
name: story-film
description: "Make the narrated story opening of a brand film (about 40 s, 16:9): a documentary cold open where a narrator says what people get wrong about the greats, archival photos of them are pinned to a cutting mat with typed captions, then we meet one character in dark cinematic stock footage (doom-scrolling a phone, failing at the moment that matters) and the brand line lands on the logo. Voice, music and effects from ElevenLabs; photos from Wikimedia Commons; footage from Pexels; drawn and filmed frame by frame from one config. Use when the user wants 'a story ad', 'a documentary-style brand video', 'an intro like Fanout's', 'a narrated cold open', 'meet <character> ... <brand> changes that', or to redo, re-voice or rebrand one made this way."
---

# Story film (the narrated cold open)

A 40-second opening in two acts and a sting, all driven by one `story.json`:

1. **The greats** (0 to about 22 s, on a dark cutting mat): "People think the best <role>s were just born smarter.
   But look at how they actually learned." Archival photos cut in one after another, each with a typed caption; the
   papers or artefacts they made fan out; then every picture at once, joined by drawn lines, under
   "It took them *years.*"
2. **The character** (about 22 to 39 s, dark stock footage): "Meet <name>. He's good, but wants to be great." An eye
   close-up, a silhouette at a desk, a phone full of hype he bookmarks and never uses, then the moment that matters
   (an interview question on a video call) where his camera freezes, the colour drains, and "he *freezes.*"
3. **The line** (about 39 to 44 s): "<Brand> changes that." The mark draws itself on the brand's ground colour, a riser,
   an impact, a sting, the tagline.

The worked example is Skillmaxing's (`templates/story.json`); its render is in the repo's `examples/skillmaxing-story/`.

| path | what it is |
| --- | --- |
| `scripts/fetch_media.py` | Commons photos (with licences), paper first pages, Pexels clips cut to 30 fps frames; `search` and `probe` finders |
| `scripts/build.py` | narration with word timings, the timeline, filming the stage in parallel, music, effects, mix, mux, checks |
| `templates/stage.html` | the scene engine: `mat`, `clip`, `phone`, `call`, `logo`, all configured from `story.json` |
| `templates/story.json` | the Skillmaxing opening, complete: script, brand, media, every scene and caption |
| `reference/techniques.md` | what took iteration. Read it before changing the engine or the timings |

Setup, once: `pip install playwright numpy pillow imageio-ffmpeg scipy pymupdf` and `python -m playwright install chromium`.
`ELEVENLABS_API_KEY` in the environment or a `.env` / `.env.local` up the tree (the narration needs it; look for it
before saying it is missing). Work in a folder outside the repo; never commit media or renders.

## 1. Write the story

Get the facts first: brand name and how it is said aloud, domain, colours, logo as SVG, tagline, and who it is for.
Then fill four blanks, which is the whole film:

- **The myth**, for the brand's field: "the best engineers / designers / founders were just born smarter".
- **How the greats really learned**, as 3 or 4 short verbs ("went deep", "read the papers", "rebuilt systems",
  "argued at whiteboards"), each one something a photo can show.
- **The character** and his tell: what he does instead (saves roadmaps, watches at 2x, follows every launch).
- **The moment he fails**: a question he should be able to answer, asked where it counts.

Keep lines short (the example's twelve lines total 44 s at `speed` 0.95). Write numbers and the brand the way they
should be spoken ("two x", not "2x"). Show the script to the user briefly, then build.

## 2. Find the pictures

- **Photos of the greats**: `python scripts/fetch_media.py search "<person> <era or object>"`. Prefer public domain
  and CC BY/BY-SA; one iconic picture per person, doing the thing the line says (Hamilton beside the code, a first
  server rack). Old photos read best in black and white (`"bw": true`).
- **Artefacts**: first pages of the papers or documents they wrote, from the authors' own PDFs (`media.papers`).
- **The character**: Pexels clips, dark and warm or blue-lit, faces half in shadow. Find ids with a web search limited
  to pexels.com. A shoot is uploaded as consecutive ids, so `python scripts/fetch_media.py probe <id> --span 40`
  shows the neighbours: pick clips of **one actor** where his face is seen, and use faceless shots (an eye, a
  silhouette, a hand on a phone) to cover the gaps. Note in the handover if two actors play him.

List them in `story.json` under `media` (`photos`: key to Commons title, `papers`: key to PDF URL, `clips`: name to
`[pexels id, in-point seconds, length seconds]`), then `python scripts/fetch_media.py --work <dir>`. It writes
`media/CREDITS.md`: CC BY and BY-SA photos need that attribution in the video's description.

## 3. Configure the scenes

Copy `templates/story.json` into the work folder and edit it. Times are strings resolved against the narration:
`"n3"` (line n3 starts), `"n3+1.2"`, `"n9@roadmap"` (the moment that word is said), `"n6.end+1.0"`, `"END"`, or plain
seconds. Hang every cut and caption off a line or a word, never off absolute seconds, so a re-voiced line moves
everything with it.

- `mat`: `shots` (a photo with its centre, height and tilt, or a `papers` fan), `captions` (`of` a shot plus `pos`:
  `above`, `below`, `right`, `br`; or absolute `x`, `y`), and `wall` (the finale and its big line).
- `clip`: one stock clip with a slow `zoom` and its captions. Portrait clips are framed on a blurred copy of
  themselves automatically.
- `phone`: posts (`media`: `tags`, `video`, `launch`), with `save_at`, `speed_at`, `launch_at` and `flicks`.
- `call`: the interview. `ask_at` (her question types in), `freeze_at` (his tile freezes and the frame drains).
- `logo`: `from`, `hit` (the impact and sting), `to`. In `brand.mark_svg`, give the parts that should rise
  `class="grow"` and the strokes that should ink on `class="draw"`.

Captions: `[word]` is the accent colour, `{word}` the second accent, `\n` breaks a line. A caption lives in one scene;
to keep one on screen across a cut, repeat it in the next scene with `"cps": 999, "tick": 0`.

## 4. Check, then render

```
python scripts/build.py --work <dir> --at 0.6,5.2,8,13,19,21.5,25.5,28.8,36.4,40.5,43
```

generates (and caches) the narration, and writes `out/at.png`. Read it. Captions must not run off the frame or sit
on faces; each photo must be on screen while its line is said. Then:

```
python scripts/build.py --work <dir> --verify
```

About 2.5 minutes for 44 s at 60 fps. It prints the loudness (aim for -14 LUFS), the biggest frame-to-frame changes
(photo cuts are meant to be hard, 40 to 90; anything else over 35 is a bug), and with `--verify` a transcript of the
finished mix plus any scripted word that could not be heard.

## 5. Deliver

Give the path (`<dir>/out/<title>.mp4`) and open it for the user. Say what the character is played by (and whether
it is one actor), where the photo credits are, and what is invented (post handles, the interviewer's name). For
changes: edit `story.json` or a line, rerun with `--at` on the affected seconds, then rebuild. `--audio-only` remixes
the sound without refilming.

This opening ends on the brand line. To continue into the product (a narrated tour, a payoff where the character
succeeds), build that part as its own stage and cut it on at the logo's hit.
