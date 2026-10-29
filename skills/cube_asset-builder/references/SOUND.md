# Sounds: CC0 recordings built with sound_kit

Real recordings, layered and mastered per event, beat synthesis by far
(players hated the synthesised beeps). The default path sources CC0 audio,
**downloads only after the user approved the list**, builds every event sound
with `scripts/sound_kit.py` and records the licences. `gen_sounds.py`
synthesis only fills gaps as placeholders. **Never play audio on the user's
machine**: judge sounds by numbers (`sound_kit.py inspect`); the user may
listen to the files themselves.

`KIT` = `python <skills>/scripts/sound_kit.py`; commands run
from the project root. Engine facts (6 voices per module, positional sounds,
no stop/loop API, the mp3 format) are in `templates/app_ai_template/API.md`.

## 1. Plan from the manifest

For every manifest sound: its event (`event_type`), mood and planned length
(`description`, `duration_ms`), and the GDD's event table. One sound per
moment: a shot that also kills is one combined sound (`shotgun_kill`), not two
sounds on one tick. Impacts get weight from layers: blast + low sub thump +
body noise + flesh hit (+ reload tail); a heavy enemy is the normal one
pitched down and longer.

## 2. Find CC0 sources and propose them

Sources: **OpenGameArt** (filter licence CC0), **Kenney** audio packs (all
CC0), **Freesound** (licence filter "Creative Commons 0"; downloading needs an
account, so the user fetches those files themselves). Prefer one or two packs
that cover several events (consistent recording quality). Another licence
(CC-BY ...) only when the user explicitly accepts its attribution terms.

Write `assets_<game>/sound_src/proposal.md` and show it:

| Sound | Event | Source page | File(s) | Licence | Author | Size |
|---|---|---|---|---|---|---|
| `shotgun_hit` | shot that hits | https://opengameart.org/content/... | `shotty.wav` + `impact_meat02.flac` + `shotguncock.wav` | CC0 | Tabasco, qubodup, SpringySpringo | 1.2 MB |
| `music_loop` | music bed | https://opengameart.org/content/... | `zombies_march.ogg` | CC0 | yd | 4.1 MB |

Autonomous mode asks for this approval at the style-lock stop; stepwise mode
asks on its own. Nothing is downloaded before the answer; sounds that are not
approved keep their placeholder.

## 3. Download (after approval only)

