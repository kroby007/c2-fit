#!/usr/bin/env python3
"""Pipeline entry point.

    generate -> render -> stage -> gate -> publish

Each stage reads and writes out/<date>/post.json, so any stage can be re-run on
its own against a previous stage's output. `run` executes the whole chain.

Phase 0 usage — no platform API access required:

    python -m src.cli run --no-publish

writes finished slides and a caption to out/<date>/ for posting by hand.

    python -m src.cli run --manual

goes one better: it also stages the slides to the public site and writes the
phone page, so posting by hand needs no file transfer and no TikTok app.

Nothing generated is bought twice: generate and render reuse whatever a previous
run left in out/<date>/, and `resume` re-dates a failed run's work onto today so
that reuse can reach it.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import pathlib
import shutil
import sys

from . import config, notify
from .caption import compose
from .recipes import quality
from .recipes.schema import Post

ALL_PLATFORMS = ("tiktok", "instagram", "facebook")
# TikTok only by default while it is being proven out. The Instagram and Facebook
# publishers are built and tested; name them with --platforms to bring them back.
DEFAULT_PLATFORMS = ("tiktok",)


def _today() -> str:
    return dt.date.today().isoformat()


def _post_dir(date: str) -> pathlib.Path:
    return config.OUT_DIR / date


def _post_path(date: str) -> pathlib.Path:
    return _post_dir(date) / "post.json"


def _hero_path(date: str) -> pathlib.Path:
    return _post_dir(date) / "hero.png"


def _load(date: str) -> Post:
    path = _post_path(date)
    if not path.exists():
        raise SystemExit(f"No post at {path}. Run the generate stage first.")
    return Post.load(path)


# --------------------------------------------------------------------------- #
# stages
# --------------------------------------------------------------------------- #

def cmd_generate(args: argparse.Namespace) -> None:
    from .recipes.generate import generate_recipe
    from .state import queue

    date = args.date

    # A run that dies after this stage has already paid for the recipe. Reusing
    # it makes the pipeline resumable instead of billing for work that is sitting
    # on disk; --regenerate forces a fresh one.
    if _post_path(date).exists() and not args.regenerate:
        post = _load(date)
        print(f"Reusing the recipe already generated for {date}: {post.recipe.title}")
        print("  (pass --regenerate to write a new one)")
        return

    recipe = generate_recipe(exclude_titles=queue.recent_titles())
    post = Post(recipe=recipe, date=date)
    post.hashtags = compose.build_hashtags(recipe, recent=queue.recent_hashtags())
    post.caption = compose.build_caption(recipe)

    # A hero image belongs to the recipe it was generated for. Writing a new
    # recipe into this directory makes any photo already sitting there a photo of
    # a different dish, so it goes now — otherwise the reuse in cmd_render would
    # cheerfully pair the old plate with the new recipe.
    _hero_path(date).unlink(missing_ok=True)
    post.save(_post_path(date))
    print(f"Generated: {recipe.title}")
    print(f"  {recipe.macros.protein_g}g protein · {recipe.total_minutes} min · "
          f"${recipe.cost_per_serving:.2f}/serving · badges: {', '.join(recipe.series) or 'none'}")
    print(f"  -> {_post_path(date)}")


def _salvageable_dates(target: str) -> list[str]:
    """Dated post directories other than the target, newest first."""
    dates = []
    for path in config.OUT_DIR.glob("*/post.json"):
        name = path.parent.name
        if name == target:
            continue
        try:
            dt.date.fromisoformat(name)
        except ValueError:
            continue  # "held" and anything else that is not a date
        dates.append(name)
    return sorted(dates, reverse=True)


def cmd_resume(args: argparse.Namespace) -> None:
    """Adopt a previous date's generated work as today's post.

    A run that died before publishing still paid for its recipe and its photo.
    Both are dated, though, so a later run looks in a different directory and
    buys them again. This copies them onto the target date, where the normal
    pipeline finds them.

    Only the two paid-for artifacts carry over. Caption and hashtags are rebuilt
    against the current history — they cost nothing, and a week-old hashtag set
    is exactly what the gate holds posts for. Slide paths, staged URLs, and any
    hold reasons all describe the old date and are dropped.
    """
    from .state import queue

    date = args.date
    source = args.from_date
    if not source:
        candidates = _salvageable_dates(date)
        if not candidates:
            # A run that failed on this same date needs no re-dating: generate
            # and render will find its work exactly where it already sits.
            if _post_path(date).exists():
                print(f"The salvaged post is already dated {date} — nothing to move.")
                return
            raise SystemExit(
                f"Nothing to resume: no other dated post found under {config.OUT_DIR}.\n"
                "Download a failed run's artifact into that directory first."
            )
        source = candidates[0]
        if len(candidates) > 1:
            print(f"Found {len(candidates)} salvageable posts; taking the newest.")

    if source == date:
        raise SystemExit(f"--from-date {source} is already the target date.")
    if not _post_path(source).exists():
        raise SystemExit(f"No post at {_post_path(source)}.")
    if _post_path(date).exists():
        raise SystemExit(
            f"{_post_path(date)} already exists — resuming would overwrite it.\n"
            f"Delete {_post_dir(date)} first if that is what you want."
        )

    old = Post.load(_post_path(source))
    post = Post(recipe=old.recipe, date=date)
    post.hashtags = compose.build_hashtags(post.recipe, recent=queue.recent_hashtags())
    post.caption = compose.build_caption(post.recipe)

    _post_dir(date).mkdir(parents=True, exist_ok=True)
    hero = _hero_path(source)
    if hero.exists():
        # Copied rather than moved: the source is a salvage, and leaving it
        # intact means a resume that goes wrong can simply be run again.
        shutil.copy2(hero, _hero_path(date))
    post.save(_post_path(date))

    print(f"Resumed {source} as {date}: {post.recipe.title}")
    print(f"  recipe   reused from {_post_path(source)}")
    print(f"  hero.png {'reused' if hero.exists() else 'MISSING — will be generated'}")
    print("  caption and hashtags rebuilt against the current history")


def cmd_render(args: argparse.Namespace) -> None:
    from .images import prompts
    from .images.provider import get_provider
    from .render.slides import png_dimensions, render_slides

    date = args.date
    post = _load(date)
    out_dir = _post_dir(date)

    hero_path = _hero_path(date)

    # The image is the single most expensive call in the run. If one is already
    # on disk — a resumed run, or a retry after a later stage failed — reuse it
    # rather than paying for a second one. cmd_generate deletes it whenever it
    # writes a new recipe, so what is here always belongs to this post.
    # --new-image forces a fresh photo.
    if hero_path.exists() and not args.new_image:
        hero = hero_path.read_bytes()
        print(f"Reusing the hero image already generated for {date} ({len(hero):,} bytes)")
        print("  (pass --new-image to generate a new one)")
    else:
        provider = get_provider()
        prompt = prompts.hero_prompt(post.recipe)
        print(f"Generating hero image via {type(provider).__name__}...")
        hero = provider.generate(prompt, prompts.aspect_ratio())
        hero_path.write_bytes(hero)

    post.hero_image_path = str(hero_path)

    if args.check_image:
        from .images.verify import check_hero

        reasons = check_hero(post.recipe, hero)
        if reasons:
            post.hold_reasons.extend(reasons)
            print("Image check flagged:")
            for reason in reasons:
                print(f"  - {reason}")

    paths = render_slides(post.recipe, hero, out_dir)
    post.slide_paths = [str(p) for p in paths]
    post.save(_post_path(date))

    for path in paths:
        print(f"  {path.name} {png_dimensions(path)}")
    (out_dir / "caption.txt").write_text(post.full_caption)
    print(f"  caption.txt ({len(post.full_caption)} chars, {len(post.hashtags)} hashtags)")


def cmd_stage(args: argparse.Namespace) -> None:
    from .storage.base import get_storage

    date = args.date
    post = _load(date)
    if not post.slide_paths:
        raise SystemExit("No rendered slides. Run the render stage first.")

    storage = get_storage()
    post.slide_urls = [
        storage.put(pathlib.Path(p), f"{date}/{pathlib.Path(p).name}") for p in post.slide_paths
    ]
    post.save(_post_path(date))
    for url in post.slide_urls:
        print(f"  {url}")

    # The phone page costs nothing to write and is the whole manual-posting
    # path, so it is produced on every stage rather than behind a flag — useful
    # even when publishing succeeds, as a look at what actually went out.
    from .render import handoff

    handoff.write_page(post, post.slide_urls)
    base = os.environ.get("PAGES_BASE_URL", "").rstrip("/")
    print(f"\n  Post it from your phone: {base}/{handoff.PAGE_NAME}")

    print(
        "\nThese must be live before publishing — commit and push docs/, and let "
        "GitHub Pages finish building."
    )


def cmd_doctor(args: argparse.Namespace) -> None:
    from . import doctor

    sys.exit(doctor.run())


def cmd_wait(args: argparse.Namespace) -> None:
    """Block until the staged slide URLs are actually served.

    Staging only copies files into docs/; they become reachable once the commit
    is pushed and GitHub Pages rebuilds. Publishing before that gives TikTok a
    404 to pull from, which fails asynchronously and is confusing to debug.
    """
    import time

    import requests

    post = _load(args.date)
    if not post.slide_urls:
        raise SystemExit("No staged slide URLs. Run the stage step first.")

    deadline = time.monotonic() + args.timeout
    for url in post.slide_urls:
        while True:
            try:
                if requests.head(url, timeout=15, allow_redirects=True).status_code == 200:
                    print(f"  live: {url}")
                    break
            except requests.RequestException:
                pass
            if time.monotonic() > deadline:
                raise SystemExit(
                    f"Timed out after {args.timeout}s waiting for {url}.\n"
                    "Check that GitHub Pages is enabled and building from the docs/ folder, "
                    "and that PAGES_BASE_URL matches the published site URL."
                )
            time.sleep(10)


def cmd_gate(args: argparse.Namespace) -> None:
    from .state import queue

    date = args.date
    post = _load(date)
    reasons = list(post.hold_reasons)  # keep anything the image check already found
    reasons += quality.check(
        post.recipe,
        past_titles=queue.recent_titles(),
        caption=post.caption,
        hashtags=post.hashtags,
    )
    post.hold_reasons = reasons
    post.held = bool(reasons)
    post.save(_post_path(date))

    if post.held:
        print("HELD:")
        for reason in reasons:
            print(f"  - {reason}")
    else:
        print(f"Clear to publish. Badges: {', '.join(post.recipe.series)}")


def _publishers(names: list[str]):
    for name in names:
        if name == "tiktok":
            from .publish.tiktok import TikTokPublisher

            yield TikTokPublisher()
        elif name == "instagram":
            from .publish.instagram import InstagramPublisher

            yield InstagramPublisher()
        elif name == "facebook":
            from .publish.facebook import FacebookPublisher

            yield FacebookPublisher()
        else:
            raise SystemExit(f"Unknown platform: {name}")


def cmd_publish(args: argparse.Namespace) -> None:
    from .state import queue

    date = args.date
    post = _load(date)

    if post.held and not args.force:
        raise SystemExit(
            "This post is held:\n"
            + "\n".join(f"  - {r}" for r in post.hold_reasons)
            + "\nFix it, or pass --force to publish anyway."
        )
    if not post.slide_urls:
        raise SystemExit("No staged slide URLs. Run the stage step first.")

    names = args.platforms.split(",") if args.platforms else list(DEFAULT_PLATFORMS)
    any_failed = False
    for publisher in _publishers(names):
        try:
            result = publisher.publish(post, dry_run=args.dry_run)
        except Exception as exc:  # a broken platform must not abort the others
            any_failed = True
            print(f"[{publisher.name}] ERROR: {exc}")
            post.published[publisher.name] = {"ok": False, "error": str(exc)}
            continue

        post.published[publisher.name] = {
            "ok": result.ok,
            "detail": result.detail,
            "needs_manual_finish": result.needs_manual_finish,
            "message": result.message,
        }
        print(f"[{result.platform}] {'OK' if result.ok else 'FAILED'} — {result.message}")
        if not result.ok:
            any_failed = True

    post.save(_post_path(date))

    if not args.dry_run:
        queue.record(date, post.recipe.slug, post.recipe.title, post.hashtags, post.published)

    if any_failed:
        sys.exit(1)


# Anything but empty or an explicit no counts as on. Demanding exactly "true"
# turned a typo in the value into "publish to TikTok", and for this flag the
# safe reading of an unclear value is the one that posts nothing.
_MANUAL_OFF = {"", "false", "0", "no", "off"}


def _manual_mode_set() -> bool:
    return os.environ.get("MANUAL_MODE", "").strip().lower() not in _MANUAL_OFF


def cmd_run(args: argparse.Namespace) -> None:
    from .state import queue

    date = args.date
    if queue.already_posted_today(date) and not args.force:
        print(f"Already posted on {date}. Pass --force to post again.")
        return

    # --force means "post again today", so it has to mean a different post:
    # reusing the recipe still on disk would republish the one that just went
    # out. Resuming a failed run is the other reason out/<date>/ is populated,
    # and that never reaches the queue, so it keeps the cheap path.
    if args.force:
        args.regenerate = True

    cmd_generate(args)
    cmd_render(args)
    cmd_gate(args)

    post = _load(date)
    if post.held:
        held_dir = config.OUT_DIR / "held" / date
        held_dir.parent.mkdir(parents=True, exist_ok=True)
        if held_dir.exists():
            shutil.rmtree(held_dir)
        shutil.move(str(_post_dir(date)), str(held_dir))
        notify.report_held(post.recipe.title, post.hold_reasons, str(held_dir))
        queue.record(date, post.recipe.slug, post.recipe.title, post.hashtags, held=True)
        # A held post is the gate doing its job, not a pipeline failure.
        return

    if args.no_publish:
        print(
            f"\nPhase 0 mode: slides and caption are ready in {_post_dir(date)}. "
            "Post them by hand, or drop --no-publish once your API access is live."
        )
        return

    cmd_stage(args)

    # Manual mode stops here on purpose. Staging has already put the slides on
    # the public site and written the phone page, which is everything posting by
    # hand needs — and unlike publishing, it requires no TikTok app at all.
    if args.manual or _manual_mode_set():
        print(
            "\nManual mode: nothing was sent to TikTok. Commit and push docs/, "
            "then open the phone page above and post it yourself."
        )
        return

    cmd_publish(args)


# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="recipe-social", description=__doc__)
    parser.add_argument("--date", default=_today(), help="Post date (YYYY-MM-DD). Defaults to today.")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, func, help_text: str):
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(func=func)
        return p

    # Both stages reuse whatever a previous run left in out/<date>/ rather than
    # paying for it twice, so both need a way to say "no, buy me a new one".
    def add_regenerate(p):
        p.add_argument(
            "--regenerate", action="store_true",
            help="Write a new recipe even if out/<date>/post.json already has one. "
                 "Also discards the hero image, which belonged to the old recipe.",
        )

    def add_new_image(p):
        p.add_argument(
            "--new-image", action="store_true",
            help="Generate a new hero image even if out/<date>/hero.png exists.",
        )

    add("doctor", cmd_doctor, "Check the setup end to end without posting anything.")

    add_regenerate(add("generate", cmd_generate, "Generate a recipe, caption, and hashtags."))

    resume = add("resume", cmd_resume, "Adopt a failed run's recipe and photo as today's post.")
    resume.add_argument(
        "--from-date", default="",
        help="Date to salvage (YYYY-MM-DD). Defaults to the newest other post in out/.",
    )

    render = add("render", cmd_render, "Generate the hero image and render the slides.")
    render.add_argument(
        "--no-check-image", dest="check_image", action="store_false",
        help="Skip the vision sanity check on the hero image.",
    )
    render.set_defaults(check_image=True)
    add_new_image(render)

    add("stage", cmd_stage, "Copy slides to the public media directory and record their URLs.")

    wait = add("wait", cmd_wait, "Block until the staged slide URLs are served publicly.")
    wait.add_argument("--timeout", type=int, default=420, help="Seconds to wait (default 420).")

    add("gate", cmd_gate, "Run the quality checks against the post.")

    publish = add("publish", cmd_publish, "Publish to the platforms.")
    publish.add_argument(
        "--platforms",
        help=f"Comma-separated subset of {','.join(ALL_PLATFORMS)}. "
             f"Default: {','.join(DEFAULT_PLATFORMS)}.",
    )
    publish.add_argument("--dry-run", action="store_true", help="Print payloads, send nothing.")
    publish.add_argument("--force", action="store_true", help="Publish even if the post is held.")

    run = add("run", cmd_run, "Run the whole pipeline.")
    run.add_argument(
        "--platforms",
        help=f"Comma-separated subset of {','.join(ALL_PLATFORMS)}. "
             f"Default: {','.join(DEFAULT_PLATFORMS)}.",
    )
    run.add_argument("--dry-run", action="store_true", help="Print payloads, send nothing.")
    run.add_argument("--force", action="store_true", help="Ignore the already-posted-today guard.")
    run.add_argument(
        "--no-publish", action="store_true",
        help="Phase 0: stop after rendering, leaving assets to post by hand.",
    )
    run.add_argument(
        "--manual", action="store_true",
        help="Build and stage everything, then stop before TikTok. Post from the "
             "phone page the stage step writes. Needs no TikTok app. Can also be "
             "set permanently with the MANUAL_MODE=true environment variable.",
    )
    run.add_argument("--no-check-image", dest="check_image", action="store_false")
    run.set_defaults(check_image=True)
    add_regenerate(run)
    add_new_image(run)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
