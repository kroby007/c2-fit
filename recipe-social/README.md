# C2 Fit — automated recipe carousels

Generates a daily recipe carousel and posts it to TikTok
([@c2_fit_](https://www.tiktok.com/@c2_fit_)). One recipe becomes three
1080×1350 slides, a caption with emojis and rotated hashtags, and a post.

```
generate  →  render  →  stage  →  gate  →  publish
 recipe      hero photo  public   quality   TikTok
 caption     + 3 slides  URLs     checks
 hashtags                + phone
                           page
```

**You can run all of this without a TikTok developer account.** Set the
`MANUAL_MODE` repository variable to `true` (or pass `--manual`) and the pipeline
stops after staging, having published everything to `today.html` on the Pages
site — open it on a phone, save three images, copy the caption, post. Since
drafts mode requires you to open TikTok and choose a sound anyway, API access
saves only the file transfer.

Each stage reads and writes `out/<date>/post.json`, so any stage can be re-run on
its own against a previous stage's output.

Instagram and Facebook publishers are built and tested but **off by default**
while TikTok is being proven out — see [Other platforms](#other-platforms-later).

---

## The one thing you cannot automate: the song

**No API lets you attach a specific trending sound.** TikTok's Content Posting
API exposes a single boolean, `auto_add_music`, which lets *TikTok's backend*
pick a trending sound — there is no parameter that takes a sound ID. This is a
platform limitation, not something a different library works around.

So there are two modes, set by `TIKTOK_POST_MODE`:

| Mode | What happens | Song control | Needs the audit? |
|---|---|---|---|
| `MEDIA_UPLOAD` **(default)** | Carousel lands in your TikTok **drafts** | **You pick it**, in the app | No |
| `DIRECT_POST` | Posts automatically | TikTok picks one | **Yes** |

The default is drafts: the system does all the work and you spend ~20 seconds
tapping the sound you want and hitting post.

`DIRECT_POST` additionally requires passing TikTok's Content Posting API audit.
Until that passes, **every direct post is forced to `SELF_ONLY`** — visible only
to you. Flip the mode with a repository variable once you're approved; no code
changes.

---

## Manual mode — the whole system, no API access

TikTok app approval takes real time, and you may never need it. Set one
repository variable:

| Variable | Value |
|---|---|
| `MANUAL_MODE` | `true` |

The scheduled job now runs end to end every day and stops before the API call,
having published the finished post to **`<PAGES_BASE_URL>/today.html`**. Open
that on your phone, save the three images, tap *Copy caption*, post. A minute a
day, and nothing to install or maintain.

Running it yourself instead of waiting for the cron:

```bash
cd recipe-social
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...     # recipe generation
export GEMINI_API_KEY=...               # food photography
export PAGES_BASE_URL=https://<user>.github.io/c2-fit

python -m src.cli run --manual
```

Then commit and push `docs/` so Pages serves it. On **Windows**, use PowerShell
and set the keys with `$env:ANTHROPIC_API_KEY = "sk-ant-..."` — `export` is
shell-specific. You need Chrome installed; the renderer finds it at the standard
install paths without any PATH setup.

`run --no-publish` is the stricter variant: it stops after rendering and writes
nothing public, leaving `slide1.png`, `slide2.png`, `slide3.png`, and
`caption.txt` in `out/<today>/` to move around by hand.

**What API access would actually add:** it uploads the carousel into your drafts
so you skip saving three images. It does not choose the sound and it does not
publish for you. Weigh that against the review before doing the work.

---

## Setup

> New here? [`START-HERE.md`](../START-HERE.md) at the repo root is the same
> setup as a short ordered checklist. This section is the detail behind it.

> **Keep this repository public.** TikTok fetches carousel images anonymously
> over HTTPS, so the Pages site must be readable without credentials. Everything
> here is safe to publish — API keys live in Actions secrets, and a rotated
> refresh token that can't be written back lands in `state/*.local`, which is
> gitignored.

### 1. Enable GitHub Pages

Settings → Pages → Source: **Deploy from a branch**, branch `main`, folder
**`/docs`**. After it builds, note the URL — something like
`https://<user>.github.io/c2-fit`.

This one site does two jobs: it hosts the slide images at a URL TikTok will
accept, and it supplies the website / privacy / terms URLs TikTok's app
registration demands.

Then set it as a repository **variable** (Settings → Secrets and variables →
Actions → Variables): `PAGES_BASE_URL` = that URL, no trailing slash.

> **Before submitting for app review:** replace the `hello@example.com`
> placeholder in `docs/privacy.html` and `docs/terms.html` with a real contact
> address. TikTok's reviewers read those pages.

### 2. Generation keys

| Secret | Where to get it | Cost |
|---|---|---|
| `ANTHROPIC_API_KEY` | <https://console.anthropic.com> | ~$0.04–0.06 per post (recipe + photo check) |
| `GEMINI_API_KEY` | <https://aistudio.google.com/apikey> | ~$0.04 per image |

At one post a day that is roughly **$3/month** — see
[Where the money goes](#where-the-money-goes) for the breakdown and the levers
that bring it down. Gemini image generation has **no free tier**; billing must be
enabled on the Google Cloud project behind the key or every run fails with a 429.

Neither of these is covered by a Claude Pro or Google One subscription — the APIs
are metered separately from any consumer plan.

### 3. TikTok

1. Register an app at <https://developers.tiktok.com>.
2. Point **Website URL** at your Pages URL, **Privacy Policy** at
   `.../privacy.html`, **Terms of Service** at `.../terms.html`.
3. Add the **Content Posting API** product. Request scopes `user.info.basic` and
   `video.upload`. (Add `video.publish` only when you go for the audit.)
4. Add a redirect URI of exactly `<PAGES_BASE_URL>/oauth.html`.
5. **Verify your URL prefix** under *Manage URL properties*: TikTok gives you a
   file; commit it to `docs/` (or `docs/media/`, matching the prefix you're
   verifying), push, wait for Pages, then click Verify.

   This step is not optional. Carousel images are `PULL_FROM_URL` only, and
   TikTok refuses to fetch from a prefix you have not proven you own — you'll get
   `url_ownership_unverified`. It is also why `raw.githubusercontent.com` cannot
   be used: you can't place a verification file on a domain you don't own.

6. Get a refresh token:

   ```bash
   export TIKTOK_CLIENT_KEY=...
   export TIKTOK_CLIENT_SECRET=...
   export PAGES_BASE_URL=https://<user>.github.io/c2-fit
   python scripts/tiktok_auth.py
   ```

   Add the printed value as the `TIKTOK_REFRESH_TOKEN` secret, plus
   `TIKTOK_CLIENT_KEY` and `TIKTOK_CLIENT_SECRET`.

   TikTok rotates the refresh token on every use, so the job writes the new one
   back into your Actions secrets. That needs a `GH_PAT` secret — a fine-grained
   PAT for this repo with **Secrets: read and write**. Without it the run still
   works but warns and drops the new token in `state/`, which you'd have to copy
   over by hand before the next run.

### 4. Check it — `doctor`

```bash
python -m src.cli doctor
```

Posts nothing. Verifies Chromium and the committed fonts, that every credential
is present, that all four Pages URLs return 200 (including `/media/README.md`,
which proves Pages serves the exact prefix the publisher hands TikTok), that your
refresh token exchanges cleanly, and that the Content Posting API scope is live.

The check worth reading carefully is **Connected account**: `creator_info`
returns the authorized username, and doctor compares it against the handle in
`config/brand.yaml`. If you authorized a different account than the slides are
branded for, this is where you find out — otherwise it only surfaces when a post
lands somewhere unexpected.

Every failure names its own fix. The one thing doctor *cannot* check is the
URL-prefix verification click in the TikTok portal, and it says so.

To run the same checks against your **Actions secrets** rather than your laptop,
trigger the **Preflight (check setup)** workflow from the Actions tab. That's the
environment the daily job actually runs in.

### 5. First live post

```bash
python -m src.cli run
```

Then open TikTok → Drafts. You should see the carousel with all three slides in
order and the caption intact. Add a trending sound and post.

### 6. Turn the schedule on

`.github/workflows/daily-post.yml` runs at 15:00 UTC daily. Try it first with
**Run workflow → dry run** ticked: it builds everything and prints the exact
payloads without sending anything.

---

## Commands

```bash
python -m src.cli doctor              # check the setup, post nothing
python -m src.cli generate            # recipe + caption + hashtags
python -m src.cli render              # hero photo + three slides
python -m src.cli stage               # copy into docs/media, record public URLs
python -m src.cli wait                # block until Pages serves them
python -m src.cli gate                # quality checks
python -m src.cli publish --dry-run   # print payloads, send nothing
python -m src.cli run                 # the whole chain
python -m src.cli run --manual       # build + stage, post from today.html by hand
python -m src.cli run --no-publish    # Phase 0: build assets only, touch nothing public

python -m src.cli resume              # adopt a failed run's recipe + photo
python -m src.cli --date 2026-07-26 render   # re-run one stage
python -m pytest tests/ -q
```

---

## When a run fails, don't pay for it twice

The two calls that cost money — writing the recipe and generating the photo —
happen at the start of a run. Anything that goes wrong after them (a bad gateway
from the image host, a crash in a later stage) used to throw that money away,
because the next run generated everything from scratch.

It doesn't now. `generate` and `render` each reuse what is already sitting in
`out/<date>/` and only call the API when there is nothing there:

```
Reusing the recipe already generated for 2026-08-11: Chipotle Chicken Burrito Bowl
Reusing the hero image already generated for 2026-08-11 (1,804,585 bytes)
```

So re-running a failed day locally costs nothing. Use `--regenerate` or
`--new-image` when you want a fresh one anyway.

### Salvaging a failed run on GitHub

Every run uploads `out/` as an artifact, kept for 14 days, so a failed run's
recipe and photo survive it. To reuse them:

1. Open the failed run and copy its **run ID** — the last number in the URL,
   e.g. `.../actions/runs/31512123594`.
2. Actions → **Daily recipe post** → **Run workflow**.
3. Paste the ID into **`resume_from_run`**, tick **`manual`**, run it.

The run downloads that artifact, re-dates it onto today, and carries on from
there. The log will say `Reusing the recipe...` where it would normally say
`Generated:`.

Caption and hashtags are rebuilt rather than carried over — they cost nothing and
a stale hashtag set is one of the things the quality gate holds posts for. The
recipe and the photo, the two things you paid for, are what actually transfer.

> A new recipe always discards the photo beside it. The photo is *of* a specific
> dish, so pairing it with a different recipe would produce slides showing the
> wrong food — with every check still passing.

---

## Configuration

Everything you'd want to change lives in `config/`, not in code.

| File | Controls |
|---|---|
| `brand.yaml` | Handle, colors, fonts, the four series badges and the rules that earn them, food-photography direction |
| `niche.yaml` | The recipe brief — positioning, hard constraints, what to require and avoid |
| `hashtags.yaml` | Hashtag pools per bucket and how many to draw from each |

**Series badges** are the account's identity: `HIGH PROTEIN`, `UNDER $3`,
`AIR FRYER`, `15 MINUTES`. Each has a machine-checked rule, so a recipe only
keeps a badge it actually earns — the generator cannot claim `HIGH PROTEIN` on a
22g recipe. Most recipes earn two or three, and every recipe must earn at least
one.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `MANUAL_MODE` | unset | `true` stops before TikTok and posts via `today.html`. No developer app needed |
| `IMAGE_CHECK_MODEL` | `claude-haiku-4-5` | Model for the hero-photo sanity check. Separate from `RECIPE_MODEL` on purpose — see below |
| `TIKTOK_POST_MODE` | `MEDIA_UPLOAD` | `DIRECT_POST` for fully automatic (post-audit) |
| `TIKTOK_AUTO_ADD_MUSIC` | `true` | Let TikTok attach a trending sound (DIRECT_POST only) |
| `IMAGE_PROVIDER` | `gemini` | Image backend |
| `GEMINI_IMAGE_MODEL` | `gemini-2.5-flash-image` | `gemini-3-pro-image` for higher quality |
| `RECIPE_MODEL` | `claude-sonnet-5` | Model that writes the recipe. `claude-opus-5` if recipes start feeling generic |
| `RECIPE_EFFORT` | `high` | Thinking depth for the recipe. `medium` trades some quality for cost |
| `CHROME_BINARY` | auto-discovered | Explicit path to Chrome/Chromium |

Every row above can be set as a **repository variable** and the workflows pass it
through. Leaving one unset is the same as not setting it — an unset variable
arrives as an empty string, and `config.setting()` reads blank as "use the
default" rather than passing `""` down to an API call.

### Where the money goes

Roughly **$0.08–0.11 a post** at the defaults, split across three calls:

| Call | Model | Cost |
|---|---|---|
| Write the recipe | Sonnet 5, high effort | ~$0.03–0.05 |
| Generate the hero photo | Gemini 2.5 Flash Image | ~$0.04 |
| Check the photo | Haiku 4.5 | ~$0.01 |

About **$3/month** at one post a day. Everything downstream — rendering, staging,
Pages hosting, Actions minutes — is free, so the whole bill is model calls.

Two deliberate choices behind that. The recipe runs on **Sonnet at high effort**
rather than Opus at medium: output tokens dominate the bill, so the tier matters
more than the thinking depth, and high effort buys back most of what dropping a
tier costs. The photo check runs on **Haiku**, because "is this food, does it
match the dish, is there text on it" does not need a frontier model — it used to
share `RECIPE_MODEL` and cost about as much as writing the entire recipe.

Note Sonnet 5 is on introductory pricing ($2/$10 per million tokens) through
**2026-08-31**, after which it returns to $3/$15 — expect the per-post figure to
rise about 30% then, to roughly $4/month.

`output_config.effort` is **rejected outright by Haiku 4.5**, so the check sends
it only to models that accept it. If you point `IMAGE_CHECK_MODEL` at another
model that doesn't support effort, add it to `_EFFORT_UNSUPPORTED` in
`src/images/verify.py` — otherwise every run fails at that call.

A failed run still costs whatever completed before it died — a run that writes
a recipe and then loses the image generation bills for the recipe. That is the
main argument for the retry in `src/images/gemini.py`.

---

## How the feed stays varied

`state/history.json` is the memory. Every finished post is appended to it and
committed, because GitHub runners are wiped between runs — history that isn't
committed doesn't survive to tomorrow. Four things read it:

| Reads | Effect |
|---|---|
| `all_slugs()` | A recipe that has run before is **refused outright**, however long ago |
| `recent_titles()` | Recent titles go into the prompt as "do not create anything similar", and a title sharing most of its words with one is rejected |
| `recent_proteins()` | The last 4 proteins are **removed from the JSON schema**, so the model cannot return them |
| `recent_methods()` | The last 2 cooking methods, likewise |
| `recent_hashtags()` | Rotates the tag selection away from the last 5 posts |
| `already_posted_today()` | Stops a re-run double-posting |

**Protein is the stronger of the two rotations**, and rotates further back.
Chicken cooked four different ways is still chicken four days running — which is
exactly how this feed started out. The pan is a smaller tell than the protein.

### Repeats are retried, not held

A repeat is checked for in `generate`, **before the image is bought**, and the
generator is simply asked again — up to 3 times, with the rejected title added to
the exclusion list so the retry doesn't just rephrase it. A repeat caught here
costs one recipe call, a few cents. A repeat caught by the gate costs the whole
day's post.

If all 3 attempts still repeat, the run continues and the gate holds it. That's
deliberate: a held post you can see beats a silent repeat.

`all_slugs()` is unbounded, unlike every other window. The others trade recency
against pools that would otherwise exhaust themselves — but an exact repeat is
never acceptable, no matter how long ago it ran.

Method rotation is enforced in the schema rather than asked for in the prompt.
A prompt instruction can be ignored; a value that isn't in the enum cannot be
returned at all. With five methods in `niche.yaml` and two excluded, there are
always at least three to choose from — and if you shorten that list, the
exclusion yields rather than leaving an empty enum and a failed run.

**The method is never rendered anywhere** — not on a slide, not in the caption.
The title is the only thing a reader ever sees. So rotating the method achieves
nothing on its own if the dish is still *called* a Skillet, and the gate holds
any title naming a method the recipe doesn't use. Only the methods' own names
count: `baked` and `pan` appear in plenty of honest titles, and holding those
would cost more good posts than it saved.

> **The first three posts were all skillets**, and nearly the same dish each
> time. `queue.record()` was only ever called by the publish stage, so running in
> manual mode left `history.json` permanently empty — and every mechanism above
> reads that file. The generator saw no recent titles, the gate had nothing to
> compare against, and nothing tracked methods at all. Manual mode records now.

## The quality gate

Runs before anything publishes. It **corrects** what it can and **holds** what it
can't:

- Recomputes calories from protein/carbs/fat at 4/4/9 and holds if the stated
  figure is more than 15% off — the reliable signal that the model invented the
  numbers.
- Drops series badges the recipe doesn't earn; holds if it earns none.
- Holds on ingredient count, total time, cost, or serving count outside the brief.
- Holds if an allergen appears in the ingredients but isn't declared, so the
  caption warning is never wrong.
- Holds a recipe too similar to a recent post.
- Holds if the caption or hashtag count exceeds a platform limit.
- Checks the generated photo with a vision model: is it food, does it match the
  dish, is it appetizing, does it have text baked in.

A held post moves to `out/held/<date>/` and opens a GitHub issue. It never
reaches a platform.

---

## Other platforms (later)

The Instagram and Facebook publishers are written and tested — they're just not
in the default path, so nothing outside TikTok can fail a run. Turning them on:

1. Convert the Instagram account to **Business** or **Creator** and link it to a
   Facebook Page. The publishing API does not work on personal accounts at any
   tier — this is the most common reason Instagram setup fails.
2. Create a Meta app at <https://developers.facebook.com> with
   `instagram_content_publish`, `pages_manage_posts`, and `pages_read_engagement`.
3. Add secrets `META_ACCESS_TOKEN`, `IG_USER_ID`, `FB_PAGE_ID`,
   `FB_PAGE_ACCESS_TOKEN`, and add them to the `env:` block in
   `.github/workflows/daily-post.yml`.
4. Widen `DEFAULT_PLATFORMS` in `src/cli.py`, or pass
   `--platforms tiktok,instagram,facebook`.

Page access tokens derived from a long-lived user token don't expire, so unlike
TikTok there's no rotation to manage.

---

## Costs

See [Where the money goes](#where-the-money-goes) for the per-call breakdown —
roughly **$3/month** at one post a day, all of it model calls.

TikTok's own daily posting cap is far above one post a day, so nothing here is
constrained by the platform.

---

## Troubleshooting

Run `python -m src.cli doctor` first — it diagnoses most of these directly.

**`url_ownership_unverified` from TikTok** — the URL prefix isn't verified.
Check that `PAGES_BASE_URL` matches the prefix in *Manage URL properties*
exactly, and that the verification file is live on the Pages site.

**Post is only visible to me on TikTok** — expected on `DIRECT_POST` before the
Content Posting API audit passes. Use `MEDIA_UPLOAD` until it does.

**Posts landed on the wrong account** — the token authorized a different account.
`doctor` catches this under **Connected account**; re-run `scripts/tiktok_auth.py`
while logged into @c2_fit_.

**Emoji render as empty boxes** — the machine has no colour emoji font. The
workflows install `fonts-noto-color-emoji`; locally, install it the same way.

**Text overflows a slide** — headline and list sizes step down by length, but a
very long title with a ten-ingredient list can still crowd. Shorten the title in
`out/<date>/post.json` and re-run `render`.

**`No Chromium/Chrome binary found`** — set `CHROME_BINARY` to its path. On
Windows the standard Chrome and Edge install locations are searched already, so
this usually means Chrome is somewhere non-standard:
`$env:CHROME_BINARY = "C:\path\to\chrome.exe"`.

**`'export' is not recognized`** (Windows) — that's bash syntax. In PowerShell
use `$env:NAME = "value"`. Note `set NAME=value` works only in `cmd.exe` and will
silently do nothing useful in PowerShell.

**Publishing 404s on the images** — Pages hadn't rebuilt yet. The `wait` stage
exists for this; if it times out, confirm Pages is building from `/docs`.

**A run failed partway — do I pay for it again?** No. Re-run it with
`resume_from_run` set to the failed run's ID and it reuses the recipe and photo
that run already generated. See
[When a run fails](#when-a-run-fails-dont-pay-for-it-twice). Artifacts expire
after 14 days, so salvage within two weeks.
