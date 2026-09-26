# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A hover-revealed Conky panel pinned to the right edge of the screen: weather,
CPU/RAM ring gauges, network rates, battery, an updates list and a power bar.

**It is a companion to Conky-Calendar-Extra's modernized widget, and must not
duplicate it.** That widget owns the clock, the calendar rings (weekday, day,
month, week), the `/` and `/home` dials, the GPU dial and the per-core CPU
temperature gauges. Those were all removed from here for that reason — along
with their samplers, which is why the panel no longer calls `conky_parse` at
all. Before adding a widget, check `lua_widgets_modernized.lua` for it.

`slackpkg-gui/` is a second program in this repository: a PyQt6 front end for
Slackware's package manager, with its own CLAUDE.md. It lives here because the
panel's Slackpkg row launches it and the two share a palette — change one
palette and change the other. Nothing in the panel imports it, and it runs
standalone.

Every pixel of the panel is drawn with Cairo from `lua/dashboard.lua`. `conky.text` is empty
on purpose, so adding a `${...}` variable to it is **not** how you add
something to this panel — you draw it in the Lua.

## Commands

The repository runs in place; `lua_load` is relative to the config file and the
Lua locates its own state files, so nothing needs copying anywhere.

```bash
./start_conky.sh                    # replaces a running instance
```

Syntax-check everything (there is no test suite):

```bash
luac -p lua/dashboard.lua && bash -n slackware_updates.bash && python3 -m py_compile openweather.py
```

Render a frame to a PNG with no X server and no conky — the fastest way to
check a layout change:

```bash
lua -e 'package.cpath="/usr/lib64/conky/lib?.so;"..package.cpath; function conky_parse() return "63" end; dofile("lua/dashboard.lua"); conky_dashboard_render("/tmp/panel.png", 400, 1048)'
```

`conky_dashboard_render(path, w, h, alpha, preview)` takes an optional
`preview = { pointer = {x=,y=}, armed = "poweroff" }` to draw the hover and
confirm-armed button states, which otherwise need a real pointer.

## The panel is self-contained

Launching conky is the whole setup: no cron entry, and `start_conky.sh` is a
convenience (kill-then-relaunch), not a requirement. Two things make that work.

**It sizes itself.** `configs/dashboard.conf` is Lua, so it works out its own
geometry at load time: `_NET_WORKAREA` via `xprop` first (the usable area,
excluding space panels reserve), falling back to the tallest mode in
`/sys/class/drm/*/modes` when xprop is absent, then 1048.
`CONKY_DASHBOARD_HEIGHT` / `_WIDTH` / `_TOP` override it.

**`conky_window` reports the size conky *asked for*, not the size it got.**
This is the trap behind panel overlap. Request 1440 on a screen whose work
area is 1395 and the WM shrinks the window, but `conky_window.height` still
says 1442 — so the Lua lays out 47px of panel outside the window and the
button labels get clipped. `cairo_clip_extents` does not help; conky's cached
surface has the same wrong size. Two things keep them in agreement:

* ask for the work area, so there is nothing to clamp;
* `border_width = 0`, because any border makes the window two pixels taller
  than requested — enough to push it back over the work area and get clamped
  again.

If you change how the window is sized, verify `conky_window.height` against
the real X geometry rather than assuming they match.

**It refreshes its own data.** `collect()` calls `refresh_updates` and
`refresh_weather`, which spawn the collector scripts *detached* on an interval
(`config.refresh_updates` / `refresh_weather`, seconds, 0 disables):

`.weather.txt` is `key=value` lines (`temp`, `feels`, `temp_min`, `temp_max`,
`humidity`, `wind_speed`, `wind_deg`, `icon`, `description`, `city`, `sunrise`,
`sunset`, `tz`, …). Keyed rather than positional so the script and the Lua can
gain fields independently — unrecognised keys are ignored and missing ones are
simply not drawn. The reader still accepts the old two-line form. Sun times are
UTC with `tz` as the city's offset, so `os.date("!%H:%M", sunrise + tz)` gives
the time where the weather is, not where the machine is.

| Producer | Spawned by | Writes | Consumer |
| --- | --- | --- | --- |
| `slackware_updates.bash` | the Lua, every 900s | `.updates.txt` | `sample_updates` |
| `openweather.py` | the Lua, every 900s | `.weather.txt` | `sample_weather` |
| conky → `conky_start_widgets` | `update_interval = 0.2` | — | reads both |

The OWM key is resolved by `owm_key()`: `config.owm_api_key` if someone set it,
otherwise the first word of `.owm_key` at the repository root, which is
gitignored. **Do not move a key into `lua/dashboard.lua`** — that file is
tracked and the remote is public. The key reaches the fetcher through the
environment (`OWM_API_KEY=...`) rather than argv, so it does not sit in `ps`
against the long-lived python process.

