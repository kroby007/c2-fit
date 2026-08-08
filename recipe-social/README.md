# C2 Fit — automated recipe carousels

Generates a daily recipe carousel and posts it to TikTok
([@c2_fit_](https://www.tiktok.com/@c2_fit_)). One recipe becomes three
1080×1350 slides, a caption with emojis and rotated hashtags, and a post.

```
generate  →  render  →  stage  →  gate  →  publish
 recipe      hero photo  public   quality   TikTok
 caption     + 3 slides  URLs     checks
 hashtags
```

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

## Phase 0 — start posting today, no API access

TikTok app approval takes real time. You do not have to wait for it.

```bash
cd recipe-social
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...     # recipe generation
export GEMINI_API_KEY=...               # food photography

python -m src.cli run --no-publish
```

That writes `out/<today>/` containing `slide1.png`, `slide2.png`, `slide3.png`,
and `caption.txt`. Airdrop them to your phone and post by hand. Everything from
here is about removing that manual step.

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
| `ANTHROPIC_API_KEY` | <https://console.anthropic.com> | ~$0.01–0.03 per recipe |
| `GEMINI_API_KEY` | <https://aistudio.google.com/apikey> | ~$0.03 per image |

At one post a day that is **under ~$2/month** in total.

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
python -m src.cli run --no-publish    # Phase 0: build assets only

python -m src.cli --date 2026-07-26 render   # re-run one stage
python -m pytest tests/ -q
```

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
| `TIKTOK_POST_MODE` | `MEDIA_UPLOAD` | `DIRECT_POST` for fully automatic (post-audit) |
| `TIKTOK_AUTO_ADD_MUSIC` | `true` | Let TikTok attach a trending sound (DIRECT_POST only) |
| `IMAGE_PROVIDER` | `gemini` | Image backend |
| `GEMINI_IMAGE_MODEL` | `gemini-2.5-flash-image` | `gemini-3-pro-image` for higher quality |
| `RECIPE_MODEL` | `claude-opus-5` | Model for recipes and the image check |
| `RECIPE_EFFORT` | `medium` | Raise to `high` if recipes feel generic |
| `CHROME_BINARY` | auto-discovered | Explicit path to Chrome/Chromium |

---

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

At one post a day, roughly **$1–2/month**: about $0.03 per image and $0.01–0.03
per recipe. GitHub Actions and Pages are free at this volume. TikTok's daily
posting cap is far above one post a day.

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

**`No Chromium/Chrome binary found`** — set `CHROME_BINARY` to its path.

**Publishing 404s on the images** — Pages hadn't rebuilt yet. The `wait` stage
exists for this; if it times out, confirm Pages is building from `/docs`.
