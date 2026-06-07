---
name: imitate-trend
description: >-
  Turn a trending TikTok/Reels/Shorts video into a finished brainrot render by
  describing it with Gemini, then building and running a preset. Use this
  whenever the user wants to imitate, recreate, copy, riff on, or "do our
  version of" a trend, dance, or viral clip — even if they just paste a TikTok
  URL and say "make this" or "can we do this one." Drives the whole loop:
  describe the video, confirm the description is accurate, pick the fidelity
  approach (dance vs mimic), ask which character and outfit, generate, and
  iterate on the result.
---

# Imitate a trend

The user found a trend they want their character to do. Your job is to get from
"here's a link" to a finished render, keeping them in the loop at the decisions
that actually matter (is the description right? which character? which outfit?
is the result good enough?) and handling everything mechanical yourself.

The pipeline already knows how to turn a **preset → video**. This skill is the
front half: turning a **reference video → a correct preset**, then running it
and iterating. Everything here runs from the repo root with the project venv
(`./venv/bin/python manage.py ...`).

## The shape of the work

```
trend URL ──describe_trend──▶ draft preset ──confirm accuracy──▶ pick mode
   ──ask character + outfit──▶ finish preset ──run_job──▶ review ──▶ iterate
```

Work it as a conversation, not a script. Do the mechanical steps (running
commands, editing the preset) without narrating every keystroke; stop and ask
only at the four human decision points below.

## Step 1 — Get the reference and describe it

If the user gave a URL, use it. If they only described a trend in words, ask for
the link — Gemini needs the actual clip to describe motion and setting
faithfully.

Run the authoring helper, which watches the video (Gemini, native video input)
and writes a draft preset with `theme` / `style` / `motion` / `hook` filled in:

```bash
./venv/bin/python manage.py describe_trend "<url>" --name <short-slug>
```

This needs `PROVIDER_MODE=real` and `GEMINI_API_KEY` set in `.env` to actually
watch the video. In `fake` mode it returns a canned fixture description — fine
for testing the plumbing, useless for a real trend, so check the mode first if
the description looks generic.

The draft lands at `presets/trend_<slug>.yaml` with the character and song left
as TODO comments. Read it.

## Step 2 — Confirm the description is accurate (the first human gate)

Gemini is good but not infallible, and every downstream generation inherits its
mistakes. Before building on the description, show the user the four fields in
plain language and ask whether they match what's in the video:

> Here's what Gemini saw — does this match the trend you want?
> • **Setting:** <theme>
> • **Look:** <style>
> • **Moves/camera:** <motion>
> • **Hook idea:** <hook>

Watch for the usual misreads: a setting detail that's wrong, an outfit it
over- or under-described, choreography it flattened into "dancing." If the user
corrects something, edit the field in the preset directly — their words are
better ground truth than a re-run. Only re-run `describe_trend` if they want a
genuinely fresh pass (e.g. they realize they linked the wrong video).

Note: `style` will be **rewritten** in Step 4 anyway (the user picks the
outfit), so don't sweat its exact wording here — focus on whether `theme` and
`motion` are faithful, since those carry the trend's identity.

## Step 3 — Pick the fidelity approach (dance vs mimic)

"Have fal create it accurately" means choosing the right pipeline for *what kind
of accuracy the user wants*. There are two, and they trade off:

- **`dance`** (recreate the *vibe*): scene-gen builds the character in the
  described setting/outfit, then Kling animates a fresh high-energy dance. The
  *aesthetic* matches the trend; the *exact choreography* does not. This is the
  default and the right call for most "do our version of this" requests — it's
  cheaper (one scene-gen + one Kling), gives full control over setting/outfit,
  and looks the most polished.
- **`mimic`** (copy the *exact moves*): the locked character performs the trend's
  precise choreography via motion transfer (Wan-Animate), driven by the original
  clip. Use this only when the *specific dance* is the whole point — a named
  move set people will recognize. It's mute, text-free (captions added at post),
  and the appearance scene must be **bright, clean, uncluttered** or both
  backends degrade. `describe_trend --mode mimic` already seeds `drive.source`
  with the URL.

Ask the user which they want, framed around intent:

