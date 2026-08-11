# C2 Fit — setup checklist

Everything is built and tested. These are the steps only you can do.

Full detail for any step is in [`recipe-social/README.md`](recipe-social/README.md).

**Steps 1–5 are the whole system.** They need no TikTok developer account, no
app review, and no approval from anyone — at the end of them a new post is built
for you every morning and posting it takes about a minute on your phone.

Steps 6–11 are optional and can wait indefinitely. All they buy is skipping the
image-saving step.

> **This repo must stay public.** TikTok fetches every carousel image over plain
> HTTPS with no credentials, so the Pages site has to be anonymously readable.
> That is why the project lives here rather than inside a private repo.

---

## 1. Enable GitHub Pages

Settings → Pages → Source: **Deploy from a branch** → branch `main`, folder
**`/docs`**

Wait for the build, then open the URL. It should be
`https://kroby007.github.io/c2-fit`.

This site does double duty: it hosts the slide images at a URL TikTok will
accept, and it supplies the website / privacy / terms URLs the app registration
demands.

## 2. Set `PAGES_BASE_URL`

Settings → Secrets and variables → Actions → **Variables** tab → New variable

| Name | Value |
|---|---|
| `PAGES_BASE_URL` | `https://kroby007.github.io/c2-fit` |

**No trailing slash.** This must end up byte-identical to the URL prefix you
verify with TikTok in step 7.

## 3. Add the two generation keys

Same page, **Secrets** tab:

| Secret | Where | Cost |
|---|---|---|
| `ANTHROPIC_API_KEY` | <https://console.anthropic.com> | ~$0.04–0.06 per post |
| `GEMINI_API_KEY` | <https://aistudio.google.com/apikey> | ~$0.04 per image |

Together: roughly **$3/month** at one post a day.

**Gemini image generation has no free tier** — enable billing on the Google Cloud
project behind the key, or every run fails with a quota error. Neither key is
covered by a Claude Pro or Google One subscription; the APIs bill separately from
any consumer plan.

## 4. Make your first post by hand

You can do this right now — no TikTok approval needed. Two ways; pick one.

### Easiest: run it on GitHub, install nothing

Actions tab → **Daily recipe post** → **Run workflow** → tick **`manual`** →
green button.

It builds everything on GitHub's machine, publishes the slides to your own site,
and stops. The run's Summary page then links you to
`https://kroby007.github.io/c2-fit/today.html` — open that on your phone and
post from it.

This needs nothing installed, and it's the same machine the daily job uses, so
what you see is what will post.

### Or run it locally

