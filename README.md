# Express

MCP server for direct-to-hardware 2D visual expression via the Usagi Engine.

Runs Lua scripts through the Usagi 2D game engine on a headless Linux machine, capturing frames to the physical framebuffer (/dev/fb0).

## Quick Start

```bash
cd ~/.build/express
pip install -e .
express
```

The server reads JSON-RPC requests from stdin and writes responses to stdout.

## Architecture

```
Upstream LLM Agent (MCP Client)
         |
         v
  MCP Server (stdio)
    └── render_lua        # Raw Lua -> Usagi -> framebuffer
         |
         v
  Usagi Engine (Rust)
    ├── Live-reload via llm_output.lua
    ├── DRM/KMS hardware rendering
    └── 320x180 canvas, Pico-8 16-color palette
         |
         v
  Linux Framebuffer (/dev/fb0)
```

### Layers

| Layer | Module | Purpose |
|---|---|---|
| **Tools** | `express.tools` | MCP tool implementations (`render_lua`) |
| **LLM** | `express.llm` | OpenAI-compatible API client and system prompts |
| **Renderer** | `express.renderer` | Usagi process management, framebuffer capture |
| **Config** | `express.config` | Environment-driven configuration, workspace setup |

## Tool

### `render_lua`

Runs Lua code through the Usagi engine and captures the result.

1. Starts Xvfb virtual display
2. Writes Lua code to Usagi workspace (`llm_output.lua`)
3. Runs Usagi with `RAYLIB_BACKEND=window`
4. Captures frame via ImageMagick `import`
5. Upscales to 1360x768 and writes to `/dev/fb0`
6. Returns base64 data URL of captured frame

**Input:** `lua_code` (required) — Complete Lua script with `_init`, `_update`, `_draw` functions. Optional `display_width` and `display_height` (defaults 320x180).

**Output:** JSON with `success`, `code`, `issues`, `console_output`, `duration_seconds`, `framebuffer_url`, `fb0_written`, `fb0_size`.

## Configuration

All paths and endpoints are configurable via `config.py` or environment variables:

| Variable | Default | Description |
|---|---|---|
| `EXPRESS_LLM_ENDPOINT` | `http://localhost:58008/v1` | OpenAI-compatible API endpoint |
| `EXPRESS_RENDER_TIMEOUT` | `30` | Seconds before timeout |
| `EXPRESS_CAPTURE_METHOD` | `xvfb` | Framebuffer capture method |
| `EXPRESS_XVFB_DISPLAY` | `99` | Xvfb display number |
| `EXPRESS_XVFB_PID_FILE` | `/tmp/.express-xvfb.pid` | Xvfb PID file path |

## Environment Requirements

- **OS**: Linux (systemd, multi-user.target)
- **Display**: DRM/KMS-capable hardware (or Xvfb for headless testing)
- **User**: Member of `video`, `render`, `input` groups
- **Dependencies**: Python 3.11+, ImageMagick (for `render_lua`), Xvfb (optional)

## Usagi Engine

The Usagi Engine is a Rust-based 2D game engine with live Lua reload. Built with `RAYLIB_BACKEND=drm` for bare-metal framebuffer rendering.

- **Canvas**: 320x180 pixels
- **Palette**: Pico-8 16-color
- **Live-reload**: Writes to `llm_output.lua`, Usagi hot-swaps automatically
- **State memory**: Capitalized globals (`State.X`) survive hot-reloads

## Testing

```bash
cd ~/.build/express
pip install -e .
python -m pytest tests/ -v
```

78 tests across 6 files. All pass.

## Lua API Reference

The Usagi (Pico-8-like) API:

| Function | Description |
|---|---|
| `gfx.clear(color)` | Clear screen |
| `gfx.rect(x, y, w, h, color)` | Outline rectangle |
| `gfx.rect_fill(x, y, w, h, color)` | Filled rectangle |
| `gfx.circ(x, y, r, color)` | Outline circle |
| `gfx.circ_fill(x, y, r, color)` | Filled circle |
| `gfx.line(x1, y1, x2, y2, color)` | Line |
| `gfx.print(text, x, y, color)` | Text |
| `gfx.spr(n, x, y, w, h, flip_x, flip_y)` | Sprite |

Color constants: `gfx.COLOR_BLACK=1` through `gfx.COLOR_PEACH=16`.

Effects: `effect.screen_shake(intensity, duration)`, `effect.flash(color, duration)`.

## License

MIT