> Do you want her doing **this exact dance** (mimic — copies the moves precisely,
> mute, you add sound at post), or **a fresh dance in this vibe** (dance — same
> setting/outfit/energy, more polished, captions + hook baked in)?

If they picked mimic and you described with `--mode dance`, rerun
`describe_trend --mode mimic` (or just convert the preset: set `mode: mimic`,
add the `drive:` block with the URL, remove any `song:`, and tighten `theme`
toward a plain uncluttered backdrop — see `mimic_neon_girl.yaml`).

## Step 4 — Ask which character and outfit (the second human gate)

The draft has a character TODO. Two questions, and they're genuine choices the
user owns — never assume the character or quietly default the outfit.

**Which character?** List what's available so they can just pick:

```bash
ls presets/characters/
```

The locked, recurring character is the **neon girl** (her `.lora.safetensors` +
trigger `neongirl`) — her LoRA is the highest-fidelity, most consistent option,
so recommend her unless the user wants someone else. Wire her exactly as the
existing presets do (these paths are **local + gitignored** — reference them,
never commit them or any identity URL):

```yaml
character:
  image: presets/characters/neon_girl.png
  lora: presets/characters/neon_girl.lora.safetensors
  trigger: neongirl
```

**Which outfit?** This becomes the `style:` field. The neon girl has outfit
variants on disk (athleisure, evening, streetwear, y2k_denim) — offer them, or
let the user describe a new one to match the trend. Translate their answer into
a concrete `style:` phrase in her voice, e.g.:

```yaml
style: "Y2K cyber-rave aesthetic — sleek hair, metallic holographic makeup, a fitted metallic holographic outfit, shiny and futuristic"
```

**Wardrobe guardrail — explain it if the trend pushes revealing:** keep the
outfit fitted-but-clothed. Bikini/lingerie/swimwear gets the render
age-restricted and suppressed (~0 views), so even if the trend's original is
skimpy, adapt it to a platform-safe equivalent and tell the user why.

## Step 5 — Finish the preset and run it

Fill the remaining gaps:
- **dance** needs a `song.source` (a TikTok URL or a `"title artist"` search) —
  ask the user what audio, or reuse the trend's sound if they want it.
- **mimic** is mute — no song; the `drive.source` is already set.
- Add a `hook:` only for dance (mimic/vibe carry no text). Use Gemini's
  suggestion or the user's own line.

Then run it. Inline (no worker needed, blocks until the mp4 exists) is simplest
for an interactive loop on the Pi:

```bash
./venv/bin/python manage.py run_job presets/trend_<slug>.yaml --sync
```

Report the final `output=` path and surface the video to the user.

## Step 6 — Review and iterate (the third human gate)

Show the result and ask what to change. Map their feedback to the cheapest lever
that fixes it — re-running generation is expensive, so prefer compose-only
changes when they apply:

| Feedback | Lever |
|---|---|
| Setting/outfit/character wrong | Edit `theme`/`style`/`character`, re-run (regenerates — expensive). |
| Dance too tame / wrong energy | Edit `motion`, re-run. |
| Hook text, captions, beat cuts, loop feel | Compose-only — these re-compose from cached clips without re-paying for generation (see `compose_video` levers). |
| Loop has a visible seam | Try `DANCE_LOOP_MODE` (`crossfade` vs `endframe`) — see CLAUDE.md. |
| Identity drifts between renders | Confirm the LoRA + trigger are wired; the LoRA beats PuLID for consistency. |
| Mimic legs melt / background warps | The appearance scene is too busy/dark — brighten and simplify `theme`; confirm `MOTION_TRANSFER_PROVIDER=wan_animate`. |

Iterate until the user is happy. Keep the working preset — a winning trend
render is worth saving under a real name (rename off the `trend_` prefix).

## Guardrails worth remembering

- **Never commit her assets.** The repo is public; her images, the
  `.lora.safetensors`, and any identity URL stay on local disk only. Presets
  reference the gitignored local paths — that's intentional, keep it that way.
- **Loud failures.** If a command errors, surface it — don't paper over a failed
  fetch or a missing key with a half-built preset.
- **Don't over-ask.** The four gates (description accuracy, mode, character,
  outfit) are real decisions. Everything else — running commands, filling
  mechanical fields, choosing the cheap iteration lever — is yours to just do.
