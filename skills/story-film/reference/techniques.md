# What took iteration

## Story and voice

- **Lines drive everything.** The narration is generated first, one mp3 per line with ElevenLabs' `with-timestamps`
  endpoint, and the word start times go into `timeline.json`. Every scene and caption is written relative to a line
  or a word, so re-voicing a line or changing its speed moves the picture with it. Absolute seconds went stale on
  every regeneration.
- **Continuity between separately generated lines**: pass `previous_text` and `next_text`. Without them each line
  starts and ends like a fresh read.
- **Write for the ear.** "two x" not "2x"; the brand as it should be said. The transcript check splits made-up words
  ("Skill maxing"); that is not a pronunciation fault, and `--verify` ignores spacing.
- A calm documentary voice suits this form (Eric, `cjVigY5qzO86Huf0OWal`, at speed 0.95); an energetic ad voice
  fights the pictures.

## The mat

- Cut photos **hard**, on the words: a 0.35 s settle (scale 1.07 to 1, ease-out) and then a slow drift. Crossfades
  here read as slideshow.
- One caption per photo, typed at about 30 characters a second with a block cursor, the key words in the accent
  colour. Give every caption an end (`to`) at the next cut, or old lines pile up under new photos.
- Place captions against the photo (`of`/`pos`), not at fixed coordinates: photos differ in shape.
- The finale collage is what sells "years": every picture at once, scaled in from 1.55, then accent lines drawn
  between neighbours and a dot on each, under one big typed line on a dark band.
- Low-resolution archival photos are fine at 480 to 600 px tall with grain on top. Upscaling them to full screen is not.

## Footage

- Pexels has no open search API, but `https://www.pexels.com/download/video/<id>/` redirects to the largest file,
  and HTTP range requests work, so ffmpeg can pull a preview frame straight from that URL.
- **One face.** A viewer notices when the character changes face. Shoots are uploaded as consecutive ids; probe the
  neighbours of a good clip for more of the same actor (`fetch_media.py probe`). Cover gaps with faceless shots.
- Cut clips to 30 fps JPEG frames once; the stage swaps `<img>` sources and waits for `decode()` before each
  screenshot. Seeking `<video>` in headless Chromium is not frame-accurate.
- Portrait clips go on a blurred, darkened copy of themselves; letterboxing them looks like a mistake.

## The freeze

The beat that makes the story: the call runs normally, the question types in, then on "he freezes" his tile holds
one frame, the camera pushes into it (scale 2.5), everything else on the call fades to black, the colour drains, a
few frames tear (hue shift and a horizontal jitter), and a tape-stop effect cuts the music dead. The scene must fade
out by itself before it ends. Ending the scene while it is still visible snaps to black and reads as a glitch.

## Sound

- The underscore is composed once for the story (ElevenLabs music, a prompt with a slow build, no drums until the
  last third) and **cut dead at the freeze**. ElevenLabs often opens a piece with several seconds of silence:
  `build.py` skips to where the sound starts.
- After the freeze: silence, the brand line, a riser into an impact, and a sting. That silence is what makes the
  line land.
- Duck the music under the voice (about 60 %), keep effects at about a third of full scale, loudness-normalise to
  -14 LUFS.

## Rendering and checking

- `seek(t)` is pure: every style from `t`, no CSS transitions, no timers. Six Chromium processes film interleaved
  ranges at 60 fps into H.264 segments that are concatenated.
- The engine hides scenes with `display:none`; overlapping scenes fade with explicit opacity ramps.
- Measure, don't eyeball: the mean frame-to-frame change (160x90 grey) finds accidental hard cuts (a scene ending
  before its fade, a black frame between two scenes). The photo cuts are the only ones that should score high.
- Transcribe the finished mix (`--verify`) to prove every line survived the ducking and the effects.
- Contact sheets of chosen seconds (`--at`) before every full render: captions off the frame, a caption left
  over from the last shot, and a photo shown under the wrong line all show up there.
