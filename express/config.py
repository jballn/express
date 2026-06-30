"""Configuration for the Express MCP server.

All settings are driven by environment variables with sensible defaults.
Import as: from express.config import config
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Config:
    """Immutable configuration backed by environment variables."""

    # ── LLM ──────────────────────────────────────────────────────────
    llm_endpoint: str = os.environ.get(
        "EXPRESS_LLM_ENDPOINT", "http://localhost:58008/v1"
    )
    llm_model: str = os.environ.get("EXPRESS_LLM_MODEL", "default-model")

    # ── Usagi Engine ─────────────────────────────────────────────────
    usagi_bin: Path = field(
        default_factory=lambda: Path(
            os.environ.get(
                "EXPRESS_USAGI_BIN",
                str(Path.home() / ".build" / "express" / "usagi-source" / "target" / "release" / "usagi"),
            )
        )
    )
    usagi_workspace: Path = field(
        default_factory=lambda: Path(
            os.environ.get(
                "EXPRESS_USAGI_WORKSPACE",
                str(Path.home() / ".build" / "express" / "usagi-workspace"),
            )
        )
    )

    # ── Display / Framebuffer ────────────────────────────────────────
    framebuffer: Path = field(
        default_factory=lambda: Path(os.environ.get("EXPRESS_FRAMEBUFFER", "/dev/fb0"))
    )
    drm_card: Path = field(
        default_factory=lambda: Path(os.environ.get("EXPRESS_DRM_CARD", "/dev/dri/card1"))
    )
    capture_method: str = os.environ.get("EXPRESS_CAPTURE_METHOD", "xvfb")
    # Xvfb virtual display settings
    xvfb_display: str = os.environ.get("EXPRESS_XVFB_DISPLAY", "99")
    xvfb_screen: str = os.environ.get("EXPRESS_XVFB_SCREEN", "320x180x24")
    xvfb_pid_file: Path = field(
        default_factory=lambda: Path(
            os.environ.get("EXPRESS_XVFB_PID_FILE", "/tmp/.express-xvfb.pid")
        )
    )

    # ── Timing ───────────────────────────────────────────────────────
    render_timeout: float = float(os.environ.get("EXPRESS_RENDER_TIMEOUT", "30"))
    max_heal_passes: int = int(os.environ.get("EXPRESS_MAX_HEAL_PASSES", "3"))
    render_wait_ms: int = int(os.environ.get("EXPRESS_RENDER_WAIT_MS", "500"))

    # ── Canvas ───────────────────────────────────────────────────────
    canvas_width: int = 320
    canvas_height: int = 180
    palette_size: int = 16

    # ── Paths ────────────────────────────────────────────────────────
    llm_output_lua: Path = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "llm_output_lua", self.usagi_workspace / "llm_output.lua")

    # ── Helpers ──────────────────────────────────────────────────────
    @property
    def llm_chat_url(self) -> str:
        """Full URL for the /v1/chat/completions endpoint."""
        return f"{self.llm_endpoint.rstrip('/')}/chat/completions"

    def ensure_workspace(self) -> None:
        """Create usagi workspace directory if it doesn't exist."""
        self.usagi_workspace.mkdir(parents=True, exist_ok=True)

    def ensure_skeleton(self) -> None:
        """Write the persistent main.lua skeleton if it doesn't exist."""
        self.ensure_workspace()  # ensure dir exists first
        main_path = self.usagi_workspace / "main.lua"
        if not main_path.exists():
            main_path.write_text(self._skeleton_main())

    @staticmethod
    def _skeleton_main() -> str:
        """Persistent skeleton that survives hot-reloads."""
        return """-- Usagi Engine — persistent skeleton
-- State table survives hot-reloads (capitalized globals)
State = State or {}

-- ── Dynamic payload (replaced each render_expression call) ─────
local payload_ok, payload = pcall(loadfile("llm_output.lua"))
if payload_ok and payload then
    local fn = payload()
    if type(fn) == "function" then
        _init = fn._init or _init
        _update = fn._update or _update
        _draw = fn._draw or _draw
    end
end

-- ── Fallback draw (always runs) ──────────────────────────────────
local _orig_draw = _draw
_draw = function()
    _orig_draw()
    gfx.print("OK", gfx.width() / 2, gfx.height() / 2, 7)
end
"""


# Singleton instance — import like: from express.config import config
config = Config()