Needs **Python 3.10+** ([python.org](https://www.python.org/downloads/) — tick
*Add python.exe to PATH* in the installer) and **Google Chrome**.

**Windows (PowerShell)** — right-click the Start button → *Terminal*:

```powershell
cd path\to\c2-fit\recipe-social
pip install -r requirements.txt
$env:ANTHROPIC_API_KEY = "sk-ant-..."
$env:GEMINI_API_KEY = "..."
python -m src.cli run --no-publish
```

**macOS / Linux:**

```bash
cd path/to/c2-fit/recipe-social
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
export GEMINI_API_KEY=...
python -m src.cli run --no-publish
```

`$env:NAME = "..."` is PowerShell's `export`, and it lasts only for that window —
reopen the terminal and you set them again. Don't use `set NAME=...`; that's the
old `cmd.exe` syntax and won't apply in PowerShell.

Slides and caption land in `out/<today>/`. Post them manually.

This is also your first real look at the AI food photography. **If it doesn't
look appetizing, say so** — swapping to a better image model is a one-line config
change, and it's much cheaper to find out now than after 30 posts.

## 5. Turn on manual mode — and you're done for now

Settings → Secrets and variables → Actions → **Variables** → New variable:

| Name | Value |
|---|---|
| `MANUAL_MODE` | `true` |

Now the daily job does everything except the final API call: it writes the
recipe, generates the photo, renders the slides, runs the quality gate, and
publishes them to a page on your own site.

Each morning, open this on your phone:

**`https://kroby007.github.io/c2-fit/today.html`**

Save the three images, tap **Copy caption**, and post. About a minute.

Add it to your home screen — the URL never changes.

The schedule is already live: `daily-post.yml` runs at **15:00 UTC** every day,
so the page refreshes itself each morning without you doing anything. Nothing
else to turn on.

**This needs no TikTok developer app at all.** Everything below is optional, and
only removes the file-saving step: even with full API access, drafts mode still
means opening TikTok and picking a sound yourself. Run this way for a few weeks
first. If the daily minute starts to grate, then do the steps below.

---

## Optional, later: the TikTok API

> Skip this entirely unless manual posting is annoying you. It takes days of
> review to save ~60 seconds a day.

## 6. Register the TikTok app

First, **replace `hello@example.com`** in `docs/privacy.html` and
`docs/terms.html` with a real address. TikTok's reviewers read those pages.

Then at <https://developers.tiktok.com>:

- **Website URL** → `https://kroby007.github.io/c2-fit`
- **Privacy Policy** → `https://kroby007.github.io/c2-fit/privacy.html`
- **Terms of Service** → `https://kroby007.github.io/c2-fit/terms.html`
- Add the **Content Posting API** product
- Request scopes `user.info.basic` and `video.upload`
  (add `video.publish` only later, when going for the audit)
- Add a redirect URI of exactly `https://kroby007.github.io/c2-fit/oauth.html`

## 7. Verify your URL prefix

Developer portal → **Manage URL properties** → add your prefix → download the
verification file → commit it to `docs/` → push → wait for Pages → click Verify.

**Everything hinges on this step.** Carousel images are pull-from-URL only, and
TikTok refuses to fetch from a prefix you haven't proven you own. Skip it and
publishing fails with `url_ownership_unverified`.

(It's also why `raw.githubusercontent.com` can't be used — you can't place a
verification file on a domain you don't own.)

## 8. Mint a refresh token

```bash
export TIKTOK_CLIENT_KEY=...
export TIKTOK_CLIENT_SECRET=...
export PAGES_BASE_URL=https://kroby007.github.io/c2-fit
python scripts/tiktok_auth.py
```

Add three secrets: `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, and the printed
`TIKTOK_REFRESH_TOKEN`.

**Optional but recommended:** a `GH_PAT` secret — a fine-grained PAT for this
repo with **Secrets: read and write**. TikTok rotates the refresh token on every
use, and this lets the job store the new one automatically. Without it, each run
warns and you copy the token over by hand.

---

## 9. Check everything

```bash
python -m src.cli doctor
```

Posts nothing. Every failure tells you its own fix.

The line to read carefully is **Connected account** — it compares the account
your token authorizes against the handle on the slides. If you authorized
anything other than `@c2_fit_`, this is where you find out, instead of when a
post lands somewhere unexpected.

Then run the **Preflight (check setup)** workflow from the Actions tab. That
checks your *Actions secrets*, which is where they actually live — `doctor` on
your laptop only proves your laptop works.

## 10. First live post

```bash
python -m src.cli run
```

Open TikTok → **Drafts**. The carousel should be there with all three slides in
order and the caption intact. Add a trending sound and post.

> Picking the sound yourself is the whole reason for drafts mode: no API accepts
> a sound ID, so this is the only way to control the song.

## 11. Turn on the schedule

`.github/workflows/daily-post.yml` already runs at 15:00 UTC daily.

Run it once manually first with **dry run** ticked — it builds everything and
prints the exact payloads without sending anything.

---

## Later

- **Instagram and Facebook** — publishers are built and tested, just switched
  off. See [Other platforms](recipe-social/README.md#other-platforms-later).
- **Fully automatic TikTok** — pass the Content Posting API audit, then set the
  `TIKTOK_POST_MODE` variable to `DIRECT_POST`. TikTok picks the sound instead of
  you, and before the audit passes every direct post is forced to `SELF_ONLY`.
- **Tune the content** — `recipe-social/config/niche.yaml` is the recipe brief,
  `brand.yaml` the look and the badge rules, `hashtags.yaml` the tag pools.
