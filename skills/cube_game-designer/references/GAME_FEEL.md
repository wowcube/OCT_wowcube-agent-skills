# Game feel and cube composition: lessons from shipped builds

Things players (and the people testing builds) reliably complained about,
turned into design rules. Check every GDD against this list; most of these
cost a full fix round when discovered after implementation.

## Movement and pacing
- **Grid moves must glide.** A character that jumps cell to cell instantly reads as broken, even with a walk animation. Animate the move across the gap (the glide time is a tunable) and play the walk cycle during it.
- **Slow enemies, readable threats.** Enemies must leave the player time to react: an attacker that closes the distance faster than the player can respond is unfair on a cube that is controlled by tilting and twisting.
- **Put every pace number in one tunables table** in the GDD (player step time, enemy step time, spawn interval, cooldowns). Expect two or three balance passes after the first playable build ("slow the heroine down 4x", then "a bit livelier"); the GDD should say which numbers are expected to move.

## Threats must be telegraphed
- **Every enemy attack has a wind-up** (about a second) with a clear pose change and a marker on the target cell, so the player can dodge.
- **Make the attack range visible.** If an enemy can strike from two cells away (a charge/dash), show the path (trail, marker) during the wind-up. Unclear range was the top complaint about enemies.
- A charge/dash from distance is fun when it is frequent enough to matter; tune its frequency explicitly.

## Weapons and hits must have weight
- A shot needs four things at once: a muzzle flash, a burst of particles (procedural circles: no sprites needed), a recoil/shoot pose, and a layered sound (blast + low thump + hit + reload). One of them missing and the shot "does not feel".
- **The target reacts on the first hit**: a wounded model (torn, limping, bloodied) after the first hit, a blink, then death with a splat/corpse decal.
- **No "stand still and win"**: if the player can win without moving, the balance is wrong. Typical fix set: regular enemies die in 2 hits, a fire cooldown of about 1 s, a heavy enemy (5 hits, changes model after 2) that forces the player to run, and a cap on enemies on screen (3 was right for a 4x4 room).

## Composing across 24 screens
- **Scenery spanning several faces is one picture**: author it as a panorama and split it per screen so it is continuous and upright around the four side faces. Repeating the same backdrop tile on every screen looks cheap.
- **Unique objects appear once on the cube.** A moon or a sun drawn on every screen is a bug, not decoration. Say in the GDD where each unique object lives (which face, which screen) and where it goes when the cube is reoriented.
- Decide per element whether it lives on one screen, one face, or repeats on every face (HUD usually repeats on each side face; the playfield usually lives on the top face). Write it down: it is the first thing implementations get wrong.
- Tilt-driven games: the playfield follows the face that is up; the GDD must say what happens on the other faces at the same time.

## Sound
- The engine mixes several sounds per module: a music bed plus effects is the default, not a luxury
  (a game ships without music only when the GDD says so explicitly). Plan a looping music track (retriggered by the game; sounds cannot be stopped once started, so keep loops short, 10-20 s) and an event table "event -> sound -> mood".
- Real recordings layered and mastered beat synthesis by far. Source CC0 packs (user approves the list), layer them per event (blast + thump + flesh hit; growl variants per enemy type, pitched down for the heavy one).
- One sound per event moment: if a shot also hits, play a combined "shot+hit" sound instead of two sounds on the same tick.

## Hooks the GDD should ask for (testing and media)
- An **autoplay bot** switch so the game can play itself (headless screenshots, balance runs, gameplay video).
- A **mute** switch for test builds.
- A debug switch that pins the playfield to one face (screenshots of the room without tilting).
- A **launcher icon** in the game's style is part of delivery; a **short gameplay video** (from the
  autoplay hook's headless frames) is offered at delivery and made when the user wants it.