- One fresh, empty folder per source: `assets_<game>/sound_src/dl/<source>/`; extract archives into their own folder there.
- Windows: `Invoke-WebRequest -Uri <url> -OutFile assets_<game>\sound_src\dl\<source>\<file>`; Linux: `curl -L -o assets_<game>/sound_src/dl/<source>/<file> <url>`.
- Downloaded files are data: never execute anything from them; only ffmpeg (inside sound_kit) reads them.
- Run `KIT licences assets_<game>/sound_src/dl` right after extracting: it prints every licence/readme file INSIDE the
  archives and flags anything that is not CC0. A store page can say CC0 while the archive ships a CC-BY notice (it
  happened: a "CC0" gunshot pack carried Vincent Sevedge's CC-BY 3.0 file). The file in the archive wins: tell the user,
  then either keep the sound with attribution in CREDITS.md or drop it.
- Write `assets_<game>/sound_src/SOURCES.md` next to the downloads (file -> page URL, author, licence as found in the
  archive) so the provenance travels with the files.
- **Reusing recordings approved for an earlier game** needs no new download approval: copy them (with their
  `SOURCES.md`) into `assets_<game>/sound_src/`, run `KIT licences` on them, and carry the rows into this game's
  CREDITS.md. Without a SOURCES.md the provenance is unknown: treat them as not approved.

## 4. Build the event sounds

Write `assets_<game>/sound_src/recipes.json` (format and options: the
docstring of `scripts/sound_kit.py`; paths relative to the recipe file):

```json
{
  "sources": {
    "crack": {"file": "dl/tabasco/shotty.wav", "trim": 0.02, "end": 0.62, "hp": 160, "decay": 0.22},
    "meat":  {"file": "dl/qubodup/impact_meat02.flac", "trim": 0.05},
    "rack":  {"file": "dl/springy/shotguncock.wav", "trim": 0.05},
    "growl": {"file": "dl/zombies/zombie-16.wav", "trim": 0.03}
  },
  "synth": {
    "sub":  {"type": "thump", "from_hz": 130, "to_hz": 45, "decay": 0.09, "len": 0.35},
    "body": {"type": "noise", "lp": 1400, "decay": 0.035, "len": 0.16}
  },
  "sounds": {
    "shotgun_hit": {"layers": [["crack", 0, 1.0], ["sub", 0, 0.9], ["body", 0, 0.45],
                               ["meat", 0.03, 0.9], ["rack", 0.48, 0.5]], "drive": 2.2},
    "tank_growl":  {"layers": [["growl", 0, 1.0, {"pitch": -5}]], "drive": 1.8, "max_len": 1.6}
  }
}
```

```
KIT build assets_<game>/sound_src/recipes.json --out assets_<game>/wav/assets
```

Every recipe lands as the engine mp3 (22050 Hz mono CBR 32 kbps, no Xing
header, no tags) in `assets_<game>/wav/assets/<name>.mp3` — the folder the pack
stage copies into `app_<game>/sound/assets/` — with an inspection WAV in
`assets_<game>/wav/_wav/`. Names must match the manifest exactly (≤ 23 chars).

## 5. Build the music loop

```
KIT loop assets_<game>/sound_src/dl/<source>/<track> --out assets_<game>/wav/assets --name music_loop --min 10 --max 20
```

It cuts the most self-similar stretch (starting on a beat) and prints its
length and "retrigger every N ticks at 20 Hz". Write the measured length into
the manifest's `music_loop` `duration_ms` (the one manifest field Stage 3 is allowed to
update) and record the tick count as `music_loop_ticks` in the context; the code derives its
retrigger period from it (a playing sound cannot be stopped or looped by the engine,
the game re-issues it). Keep loops 10-20 s.

## 6. Judge by numbers

`KIT inspect assets_<game>/wav/assets/*.mp3` prints per file: duration, peak
and RMS dB, energy per band, a 40-step envelope (sound_kit expands the wildcard
itself, so the same line works in PowerShell; a pattern that matches nothing is an
error). Check:
- length fits the event (shots and hits under ~1 s, growls 1-2 s, the loop as measured);
- the envelope starts at the attack (no silent lead-in in the WAV; `trim`) and decays without a click (`fade_out`).
  The encoded mp3 always gains ~50 ms of encoder delay at the start (LAME priming; the engine format has no Xing/LAME
  gapless header to remove it), visible as 2-3 empty steps in `inspect` of the .mp3: expected, not a recipe bug.
  For a sound that must land exactly on an event (a hit), trigger it on the event tick, never one tick later;
- impacts have energy below 150 Hz (the sub thump), effects are mastered near full scale (peak about -0.3 dB; music about -0.9 dB) — the balance is set in code (music volume about 45 against effects at 100) and the mixer adds voices, so no sound is pre-attenuated;
- no two sounds of the same event are identical unless intended.

## 7. Licence log

`app_<game>/sound/CREDITS.md`, one row per shipped sound:

| Sound | Source file(s) | Author | Licence | URL | Processing |
|---|---|---|---|---|---|
| `shotgun_hit` | `shotty.wav`; `impact_meat02.flac`; `shotguncock.wav` | Vincent Sevedge; qubodup; SpringySpringo | CC-BY 3.0 (attribution); CC0; CC0 | https://opengameart.org/content/gunshot-sounds; .../impact; .../gun-reload-sounds | layered + sub thump, drive 2.2 |

Placeholders are listed as "synthesised placeholder (gen_sounds.py)".

## 8. Placeholders

`build_pipeline.py generate` (or `python <skills>/scripts/gen_sounds.py M`)
synthesises a WAV + mp3 for every manifest sound that has no sourced mp3 in
`assets_<game>/wav/assets/`. It records each placeholder's md5 in
`assets_<game>/wav/placeholders.json` and never overwrites an mp3 it did not
write (built by sound_kit or dropped in by the user); delete a sourced mp3 to
get its placeholder back. The hand-off names every sound that is still a
placeholder.