`spawn_detached` appends `&`, so the shell exits as soon as it forks:
`os.execute` returns in about 2ms, the child is reparented to init, and there
is no zombie to reap. **Never call a collector synchronously** — they do
network I/O and would freeze the draw hook for seconds.

`slackware_updates.bash` takes an atomic `mkdir` lock (with a pid inside, so a
crashed run can be cleaned up) whenever `-o` is given, so a slow check cannot
have a second copy stacked on it. Manual runs to stdout deliberately skip the
lock.

Arguments are built through `shell_quote`, which wraps in single quotes and
escapes embedded ones as `'\''` — the city name and release string reach a
shell, so this is the injection boundary. It is tested against `x; touch ...`
and `$(whoami)`.

### The status wording is a contract

The shell script prints `Name: Status` and the Lua maps it to three states: `Updates available` → pending (red),
`No updates available` → ok (green), anything else → unknown (amber). Rows are
parsed generically, so adding a checker to the shell script needs no Lua
change. A checker that cannot reach the network must print `Unknown` — printing
"Updates available" on a failed fetch is a phantom update, which is the bug
this replaced.

Both scripts take `-o`/`--output` and write via a temp file plus rename. Use
that rather than a `>` redirect, or the panel can read a half-written file.

## Degrading instead of breaking

Only conky is genuinely required. Everything else is checked and its widget
withdrawn: no OWM key or cached reading and `section_weather` returns 0 height
(the two-pass layout then closes the gap); no battery and `section_battery`
returns 0; a power button whose binary is missing is drawn dimmed, labelled
"unavailable", and ignores clicks via `box.usable`. `command_available` caches
the result, so the probe happens once, not per frame.

When adding a widget, follow the same pattern: return 0 from `measure` rather
than drawing a placeholder.

The weather block's vertical anchors are **derived from measured ink, not from
`WX_ICON_SIZE`**. That constant is the size the glyph is drawn *to*; what it
puts on the panel is 1.22x bigger and asymmetric — worst case `0.642 * size`
above the centre (`10d`, the sun's rays clearing a cloud) and `0.574 * size`
below (`01d`, the bare sun), i.e. 180px of ink for a 148px box. Centring the
icon on the arithmetic middle of the gap therefore collides with the city
caption above *and* the temperature below, and it did both, twice. `WX_ICON_Y`
and `WX_TEMP_Y` are now computed from those ratios plus `WX_GAP`, and the rest
of the block hangs off `WX_TEMP_Y`, so changing the icon size moves everything
in step.

To re-measure after a drawing change, render each code in isolation rather than
reading the geometry out of the source — append a function to a copy of
`dashboard.lua` so it closes over the file-scope `icons` table, call
`icons.weather` onto a blank surface for each of `01d 01n 02d 02n 03d 04d 09d
10d 10n 11d 13d 50d`, and read the extreme non-transparent rows off the pixels.
Both previous attempts at these numbers were wrong because they were derived by
hand from one code.

The daylight arc has to be placed *after* the detail row; getting that wrong
silently draws one on top of the other. The arc is a squashed ellipse — a true
semicircle that wide would be 180px tall — and its path is built under a scaled
CTM but stroked after restoring it, or the scale distorts the line width along
with the shape.

The crescent moon is built by clipping to the moon's disc and then filling
everything except an offset shadow disc. An even-odd "punch" cannot do it: a
shadow large enough to cut a crescent also pokes outside the moon, and
even-odd fills that overhang, which yields a ring. If the moon ever looks like
a letter C again, that is why.

`config.bottom_gap` (default 18) is reserved at the bottom of the window before
anything is laid out, so the button bar clears a Plasma panel instead of
sitting flush against it. `conky_start_widgets` subtracts it once and passes
the reduced height to `draw_panel`, which is why the background, the edge
stripe and the button hit boxes all move together.

## Clickable rows and autostart

`section_updates` registers a hit box in `ui.rows` for any row whose name has
an entry in `config.update_actions`, and `conky_mouse_event` checks those
before the bottom bar's boxes. Rows are single-click; only the power bar arms.
`action_for` resolves an entry to a command and returns nil when the target is
missing, so a row whose program is not installed simply stays inert rather
than looking live.

`section_updates` also draws a **refresh button** in its header and registers
it in `ui.rows`' sibling `ui.controls`, which `conky_mouse_event` checks
*before* the rows. It calls `spawn_update_check()` — factored out of
`refresh_updates` — so it fires regardless of `config.refresh_updates`, and a
manual check still works when the schedule is switched off. The script's own
mkdir lock stops a click landing on top of a scheduled run from stacking two
copies. `ui.checking_at` drives an eight-second "checking…" caption; nothing
polls for completion, the next `sample_updates` tick simply picks the new file
up.

**Testing a click needs the refresh intervals set to 0.** `last_run` starts at
zero in a fresh Lua state, so the very first `conky_dashboard_render` spawns
both collectors on its own — which looks exactly like the click having worked.
Two such results here were meaningless before this was noticed. Render a copy
with `refresh_updates`/`refresh_weather` patched to 0, then dispatch
`conky_mouse_event` and watch `.updates.txt`'s mtime.

**A circular-arrow glyph needs its head at the *end* of the arc**, pointing
along the tangent in the direction of travel. Put it at the start and it aims
into the arc: the result renders as a ring with a nub, legible at 6x and
meaningless at 1x. `icons.refresh` draws at 15px, not 13 — the head has to
survive being four pixels across. Check glyph work by rendering at real size
and magnifying with `CAIRO_FILTER_NEAREST`, never by eye at 1x.

**The autostart entry's `--delay` is load-bearing.** `configs/dashboard.conf`
reads `_NET_WORKAREA` at parse time, and conky applies `--pause` *after*
`load_config_file()` (`src/conky.cc`: 2355 vs 2460), so conky's own flag
cannot substitute. The delay also cannot live in the `Exec=` line as
`sh -c 'sleep 10; …'` — `desktop-file-validate` rejects the unescaped `'` and
`;` — which is why `start_conky.sh` takes `--delay` itself.

## Colour

The palette is taken from `Conky-Calendar-Extra/conky/lua_widgets_modernized.lua`
in the Conky-themes repo: white `#FFFFFF`, accent `#FF4081`, warm `#FF7043`,
with that theme's four opacity tiers (`track` 0.15, `label` 0.55, `text` 0.85,
`live` 0.95). Everything structural is the same white at a different weight,
which is what makes it read as one theme.

