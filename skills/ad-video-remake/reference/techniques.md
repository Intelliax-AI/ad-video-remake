# Techniques

The parts of `templates/stage.html` and `scripts/build.py` that took more than one attempt, and why they are the
way they are. Line references are to functions in the template.

## Filming

- **Pure `render(t)`.** `build.py` opens six pages and gives each every sixth frame, so a page renders t=8.3 and
  then t=11.0. Anything carried between calls (a "last position", an element left visible) leaks into the wrong
  frame. Compute everything from `t`.
- **`display:none` for layers.** `visibility` is inherited, but a child that sets `visibility:visible` (as `css()`
  does for anything with opacity above zero) shows even inside a hidden parent. That is how words from one scene
  turn up in another. `show(layer, on)` toggles `display`.
- **Measure once, in `ready`.** `Line.measure()` reads `offsetWidth` after `document.fonts.ready`; widths ignore
  transforms, so scaling words later does not disturb the layout. Elements must be displayed when measured, which
  is why layers start visible and `render(0)` runs after measuring.
- **Colour range.** Screenshots are full-range JPEG. Encode with
  `scale=in_range=pc:out_range=tv:out_color_matrix=bt709,format=yuv420p` and tag bt709, or the file comes out
  `yuvj420p` and some players wash it out.
- **Speed.** 990 frames at 1920x1080 take about 20 s with six pages. Check single moments with `--at`, which
  films only those.

## Motion

- **Word blur-in** (`ws`): opacity over the first half, blur 16 px to 0, 44 px slide from the right, scale 1.08 to 1,
  `out5` easing over 0.42 s; out is `in2` over 0.24 s with blur and a slight shrink. This one move is most of the
  "premium SaaS ad" look.
- **Re-centring lines** (`Line.place`): each item has a weight `w` from 0 to 1 that eases in as it arrives; the row's
  width is the weighted sum, so earlier words glide aside to make room instead of jumping.
- **Camera push into an element**: set `transform-origin` to the element's centre F, then
  `translate(centre - F) scale(z)`. F maps to the screen centre, and at z=1 with F at the centre nothing moves, so
  the push can start from rest.
- **Cursor**: an SVG pointing hand with its hotspot at the fingertip (`HOT`). A click is a 0.09 s scale dip
  (`press`). When the cursor works inside a tilted 3D window, make it a child of that window so it tilts with it;
  a screen-space cursor cannot line up with a perspective-transformed target.
- **Morph handovers** (a blurred sweep that becomes a progress bar, a button that becomes a sparkle): the outgoing
  element's last keyframe must equal the incoming element's first frame exactly (position, size, radius), and one
  of them must disappear on the same frame the other appears. Otherwise there is a frame with two of it.
- **Count-up**: interpolate the value with keyframes that slow near the end (`out` easing between 63, 90, 98, 100),
  round it, and right-align the number to the end of the bar.
- **Confetti**: about 90 pieces from a seeded PRNG (the same every render), closed-form motion with drag
  (`v(1 - e^{-kt})/k`) plus gravity, a flip made by scaling x with `cos`, and a few large blurred pieces in front
  for depth.
- **Sparkle trail**: sample the sparkle's own position function at `t - i * 0.011` and stroke segments that thin and
  fade with age, on a blurred canvas. Skip segments shorter than 1.5 px: once the sparkle rests, zero-length round
  caps pile up into a blot.
- **Logo lockup**: the mark lands (bars `scaleY` with overshoot, then the arrow draws with `stroke-dashoffset`), then
  slides left while the wordmark reveals with a clip-path. The wordmark's x must follow the mark's current x, or the
  two overlap mid-slide.

## The phone ring (the "tunnel" shot)

The reference shows four phones making a closed square ring round the words, like the walls of a tunnel seen from
inside: each phone lies flat on its wall, its top (status bar and notch) at the far end facing in, its body running
past the edge of the frame. The ring turns slowly while the camera drifts forward.

- Container: `perspective: 1000px`, origin at the screen centre; inner group `transform-style: preserve-3d`.
- Each phone: `rotateZ(wall) translateY(-R) translateZ(DEPTH) rotateX(-90deg) rotateZ(180deg)`.
  `rotateX(-90deg)` lays it on the wall facing the axis; the `rotateZ(180deg)` first puts its top at the far end.
- Only the top of each phone is ever in shot, so **build only the top slice** (1000 x 900, rounded top corners). A
  full-length phone would cross the camera plane (z > perspective), which CSS 3D renders badly.
- Numbers used: R 300 for the top and bottom walls, 500 for the sides (16:9), DEPTH 200, so the far edges sit at
  z = -250 (80% scale) and the near edges at z = 650, well off frame. The opening is then about 800 x 480 px:
  keep the words inside it (64 px type).
- Enter: each phone's R eases from 3.2x to 1x, staggered 0.08 s, while the ring turns from -55 to -12 degrees. Hold:
  turn -12 to +12 and push forward 140 px. Exit: R to 2.6x, turn to +50, blur, fade.
- Screens are drawn HTML at 400 px wide scaled by 2.4 (`.ui`): status bar, notch, a header and one strong element
  (a video player, a heading and paragraph, quiz options, chat bubbles). Big type reads even at the tunnel's angle.

## Drawn content instead of screenshots

Screenshots of a real site look muddy and busy at video scale, and users notice. The template draws instead:
- `ART`: small diagrams in a 320 x 180 viewBox (a hash ring, prefill and decode tokens, client to server to cache
  to database, a latency histogram with a p99 tail, a mixture-of-experts router, async lanes, a hot partition,
  agent memory), each with its own gradient ids (`svg()` numbers them). Use them as card art, list thumbnails and
  phone figures. Add new ones in the same style for a new brand.
- Windows (`windowHTML`): a sidebar with the brand mark, nav, a header with a user, tabs, search, and a body (a grid
  of cards, a list of rows, or course cards).
- Everything uses the brand's palette, one type family, 1.5-2.5 px strokes, generous radii and soft blue shadows.

## Sound

- Measure the reference: per-second loudness (dB), onsets, tempo. In the example: -20 dB intro to 3.2 s, -15 to -18
  body, a dip to about -28 at 26-27 s, the hit at 28 s, fade out by 31 s. Match that shape, not the notes.
- Cues sit on visible events, a few frames early for whooshes. Generated effects start with air, so `build.py` trims
  each to where its sound begins.
- Eleven Music takes a `composition_plan`: global positive and negative styles, and sections with `section_name`,
  `positive_local_styles`, `duration_ms` and `lines` (lyrics). Section boundaries at the picture's hit points are
  what make the drop land on the cut. `build.py` falls back to a plain prompt with the timings written out.
- Mix: bed under effects, a limiter, `loudnorm` to -14 LUFS / -1.5 dBTP for social.
- The reference's audio is licensed music: compose to its structure by default. Only mux it (`--audio-from`) when
  the user asks, as a separate file, with a one-line licence warning.
