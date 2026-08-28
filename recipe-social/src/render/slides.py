"""Render recipe carousel slides: HTML/CSS -> headless Chromium -> PNG.

Same technique as product/moving-guide/build-pdf.py elsewhere in this repo, with
--screenshot instead of --print-to-pdf. Chromium gives real typography and layout
for free, which an image library would not.

Fonts and the hero photo are inlined as data URIs rather than file:// references
so Chromium never has to reach outside the single HTML file it is handed.
"""
from __future__ import annotations

import base64
import functools
import html
import pathlib
import subprocess
import tempfile

from .. import config
from ..recipes.schema import Recipe

TEMPLATE_DIR = pathlib.Path(__file__).parent / "templates"

FONT_FILES = {
    "FONT_ANTON": "Anton-Regular.ttf",
    "FONT_INTER_REGULAR": "Inter-Regular.ttf",
    "FONT_INTER_BOLD": "Inter-Bold.ttf",
    "FONT_INTER_BLACK": "Inter-Black.ttf",
}


@functools.lru_cache(maxsize=None)
def _font_data_uri(filename: str) -> str:
    raw = (config.FONTS_DIR / filename).read_bytes()
    return f"data:font/ttf;base64,{base64.b64encode(raw).decode()}"


def _image_data_uri(image_bytes: bytes) -> str:
    # Chromium sniffs the actual format, so the declared type only needs to be
    # an image type; PNG is a safe label for both PNG and JPEG payloads here.
    return f"data:image/png;base64,{base64.b64encode(image_bytes).decode()}"


