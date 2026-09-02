# C2 Fit

Automated recipe carousels for TikTok — [@c2_fit_](https://www.tiktok.com/@c2_fit_).

One recipe becomes three 1080×1350 slides, a caption with emojis and rotated
hashtags, and a post — generated, quality-checked, and published on a schedule.

**Setting this up for the first time? → [`START-HERE.md`](START-HERE.md)**

**How it works, and every knob → [`recipe-social/README.md`](recipe-social/README.md)**

```
generate  →  render  →  stage  →  gate  →  publish
 recipe      hero photo  public   quality   TikTok
 caption     + 3 slides  URLs     checks
 hashtags
```

| Path | What's in it |
|---|---|
| `recipe-social/` | The pipeline — generation, rendering, quality gate, publishers, tests |
| `docs/` | The GitHub Pages site: privacy/terms pages TikTok requires, and the media prefix it fetches images from |
| `.github/workflows/` | `daily-post.yml` (the scheduled run — Tue/Thu/Sat/Sun) and `preflight.yml` (setup check, posts nothing) |

## Two things worth knowing up front

**You pick the song, not the code.** No API accepts a trending sound ID — TikTok
exposes only an `auto_add_music` boolean that lets *its* backend choose. So the
default mode drops finished carousels into your TikTok **drafts**; you tap a
sound and post. That's the one manual step, and it's deliberate.

**This repository is public on purpose.** TikTok fetches every carousel image
anonymously over HTTPS, so the Pages site has to be readable without
credentials. Nothing secret lives here: API keys are Actions secrets, and
`state/*.local` is gitignored.