Drawing code names a **role**, never a colour: `"text"`, `"label"`, `"track"`,
`"surface"`, `"accent"`, `"warm"`. `set_colour` resolves a role to a palette
colour plus its opacity tier and multiplies that by the panel's fade alpha. A
literal `"#RRGGBB"` still works, which is how the heat ramp returns a computed
blend. Re-theming should mean editing the config block and nothing else — if
you find yourself writing a hex in a section function, add a role instead.

`level_colour(pct)` and `heat_colour(celsius)` both hold at accent until a
threshold (`warm_above_pct` 75, `warm_above_temp` 70) and only then blend
towards warm, so an idle machine never reads as a hot one. The temperature one
is keyed to degrees rather than a fraction of `max_temp`, so raising the
ceiling does not quietly move the point where things start looking hot — same
reasoning as the theme it came from.

Note there is no green: "nothing to do" de-emphasises to `label` weight rather
than turning a colour the palette does not contain. The same rule killed a
yellow sun — a literal sun colour would be a fourth hue with no other home,
and the palette is shared with the calendar widget so both read as one theme.
The daytime sun uses `sun`, which resolves to `warm` today: sun-like without
inventing anything. It is a separate role rather than `warm` itself because
`warm` means "hot" in the CPU and temperature ramps and this means "daylight";
they coincide by luck, not by meaning. The moon, rain, bolt and snow stay on
`accent` — a warmed moon reads as a harvest moon, and warm precipitation reads
as embers.

## Data collection is fork-free

`collect()` reads `/proc/stat`, `/proc/meminfo`, `/proc/net/dev`,
`/proc/loadavg`, `/proc/uptime`, `/sys/class/hwmon/*`,
`/sys/class/power_supply/BAT*` and the two dotfiles. The previous version
spawned 14 processes per frame via `${exec ...}`; a frame now spawns none.

The one exception is the disk gauge, which uses `conky_parse("${fs_used_perc}")`
— an in-process conky variable, not a shell-out, because Lua has no `statvfs`.
It is guarded so the offscreen renderer works without conky.

Cadences are in **seconds**, not frames, so they stay correct if
`update_interval` changes: CPU/RAM/network every frame, disk/temp/battery every
5s, weather/updates every 15s.

`/proc/uptime` is used as the monotonic clock — `os.time()` only has
one-second resolution, too coarse to turn byte counters into rates.

## The network graph

`net_history` holds `NET_SAMPLES` (96) points per direction, pushed by
`record_network` on a **one-second** cadence — not once per frame. Two reasons
this matters:

* the window stays a fixed span of wall-clock time whatever `update_interval`
  is set to;
