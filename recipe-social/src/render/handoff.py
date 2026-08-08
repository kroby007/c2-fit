"""The phone page for posting by hand.

Manual posting does not actually need the TikTok API — it needs the three
slides and the caption to be on your phone. Downloading a workflow artifact on
a laptop and transferring PNGs is the whole friction; a page on the Pages site
removes it. Open one URL, long-press each image to save it, tap to copy the
caption, post.

Written to docs/today.html — a stable URL, so it can be bookmarked or added to
a home screen once and never revisited as a link.

Deliberately self-contained: no external CSS, fonts, or scripts, because the
one place this gets opened is a phone on mobile data, and a blocked CDN would
mean no page at all.
"""
from __future__ import annotations

import datetime
import html
import pathlib

from .. import config
from ..recipes.schema import Post

PAGE_NAME = "today.html"

_CSS = """
*, *::before, *::after { box-sizing: border-box; }
body {
  margin: 0; padding: 20px 16px 64px;
  background: #14110F; color: #F5EFE6;
  font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  -webkit-text-size-adjust: 100%;
}
.wrap { max-width: 560px; margin: 0 auto; }
h1 { font-size: 21px; margin: 0 0 2px; letter-spacing: -0.01em; }
.date { color: #A89C8E; font-size: 14px; margin: 0 0 22px; }
.steps {
  background: #1E1A17; border: 1px solid #3A332E; border-radius: 12px;
  padding: 14px 16px 14px 34px; margin: 0 0 26px; font-size: 14.5px; color: #D8CEC2;
}
.steps li { margin: 5px 0; }
h2 {
  font-size: 12px; text-transform: uppercase; letter-spacing: 0.09em;
  color: #A89C8E; margin: 30px 0 10px; font-weight: 700;
}
figure { margin: 0 0 16px; }
figure img {
  display: block; width: 100%; height: auto; border-radius: 12px;
  border: 1px solid #3A332E; background: #1E1A17;
}
figcaption { color: #A89C8E; font-size: 13px; margin-top: 7px; }
.caption-box {
  background: #1E1A17; border: 1px solid #3A332E; border-radius: 12px;
  padding: 15px; white-space: pre-wrap; word-wrap: break-word;
  font-size: 15px; margin: 0 0 12px;
}
/* The title is one line and gets read at a glance before copying, so it is set
   larger and heavier than the caption body rather than sharing its type. */
.title-box { font-size: 19px; font-weight: 700; white-space: normal; }
button {
  width: 100%; padding: 15px; font-size: 16px; font-weight: 700;
  color: #14110F; background: #FF4D3D; border: 0; border-radius: 12px;
  cursor: pointer; font-family: inherit;
}
button:active { opacity: 0.75; }
button.done { background: #35D07F; }
.note {
  color: #A89C8E; font-size: 13.5px; margin-top: 30px;
  border-top: 1px solid #3A332E; padding-top: 16px;
}
.held {
  background: #3A2018; border: 1px solid #FF4D3D; border-radius: 12px;
  padding: 15px; margin: 0 0 24px; font-size: 14.5px;
}
.held strong { color: #FF9A8F; }
"""

_SCRIPT = """
// One handler for every copy button, keyed by data-copy, so adding another
// copyable block is markup only.
document.querySelectorAll('button[data-copy]').forEach(function (button) {
  button.addEventListener('click', async function () {
    var source = document.querySelector(this.getAttribute('data-copy'));
    try {
      await navigator.clipboard.writeText(source.innerText);
    } catch (err) {
      // Older mobile browsers, and any page not served over HTTPS, have no
      // clipboard API. Selecting the text at least leaves one tap to copy.
      var range = document.createRange();
      range.selectNodeContents(source);
      var selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      this.textContent = 'Press and hold the text to copy';
      return;
    }
    this.textContent = 'Copied';
    this.classList.add('done');
  });
});
"""


def _held_banner(post: Post) -> str:
    if not post.held:
        return ""
    reasons = "".join(f"<li>{html.escape(r)}</li>" for r in post.hold_reasons)
    return (
        '<div class="held"><strong>The quality gate held this post.</strong>'
        f"<ul>{reasons}</ul>Read it over before posting.</div>"
    )


def render_page(post: Post, urls: list[str]) -> str:
    recipe = post.recipe
    account = config.brand()["account"]

    try:
        pretty_date = datetime.date.fromisoformat(post.date).strftime("%A %d %B %Y")
    except ValueError:
        pretty_date = post.date

    figures = "".join(
        f'<figure><img src="{html.escape(url)}" alt="Slide {i}" loading="lazy">'
        f"<figcaption>Slide {i} of {len(urls)}</figcaption></figure>"
        for i, url in enumerate(urls, 1)
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Post today — {html.escape(account['name'])}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
  <h1>{html.escape(recipe.title)}</h1>
  <p class="date">{html.escape(pretty_date)} &middot; {html.escape(account['handle'])}</p>

  {_held_banner(post)}

  <ol class="steps">
    <li>Long-press each image below and save it, in order.</li>
    <li>In TikTok: <strong>+</strong> &rarr; Upload &rarr; select all three, keeping the order.</li>
    <li>Tap <em>Copy title</em> or <em>Copy caption</em> and paste where you need it.</li>
    <li>Pick a trending sound, post.</li>
  </ol>

  <h2>Slides</h2>
  {figures}

  <h2>Title</h2>
  <div class="caption-box title-box" id="title">{html.escape(recipe.title)}</div>
  <button type="button" data-copy="#title">Copy title</button>

  <h2>Caption</h2>
  <div class="caption-box" id="caption">{html.escape(post.full_caption)}</div>
  <button type="button" data-copy="#caption">Copy caption</button>

  <p class="note">Picking the sound is the one step no API can do — TikTok has
  no parameter that takes a sound ID. So it is yours either way, and this page
  is the rest of the work already done.</p>
</div>
<script>{_SCRIPT}</script>
</body>
</html>
"""


def write_page(post: Post, urls: list[str]) -> pathlib.Path:
    """Write docs/today.html for the given post. Returns the path written."""
    path = config.DOCS_DIR / PAGE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_page(post, urls), encoding="utf-8")
    return path
