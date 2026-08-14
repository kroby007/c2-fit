"""End-to-end pipeline orchestration.

Only the two calls that need credentials are stubbed — recipe generation and
image generation. Everything else runs for real: caption composition, Chromium
rendering, the quality gate, the hold path, and staging to public URLs. This is
the `run --no-publish` path a first-time user executes.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src import cli, config  # noqa: E402
from src.images.provider import ImageProvider  # noqa: E402
from src.recipes.schema import Post, Recipe  # noqa: E402

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
DATE = "2026-07-26"


def _chrome_available() -> bool:
    try:
        config.chrome_binary()
        return True
    except RuntimeError:
        return False


pytestmark = pytest.mark.skipif(not _chrome_available(), reason="No Chromium/Chrome available")


class _StubImageProvider(ImageProvider):
    """Renders a gradient with Chromium so no image API key is needed."""

    def generate(self, prompt: str, aspect_ratio: str) -> bytes:
        assert "The dish:" in prompt, "prompt must carry the dish description"
        assert aspect_ratio == config.brand()["photography"]["aspect_ratio"]
        tmp = pathlib.Path(config.OUT_DIR) / "_stub_hero"
        tmp.mkdir(parents=True, exist_ok=True)
        html_path, png_path = tmp / "h.html", tmp / "h.png"
        html_path.write_text(
            "<!doctype html><html><head><style>html,body{margin:0;width:1080px;"
            "height:1440px;overflow:hidden}body{background:linear-gradient("
            "150deg,#C8541F,#4E6B22 60%,#14110F)}</style></head><body></body></html>"
        )
        subprocess.run(
            [config.chrome_binary(), "--headless=new", "--no-sandbox", "--disable-gpu",
             "--hide-scrollbars", "--window-size=1080,1440",
             f"--screenshot={png_path}", f"file://{html_path}"],
            capture_output=True, timeout=120,
        )
        return png_path.read_bytes()


@pytest.fixture
def wired(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect all writable paths into tmp and stub the two credentialed calls."""
    monkeypatch.setattr(config, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    # DOCS_DIR as well as MEDIA_DIR: today.html is written straight into docs/,
    # and it is a live file — the page the phone opens every morning. A test run
    # that forgets this quietly replaces the real post with fixture data, and the
    # damage only shows up on the published site.
    monkeypatch.setattr(config, "DOCS_DIR", tmp_path / "docs")
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path / "docs" / "media")
    monkeypatch.setenv("PAGES_BASE_URL", "https://example.github.io/c2-fit")

    from src.state import queue

    monkeypatch.setattr(queue, "HISTORY_PATH", tmp_path / "state" / "history.json")

    def fake_generate(exclude_titles=None, exclude_methods=None, exclude_proteins=None,
                        exclude_cuisines=None):
        return Recipe.from_dict(json.loads((FIXTURES / "recipe_good.json").read_text()))

    monkeypatch.setattr("src.recipes.generate.generate_recipe", fake_generate)
    monkeypatch.setattr("src.images.provider.get_provider", lambda name=None: _StubImageProvider())
    return tmp_path


def _run(*argv: str) -> None:
    cli.main(["--date", DATE, *argv])


def test_run_no_publish_produces_postable_assets(wired: pathlib.Path) -> None:
    _run("run", "--no-publish", "--no-check-image")

    post_dir = config.OUT_DIR / DATE
    for name in ("slide1.png", "slide2.png", "slide3.png", "hero.png", "caption.txt", "post.json"):
        assert (post_dir / name).exists(), f"{name} missing"

    caption = (post_dir / "caption.txt").read_text()
    assert "44g protein" in caption
    assert "#" in caption, "hashtags should be appended to the caption file"

    post = Post.load(post_dir / "post.json")
    assert not post.held
    assert post.recipe.series == ["high_protein", "budget"]
    assert len(post.slide_paths) == 3


def test_stage_produces_verified_prefix_urls(wired: pathlib.Path) -> None:
    _run("run", "--no-publish", "--no-check-image")
    _run("stage")

    post = Post.load(config.OUT_DIR / DATE / "post.json")
    assert len(post.slide_urls) == 3
    for i, url in enumerate(post.slide_urls, 1):
        assert url == f"https://example.github.io/c2-fit/media/{DATE}/slide{i}.png"
        # The file has to actually be in the published directory, not just named.
        assert (config.MEDIA_DIR / DATE / f"slide{i}.png").exists()