* each point is a true one-second average computed from the cumulative
  `/proc/net/dev` counters held in `net_mark`, not the per-frame rate in
  `stats.net.down`. That per-frame figure covers 200ms, and a window that
  short turns ordinary bursts into spikes that dwarf the real transfer — a
  steady 250 KiB/s download plotted peaks near 10 MiB/s before this.

Each half is scaled to **its own** peak. A shared scale reads as more honest
about the ratio, but on any ordinary asymmetric link it flattens upload into
the axis; the two peak figures under the plot carry the magnitude instead.

Samples are right-aligned, so a fresh start draws from the right and fills
leftwards over 96 seconds rather than pretending the missing history was idle.

## Layout reflows

Sections take `(cr, w, y, alpha, measure)` and return their own height; with
`measure` true they return that height without drawing. `draw_panel` measures
everything, then shares the leftover space equally between the sections, and
centres the block when the gaps hit their cap. A section with nothing to show
returns 0 and takes no gap — that is how the battery disappears on a desktop.

This is why the panel fills a 1048px window and a 1440px one equally well. Do
not reintroduce absolute pixel positions.

## Pointer handling

`lua_mouse_hook = 'mouse_event'` → `conky_mouse_event(event)`. Verified field
names for conky 1.24.2 (from `src/mouse-events.cc`): `type` is one of
`button_down`, `button_up`, `mouse_scroll`, `mouse_move`, `mouse_enter`,
`mouse_leave`; plus `time`, `x`, `y`, `x_abs`, `y_abs`, `mods`, and `button`
(`left`/`right`/`middle`/`back`/`forward`) or `direction` on the relevant
types. `x`/`y` are relative to the conky window.

`config.reveal = "auto"` keeps the panel visible until the first mouse event
arrives, then switches to hover behaviour. That is deliberate: if pointer
events never reach conky on a given desktop, the panel stays usable instead of
being invisible and unreachable.

## Things that will trip you up

**conky 1.24 API.** `own_window_argb_visual` was removed (the binary's message
is "ARGB is now always enabled when available"); opacity comes from
`own_window_colour`'s alpha, `#AARRGGBB`. `own_window_transparent` is
deprecated. `cairo_xlib_surface_create` lives in a separate `cairo_xlib`
module, not `cairo`, and is itself deprecated in favour of `conky_surface()` —
which returns a **conky-owned cached surface that must not be passed to
`cairo_surface_destroy`**. The Lua handles both paths and only destroys the
surface it created itself.

**Click-through.** `src/output/x11.cc` looks like it sets an empty ShapeInput
region for undecorated windows, which would make mouse events impossible. It
does not on this build: measuring the actual region (`XShapeGetRectangles`,
`ShapeInput`) returns one full-window rectangle for every `own_window_type` and
hint combination tested. Measure before believing the source here.

**This is a Wayland session.** Two consequences when verifying changes:
XTEST pointer synthesis is silently ignored (the compositor owns the pointer),
so hover and click behaviour cannot be tested programmatically — it needs a
human. And `import`/`xwd` against the conky window return a blank image, so the
panel cannot be screenshotted through X; `screenshot.png` is produced by
`conky_dashboard_render`, not captured from the desktop.

**Killing the old instance needs the *resolved* config path.** `start_conky.sh`
used to grep each `/proc/$pid/cmdline` for the absolute `$conf` string, which
only matches instances spelled that exact way. One started the way this file
and the script's own header suggest -- `conky -c configs/dashboard.conf &` --
never matched, so it survived every restart and drew a second panel on top of
the first. Two panels at 0.2s each, one slightly stale, is easy to mistake for
a rendering bug. It now parses `-c` / `--config` / `--config=` out of the
cmdline, resolves a relative value against that process's own `/proc/$pid/cwd`
(not ours), and compares `readlink -f` results. Check `pgrep -x conky` before
concluding the panel itself is misbehaving.

**`pkill -f` matches your own shell.** `pkill -f "conky -c $conf"` also matches
any process whose command line quotes that path, including the shell running
the script. `start_conky.sh` filters `pgrep -x conky` by reading
`/proc/$pid/cmdline` instead.

**Fonts.** Defaults to Noto Sans, with `Noto Sans Light` as a separate family
for the two large readouts — Cairo's toy font API only knows normal and bold,
so any other weight has to come through the family name. There is no
`font_medium`: it was declared and never read, which made setting it look like
it would do something. Fontconfig substitutes silently when a family is
missing, so a wrong-looking panel may just be a missing font. No icon font is
needed: every glyph is a Cairo path.

**The NVIDIA check compares against the Vulkan *beta* driver page**, which is
normally ahead of stable, so it will usually report an update even when current.
Inherited behaviour, flagged in a comment rather than silently changed.
