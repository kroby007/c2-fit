#!/usr/bin/env python3
"""Pipeline entry point.

    generate -> render -> stage -> gate -> publish

Each stage reads and writes out/<date>/post.json, so any stage can be re-run on
its own against a previous stage's output. `run` executes the whole chain.

Phase 0 usage — no platform API access required:

    python -m src.cli run --no-publish

writes finished slides and a caption to out/<date>/ for posting by hand.
"""
from __future__ import annotations

import argparse
import datetime as dt
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
    recipe = generate_recipe(exclude_titles=queue.recent_titles())
    post = Post(recipe=recipe, date=date)
    post.hashtags = compose.build_hashtags(recipe, recent=queue.recent_hashtags())
    post.caption = compose.build_caption(recipe)

    post.save(_post_path(date))
    print(f"Generated: {recipe.title}")
    print(f"  {recipe.macros.protein_g}g protein · {recipe.total_minutes} min · "
          f"${recipe.cost_per_serving:.2f}/serving · badges: {', '.join(recipe.series) or 'none'}")
    print(f"  -> {_post_path(date)}")


def cmd_render(args: argparse.Namespace) -> None:
    from .images import prompts
    from .images.provider import get_provider
    from .render.slides import png_dimensions, render_slides

    date = args.date
    post = _load(date)
    out_dir = _post_dir(date)

    provider = get_provider()
    prompt = prompts.hero_prompt(post.recipe)
    print(f"Generating hero image via {type(provider).__name__}...")
    hero = provider.generate(prompt, prompts.aspect_ratio())

    hero_path = out_dir / "hero.png"
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


def cmd_run(args: argparse.Namespace) -> None:
    from .state import queue

    date = args.date
    if queue.already_posted_today(date) and not args.force:
        print(f"Already posted on {date}. Pass --force to post again.")
        return

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

    add("doctor", cmd_doctor, "Check the setup end to end without posting anything.")

    add("generate", cmd_generate, "Generate a recipe, caption, and hashtags.")

    render = add("render", cmd_render, "Generate the hero image and render the slides.")
    render.add_argument(
        "--no-check-image", dest="check_image", action="store_false",
        help="Skip the vision sanity check on the hero image.",
    )
    render.set_defaults(check_image=True)

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
    run.add_argument("--no-check-image", dest="check_image", action="store_false")
    run.set_defaults(check_image=True)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
