"""Publisher interface shared by TikTok, Instagram, and Facebook."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..recipes.schema import Post


@dataclass
class PublishResult:
    platform: str
    ok: bool
    # What the platform gave back — publish id, draft id, error payload.
    detail: dict[str, Any] = field(default_factory=dict)
    # Set when the post landed somewhere the user still has to finish by hand.
    needs_manual_finish: bool = False
    message: str = ""


class Publisher(ABC):
    name: str

    @abstractmethod
    def publish(self, post: Post, dry_run: bool = False) -> PublishResult:
        """Publish `post`. With dry_run, build and report the payload but send nothing."""