def _fill(template: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def _title_size(title: str) -> int:
    """Pick a headline size that keeps long titles inside the canvas.

    Chromium has no reliable pure-CSS fit-to-box, and titles vary from
    "Chili Crisp Eggs" to "Sheet Pan Harissa Chicken and Chickpeas". Bucketing on
    length is crude but deterministic, which matters more than optimal here.
    """
    n = len(title)
    if n <= 16:
        return 132
    if n <= 24:
        return 112
    if n <= 34:
        return 94
    if n <= 46:
        return 78
    return 66


# Vertical room each slide leaves its list, measured from the rendered slides
# rather than guessed. Slide 2 gives the ingredients what is left of the panel
# once the photo strip, the macro chips, the heading and the serves/time/cost
# footer have taken their share; slide 3 is a full-height panel of steps with
# only a heading, a title and the CTA above and below it, so it has far more.
INGREDIENT_BUDGET_PX = 465
STEP_BUDGET_PX = 720

# Type never shrinks past this. Below it the slide stops being readable at the
# size anyone actually views it, and the right answer is a shorter recipe —
# niche.yaml caps ingredients at 10 for exactly this reason.
MIN_LIST_SIZE = 22
MAX_LIST_SIZE = 36


def _row_height(size: int, pad: int) -> float:
    """What one list row costs: line box, padding both sides, and the rule."""
    return size * 1.28 + 2 * pad + 2


def _list_metrics(count: int, longest: int, budget: int) -> tuple[int, int]:
    """Largest type that fits `count` rows into `budget` pixels.

    Solved against the budget rather than read off a table of counts. The table
    was tuned by eye and quietly overflowed: nine ingredients came to roughly
    850px of content in a 740px panel, so the serves/time/cost footer was pushed
    off the bottom edge of the slide and simply cut in half.
    """
    if count <= 0:
        return MAX_LIST_SIZE, 20
    for size in range(MAX_LIST_SIZE, MIN_LIST_SIZE - 1, -1):
        # Padding tightens faster than the type, so dense lists close up rather
        # than turning into small text swimming in whitespace.
        pad = max(6, round(size * 0.55) - (MAX_LIST_SIZE - size))
        # A very long line wraps to two rows and costs the budget twice.
        rows = count + (1 if longest > 78 else 0)
        if rows * _row_height(size, pad) <= budget:
            return size, pad
    return MIN_LIST_SIZE, 6


def palette_for(theme: str = "") -> dict:
    """The colour set for one post.

    Named themes rotate per post. The accent used to be the recipe's first
    earned series colour, which sounded varied and was not: high_protein is
    first in the config and almost every recipe earns it, so every slide came
    out the same orange-red.

    An unknown or empty name falls back to the base palette, so a post saved
    before themes existed still renders.
    """
    base = dict(config.brand()["palette"])
    themes = config.brand().get("themes") or {}
    base.setdefault("accent", next(iter(themes.values()))["accent"] if themes else "#FF5A36")
    if theme in themes:
        base.update(themes[theme])
    return base


def _base_css(
    recipe: Recipe, title_size: int, list_size: int, list_pad: int, theme: str = ""
) -> str:
    brand = config.brand()
    palette = palette_for(theme)
    canvas = brand["canvas"]
    css = (TEMPLATE_DIR / "base.css").read_text()
    values = {
        "BG": palette["bg"],
        "SURFACE": palette["surface"],
        "SURFACE_ALT": palette["surface_alt"],
        "TEXT": palette["text"],
        "TEXT_MUTED": palette["text_muted"],
        "HAIRLINE": palette["hairline"],
        "ACCENT": palette["accent"],
        "WIDTH": str(canvas["width"]),
        "HEIGHT": str(canvas["height"]),
        "TITLE_SIZE": str(title_size),
        "LIST_SIZE": str(list_size),
        "LIST_PAD": str(list_pad),
    }
    values.update({key: _font_data_uri(name) for key, name in FONT_FILES.items()})
    return _fill(css, values)


def _badges_html(recipe: Recipe) -> str:
    series = config.brand()["series"]
    return "".join(
        f'<span class="badge" style="--badge-color:{series[key]["color"]}">'
        f'{series[key]["emoji"]} {html.escape(series[key]["label"])}</span>'
        for key in recipe.series
        if key in series
    )


def _macros_html(recipe: Recipe) -> str:
    out = []
    for spec in config.brand()["macros"]:
        value = getattr(recipe.macros, spec["key"])
        out.append(
            '<div class="macro">'
            f'<div class="value">{value}{html.escape(spec["unit"])}</div>'
            f'<div class="label">{html.escape(spec["label"])}</div>'
            "</div>"
        )
    return "".join(out)


def render_slides(
    recipe: Recipe, hero_image: bytes, out_dir: pathlib.Path, theme: str = ""
) -> list[pathlib.Path]:
    """Render the three carousel slides. Returns PNG paths in carousel order."""
    brand = config.brand()
    account = brand["account"]
    canvas = brand["canvas"]
    out_dir.mkdir(parents=True, exist_ok=True)

    ingredient_rows = [i.display() for i in recipe.ingredients]
    ing_size, ing_pad = _list_metrics(
        len(ingredient_rows), max(map(len, ingredient_rows), default=0), INGREDIENT_BUDGET_PX)
    step_size, step_pad = _list_metrics(
        len(recipe.steps), max(map(len, recipe.steps), default=0), STEP_BUDGET_PX)

    hero_uri = _image_data_uri(hero_image)
    title_size = _title_size(recipe.title)

    ingredients_html = "".join(
        f'<li><span class="qty">{html.escape(i.qty)}</span>'
        f'<span class="item">{html.escape(i.item)}</span></li>'
        for i in recipe.ingredients
    )
    steps_html = "".join(
        f'<li><span class="n">{n}</span><span>{html.escape(step)}</span></li>'
        for n, step in enumerate(recipe.steps, 1)
    )

    slides = [
        (
            "slide1.html",
            {
                "BASE_CSS": _base_css(recipe, title_size, ing_size, ing_pad, theme),
                "HERO": hero_uri,
                "HANDLE": html.escape(account["handle"]),
                "BADGES": _badges_html(recipe),
                "TITLE": html.escape(recipe.title),
                "HOOK": html.escape(recipe.hook),
            },
        ),
        (
            "slide2.html",
            {
                "BASE_CSS": _base_css(recipe, title_size, ing_size, ing_pad, theme),
                "HERO": hero_uri,
                "HANDLE": html.escape(account["handle"]),
                "SLIDE_MARKER": "2 / 3",
                "MACROS": _macros_html(recipe),
                "INGREDIENTS": ingredients_html,
                "SERVINGS": str(recipe.servings),
                "TOTAL_MINUTES": str(recipe.total_minutes),
                "COST": f"{recipe.cost_per_serving:.2f}",
            },
        ),
        (
            "slide3.html",
            {
                "BASE_CSS": _base_css(recipe, title_size, step_size, step_pad, theme),
                "HANDLE": html.escape(account["handle"]),
                "SLIDE_MARKER": "3 / 3",
                "TITLE": html.escape(recipe.title),
                "STEPS": steps_html,
                "CTA": html.escape(account["cta"]),
                "DISCLAIMER": html.escape(brand["disclaimer"]),
            },
        ),
    ]

    chrome = config.chrome_binary()
    paths: list[pathlib.Path] = []
    for index, (template_name, values) in enumerate(slides, 1):
        markup = _fill((TEMPLATE_DIR / template_name).read_text(), values)
        png_path = out_dir / f"slide{index}.png"
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as handle:
            handle.write(markup)
            html_path = handle.name
        try:
            result = subprocess.run(
                [
                    chrome, "--headless=new", "--no-sandbox", "--disable-gpu",
                    "--hide-scrollbars", "--force-device-scale-factor=1",
                    f"--window-size={canvas['width']},{canvas['height']}",
                    # Give fonts and the inlined image a moment to settle before capture.
                    "--virtual-time-budget=3000",
                    # as_uri() rather than an f-string: a Windows path is
                    # C:\...\x.html, and "file://C:\..." is not a URL Chrome loads.
                    f"--screenshot={png_path}", pathlib.Path(html_path).as_uri(),
                ],
                capture_output=True, text=True, timeout=120,
            )
        finally:
            pathlib.Path(html_path).unlink(missing_ok=True)

        if not png_path.exists():
            raise RuntimeError(
                f"Chromium produced no PNG for slide {index} "
                f"(rc={result.returncode}): {result.stderr[-600:]}"
            )
        paths.append(png_path)

    return paths


def png_dimensions(path: pathlib.Path) -> tuple[int, int]:
    """Read width/height straight from the PNG IHDR — avoids a Pillow dependency."""
    header = path.read_bytes()[:24]
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG")
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")