def test_bad_recipe_is_held_and_never_published(
    wired: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def bad_generate(exclude_titles=None, exclude_methods=None, exclude_proteins=None,
                        exclude_cuisines=None):
        return Recipe.from_dict(json.loads((FIXTURES / "recipe_bad_macros.json").read_text()))

    monkeypatch.setattr("src.recipes.generate.generate_recipe", bad_generate)
    _run("run", "--no-publish", "--no-check-image")

    assert not (config.OUT_DIR / DATE).exists(), "held post must be moved out of the live folder"
    held_dir = config.OUT_DIR / "held" / DATE
    assert held_dir.exists()

    post = Post.load(held_dir / "post.json")
    assert post.held
    assert any("do not add up" in r for r in post.hold_reasons)
    assert "POST HELD" in capsys.readouterr().out


def test_second_run_is_blocked_by_the_already_posted_guard(
    wired: pathlib.Path, capsys: pytest.CaptureFixture
) -> None:
    from src.state import queue

    queue.record(DATE, "chili-crisp-chicken-bowls", "Chili Crisp Chicken Bowls", ["#foodtok"])
    _run("run", "--no-publish", "--no-check-image")
    assert "Already posted" in capsys.readouterr().out


def test_dry_run_publish_sends_nothing_to_the_platform(
    wired: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dry run skips the API call — it does not un-publish what staging did.

    Staging copies the slides onto the live site and rewrites the phone page, so
    the recipe really has gone out and the history has to say so. What the dry
    run must leave empty is the platform result.
    """
    monkeypatch.setenv("TIKTOK_POST_MODE", "MEDIA_UPLOAD")
    _run("run", "--no-publish", "--no-check-image")
    _run("stage")
    _run("publish", "--dry-run", "--platforms", "tiktok")

    post = Post.load(config.OUT_DIR / DATE / "post.json")
    assert post.published["tiktok"]["ok"]
    assert "DRY RUN" in post.published["tiktok"]["message"]

    from src.state import queue

    entry = json.loads(queue.path().read_text())[-1]
    assert entry["title"] == post.recipe.title, "staging put the post on the site"
    assert entry["published"] == {}, "a dry run must not record a platform result"


def test_publish_defaults_to_tiktok_only(
    wired: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Meta must not be touched by a default run while TikTok is being proven out."""
    monkeypatch.setenv("TIKTOK_POST_MODE", "MEDIA_UPLOAD")
    _run("run", "--no-publish", "--no-check-image")
    _run("stage")
    _run("publish", "--dry-run")  # no --platforms

    post = Post.load(config.OUT_DIR / DATE / "post.json")
    assert set(post.published) == {"tiktok"}
    assert cli.DEFAULT_PLATFORMS == ("tiktok",)


def test_meta_publishers_are_dormant_not_broken(
    wired: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Naming them explicitly still works, so turning them on later is a flag."""
    monkeypatch.setenv("IG_USER_ID", "fake")
    monkeypatch.setenv("META_ACCESS_TOKEN", "fake")
    monkeypatch.setenv("FB_PAGE_ID", "fake")
    _run("run", "--no-publish", "--no-check-image")
    _run("stage")
    _run("publish", "--dry-run", "--platforms", "instagram,facebook")

    post = Post.load(config.OUT_DIR / DATE / "post.json")
    assert post.published["instagram"]["ok"]
    assert post.published["facebook"]["ok"]
    assert "tiktok" not in post.published


def test_slides_carry_the_configured_handle(wired: pathlib.Path) -> None:
    """The handle is burned into every slide, so a stale brand config is silent."""
    from src.render import slides as slides_mod

    handle = config.brand()["account"]["handle"]
    assert handle == "@c2_fit_"

    recipe = Recipe.from_dict(json.loads((FIXTURES / "recipe_good.json").read_text()))
    css = slides_mod._base_css(recipe, 94, 33, 16)
    markup = slides_mod._fill(
        (slides_mod.TEMPLATE_DIR / "slide1.html").read_text(),
        {"BASE_CSS": css, "HERO": "", "HANDLE": handle, "BADGES": "",
         "TITLE": recipe.title, "HOOK": recipe.hook},
    )
    assert handle in markup


def test_manual_run_writes_a_postable_phone_page(wired: pathlib.Path) -> None:
    """The manual path has to be self-sufficient: no API, no file transfer.

    Everything needed to post by hand must be on this one page, at the public
    URLs, or the whole point of it is lost.
    """
    _run("run", "--manual", "--no-check-image")

    page_path = config.DOCS_DIR / "today.html"
    assert page_path.exists(), "manual mode must write the phone page"
    page = page_path.read_text(encoding="utf-8")

    post = Post.load(config.OUT_DIR / DATE / "post.json")
    assert len(post.slide_urls) == 3

    # Public URLs, not local paths — the page is opened on a phone.
    for url in post.slide_urls:
        assert url in page
        assert url.startswith("https://")
    assert "out/" not in page, "must not leak local working paths"

    # The caption has to be present in full, hashtags included.
    assert post.recipe.title in page
    assert post.hashtags[0] in page
    assert "Copy caption" in page

    # The title is copyable on its own, and its button targets the title block
    # rather than the caption — an easy thing to get backwards.
    assert "Copy title" in page
    assert 'data-copy="#title"' in page
    assert 'id="title"' in page
    assert page.index('id="title"') < page.index('id="caption"'), \
        "the title block must come above the caption block"

    # Self-contained: a phone on mobile data with a blocked CDN still renders it.
    for offsite in ("http://fonts.", "https://fonts.", "cdn.", "<link"):
        assert offsite not in page, f"page must not depend on {offsite}"


def test_manual_run_sends_nothing_and_records_nothing(
    wired: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Manual mode must stop short of TikTok even with credentials present."""
    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "fake")
    monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "fake")
    monkeypatch.setenv("TIKTOK_REFRESH_TOKEN", "fake")

    def explode(*args, **kwargs):
        raise AssertionError("manual mode must not reach a publisher")

    monkeypatch.setattr("src.publish.tiktok.TikTokPublisher.publish", explode)
    _run("run", "--manual", "--no-check-image")

    post = Post.load(config.OUT_DIR / DATE / "post.json")
    assert post.published == {}


def test_a_repeated_recipe_is_asked_for_again_before_anything_is_rendered(
    wired: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Tightening the repeat rules is only safe because a repeat is retried.

    The retry has to happen in generate, before the image is bought: a repeat
    caught by the gate costs the whole day, and one caught here costs cents.
    """
    from src.state import queue

    queue.record("2026-07-20", "chili-crisp-chicken-bowls", "Chili Crisp Chicken Bowls",
                 [], method="skillet", protein="chicken")

    seen = []
    base = json.loads((FIXTURES / "recipe_good.json").read_text())

    def repeats_once(exclude_titles=None, exclude_methods=None, exclude_proteins=None,
                        exclude_cuisines=None):
        seen.append(list(exclude_titles or []))
        title = ("Chili Crisp Chicken Bowls" if len(seen) == 1
                 else "Sheet-Pan Harissa Salmon")
        return Recipe.from_dict({**base, "title": title})

    monkeypatch.setattr("src.recipes.generate.generate_recipe", repeats_once)
    images = []
    monkeypatch.setattr(
        "src.images.provider.get_provider",
        lambda name=None: images.append(1) or _StubImageProvider(),
    )

    _run("generate")

    assert len(seen) == 2, "the repeat should have been asked about again"
    assert images == [], "no image may be bought while the recipe is still a repeat"
    assert "Chili Crisp Chicken Bowls" in seen[1], \
        "the rejected title must be excluded from the retry, or it just rephrases"

    post = Post.load(config.OUT_DIR / DATE / "post.json")
    assert post.recipe.title == "Sheet-Pan Harissa Salmon"
    assert "Asking for a different one" in capsys.readouterr().out


def test_retries_are_capped_and_fall_through_to_the_gate(
    wired: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """A model stuck in a rut must not bill forever, nor post a silent repeat."""
    from src.state import queue

    queue.record("2026-07-20", "chili-crisp-chicken-bowls", "Chili Crisp Chicken Bowls",
                 [], method="skillet", protein="chicken")

    calls = []

    def always_repeats(exclude_titles=None, exclude_methods=None, exclude_proteins=None,
                        exclude_cuisines=None):
        calls.append(1)
        return Recipe.from_dict(json.loads((FIXTURES / "recipe_good.json").read_text()))

    monkeypatch.setattr("src.recipes.generate.generate_recipe", always_repeats)
    _run("generate")

    assert len(calls) == cli.MAX_GENERATE_ATTEMPTS
    assert "leaving it to the gate" in capsys.readouterr().out

    # And the gate must then actually hold it, rather than the repeat slipping by.
    _run("gate")
    assert Post.load(config.OUT_DIR / DATE / "post.json").held


def test_the_workflows_stage_by_stage_path_records_the_post(wired: pathlib.Path) -> None:
    """The daily job never calls `run` — it invokes each stage in turn.

    Recording used to live inside cmd_run, so production wrote nothing to the
    history while the tests, which do call `run`, passed. The feed produced two
    shrimp dishes back to back with an empty history behind it. This exercises
    the exact sequence daily-post.yml runs.
    """
    from src.state import queue

    _run("generate")
    _run("render", "--no-check-image")
    _run("gate")
    _run("stage")

    post = Post.load(config.OUT_DIR / DATE / "post.json")
    assert queue.recent_titles() == [post.recipe.title]
    assert queue.recent_proteins() == [post.recipe.protein]
    assert queue.recent_cuisines() == [post.recipe.cuisine]
    assert post.recipe.slug in queue.all_slugs()


def test_recording_twice_does_not_duplicate_the_entry(wired: pathlib.Path) -> None:
    """Stage is re-runnable, and publish records the same post again after it."""
    from src.state import queue

    _run("run", "--no-publish", "--no-check-image")
    _run("stage")
    _run("stage")

    entries = json.loads(queue.path().read_text())
    assert len(entries) == 1, "one post, one entry, however many times it staged"


def test_manual_run_records_the_post_in_the_history(wired: pathlib.Path) -> None:
    """Manual mode used to return before the only call that wrote the history.

    Nothing was sent anywhere, so it did not look like a post — but it went on
    the phone page and got posted by hand, and the next day's generator has to
    know that. Leaving it out is what produced three skillets in a row.
    """
    from src.state import queue

    _run("run", "--manual", "--no-check-image")

    post = Post.load(config.OUT_DIR / DATE / "post.json")
    assert queue.recent_titles() == [post.recipe.title]
    assert queue.recent_methods() == [post.recipe.method]
    assert queue.recent_hashtags() == post.hashtags
    assert queue.already_posted_today(DATE), "a manual post must block a second run"


def test_a_manual_run_tells_the_next_one_what_to_avoid(counted: dict) -> None:
    """The recorded method has to actually reach the next generate call."""
    _run("run", "--manual", "--no-check-image")
    assert counted["exclude_methods"] == [], "nothing to avoid on the first run"

    cli.main(["--date", "2026-07-27", "run", "--manual", "--no-check-image"])

    post = Post.load(config.OUT_DIR / DATE / "post.json")
    assert counted["exclude_methods"] == [post.recipe.method]


def test_manual_mode_env_var_matches_the_flag(
    wired: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MANUAL_MODE is how the scheduled job opts in; it must behave as --manual."""
    monkeypatch.setenv("MANUAL_MODE", "true")

    def explode(*args, **kwargs):
        raise AssertionError("MANUAL_MODE=true must not reach a publisher")

    monkeypatch.setattr("src.publish.tiktok.TikTokPublisher.publish", explode)
    _run("run", "--no-check-image")

    assert (config.DOCS_DIR / "today.html").exists()
    assert Post.load(config.OUT_DIR / DATE / "post.json").published == {}


def test_held_post_page_warns_before_it_is_posted(wired: pathlib.Path) -> None:
    """A held post must say so on the page, or the gate is silently bypassed."""
    from src.render import handoff

    recipe = Recipe.from_dict(json.loads((FIXTURES / "recipe_good.json").read_text()))
    held = Post(recipe=recipe, date=DATE, caption="x", hashtags=["#a"],
                held=True, hold_reasons=["macros do not add up"])
    page = handoff.render_page(held, ["https://example.github.io/c2-fit/media/x/s1.png"])
    assert "held this post" in page
    assert "macros do not add up" in page


# --------------------------------------------------------------------------- #
# resuming a failed run
#
# Both generation calls cost real money, and a run that dies late — a bad
# gateway from the image host, a crash in a later stage — has already paid for
# whatever reached out/<date>/. These lock in that a re-run spends nothing on
# work already on disk, and that reuse never outlives the recipe it belongs to.
# --------------------------------------------------------------------------- #

def _spend(counted: dict) -> dict:
    """Only the two counts that cost money, ignoring whatever else was captured."""
    return {"recipe": counted["recipe"], "image": counted["image"]}


@pytest.fixture
def counted(wired: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """Count what a run actually pays for: recipes written, images generated."""
    calls = {"recipe": 0, "image": 0, "exclude_methods": []}
    titles = iter(["First Dish", "Second Dish", "Third Dish"])

    def counting_generate(exclude_titles=None, exclude_methods=None, exclude_proteins=None,
                        exclude_cuisines=None):
        calls["exclude_methods"] = list(exclude_methods or [])
        calls["recipe"] += 1
        base = json.loads((FIXTURES / "recipe_good.json").read_text())
        return Recipe.from_dict({**base, "title": next(titles)})

    stub = _StubImageProvider()
    real_generate = stub.generate

    def counting_image(prompt: str, aspect_ratio: str) -> bytes:
        calls["image"] += 1
        return real_generate(prompt, aspect_ratio)

    monkeypatch.setattr(stub, "generate", counting_image)
    monkeypatch.setattr("src.recipes.generate.generate_recipe", counting_generate)
    monkeypatch.setattr("src.images.provider.get_provider", lambda name=None: stub)
    return calls


def test_rerunning_generate_reuses_the_recipe_on_disk(counted: dict) -> None:
    _run("generate")
    _run("generate")
    assert counted["recipe"] == 1, "the second generate must not pay for a new recipe"
    assert Post.load(config.OUT_DIR / DATE / "post.json").recipe.title == "First Dish"


def test_regenerate_overrides_the_reuse(counted: dict) -> None:
    _run("generate")
    _run("generate", "--regenerate")
    assert counted["recipe"] == 2
    assert Post.load(config.OUT_DIR / DATE / "post.json").recipe.title == "Second Dish"


def test_rerunning_render_reuses_the_hero_image(counted: dict) -> None:
    _run("generate")
    _run("render", "--no-check-image")
    _run("render", "--no-check-image")
    assert counted["image"] == 1, "the second render must not pay for a new image"


def test_new_image_overrides_the_reuse(counted: dict) -> None:
    _run("generate")
    _run("render", "--no-check-image")
    _run("render", "--no-check-image", "--new-image")
    assert counted["image"] == 2


def test_a_resumed_run_costs_nothing_it_already_paid_for(counted: dict) -> None:
    """The case this exists for: a run died after the image, before publishing.

    Re-running it must reach the same finished slides on one recipe and one
    photo — the money is already spent, and the artifacts are right there.
    """
    _run("generate")
    _run("render", "--no-check-image")  # stands in for the run that then died

    _run("run", "--manual", "--no-check-image")

    assert _spend(counted) == {"recipe": 1, "image": 1}
    post = Post.load(config.OUT_DIR / DATE / "post.json")
    assert post.recipe.title == "First Dish"
    assert len(post.slide_urls) == 3


def test_a_regenerated_recipe_never_inherits_the_old_photo(counted: dict) -> None:
    """The trap in reusing by filename: hero.png is a photo of a specific dish.

    Without invalidation the pipeline would pair the new recipe with the old
    plate, and every downstream check would pass — the slides would simply show
    the wrong food.
    """
    _run("generate")
    _run("render", "--no-check-image")
    assert (config.OUT_DIR / DATE / "hero.png").exists()

    _run("generate", "--regenerate")
    assert not (config.OUT_DIR / DATE / "hero.png").exists(), \
        "the old recipe's photo must not survive a new recipe"

    _run("render", "--no-check-image")
    assert counted["image"] == 2, "the new recipe must get its own photo"


def test_force_posts_something_new_rather_than_the_last_recipe(counted: dict) -> None:
    """--force means 'post again today', which has to mean a different post."""
    from src.state import queue

    _run("run", "--manual", "--no-check-image")
    queue.record(DATE, "first-dish", "First Dish", ["#foodtok"])

    _run("run", "--manual", "--no-check-image", "--force")

    assert counted["recipe"] == 2, "--force must not republish the recipe already out"
    assert counted["image"] == 2, "and it must not reuse the previous dish's photo"
    assert Post.load(config.OUT_DIR / DATE / "post.json").recipe.title == "Second Dish"


def test_resume_adopts_a_previous_dates_work(counted: dict) -> None:
    """The Aug 10 case: the run died, and the salvage happens on a later day."""
    cli.main(["--date", "2026-07-25", "generate"])
    cli.main(["--date", "2026-07-25", "render", "--no-check-image"])

    _run("resume")                       # --from-date auto-detected
    _run("run", "--manual", "--no-check-image")

    assert _spend(counted) == {"recipe": 1, "image": 1}, "a resumed day must buy nothing twice"

    post = Post.load(config.OUT_DIR / DATE / "post.json")
    assert post.recipe.title == "First Dish"
    assert post.date == DATE, "the adopted post must carry the new date"
    assert len(post.slide_urls) == 3
    for url in post.slide_urls:
        assert DATE in url and "2026-07-25" not in url, "URLs must not point at the old date"


def test_resume_drops_state_that_described_the_old_date(counted: dict) -> None:
    """Everything downstream of the recipe is about a day that is not this one."""
    cli.main(["--date", "2026-07-25", "generate"])
    cli.main(["--date", "2026-07-25", "render", "--no-check-image"])
    cli.main(["--date", "2026-07-25", "stage"])

    stale = Post.load(config.OUT_DIR / "2026-07-25" / "post.json")
    stale.held = True
    stale.hold_reasons = ["some problem from that day"]
    stale.save(config.OUT_DIR / "2026-07-25" / "post.json")
    assert stale.slide_urls, "the old post must really carry URLs for this to prove anything"

    _run("resume")

    post = Post.load(config.OUT_DIR / DATE / "post.json")
    assert post.slide_paths == [] and post.slide_urls == []
    assert post.published == {}
    assert not post.held and post.hold_reasons == [], "the gate must judge this run afresh"
    assert post.caption and post.hashtags, "caption and hashtags are rebuilt, not dropped"


def test_resume_refuses_to_overwrite_work_already_here(counted: dict) -> None:
    cli.main(["--date", "2026-07-25", "generate"])
    _run("generate")

    with pytest.raises(SystemExit, match="already exists"):
        _run("resume")
    assert Post.load(config.OUT_DIR / DATE / "post.json").recipe.title == "Second Dish"


def test_resume_is_a_no_op_when_the_salvage_is_already_todays_date(
    counted: dict, capsys: pytest.CaptureFixture
) -> None:
    """A run that failed the same day it was meant to post needs no re-dating.

    The workflow runs `resume` unconditionally when given a run ID, so this path
    has to succeed rather than fail the job for having nothing to move.
    """
    _run("generate")
    _run("render", "--no-check-image")

    _run("resume")
    assert "nothing to move" in capsys.readouterr().out

    _run("run", "--manual", "--no-check-image")
    assert _spend(counted) == {"recipe": 1, "image": 1}


def test_resume_says_so_when_there_is_nothing_to_salvage(counted: dict) -> None:
    with pytest.raises(SystemExit, match="Nothing to resume"):
        _run("resume")


def test_resume_ignores_the_held_directory(counted: dict) -> None:
    """out/held/ sits beside the dated folders and is not a date."""
    (config.OUT_DIR / "held").mkdir(parents=True)
    (config.OUT_DIR / "held" / "post.json").write_text("{}")

    with pytest.raises(SystemExit, match="Nothing to resume"):
        _run("resume")


@pytest.mark.parametrize(
    "value,manual",
    [
        ("true", True),
        ("TRUE", True),
        (" true ", True),
        ("1", True),
        ("yes", True),
        # The value someone types when they paste the whole assignment into the
        # value box. It must not read as "publish to TikTok".
        ("MANUAL_MODE = true", True),
        ("", False),
        ("false", False),
        ("0", False),
        ("off", False),
    ],
)
def test_manual_mode_reads_unclear_values_as_manual(
    value: str, manual: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MANUAL_MODE", value)
    assert cli._manual_mode_set() is manual
