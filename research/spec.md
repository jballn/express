# Usagi Engine — Technical Specification

> **Source code**: `usagi-source/` (Rust + Lua game engine, raylib 5.x via `sola_raylib`)  
> **Lua version**: Lua 5.4 via `mlua` (feature = "lua54")  
> **Raylib version**: 5.5 (via `sola_raylib` 0.11)  
> **Build target**: Single binary `usagi` + wasm32-unknown-emscripten export

---

## 1. Project Structure

```
usagi-source/
├── Cargo.toml              # workspace manifest (single crate)
├── src/
│   ├── main.rs             # entry point: mode dispatch (run / init / export / web-export / tools)
│   ├── session.rs          # core game loop, Lua VM lifecycle, API registration, render pipeline
│   ├── palette.rs          # Pico-8 16-color palette, palette.png loading
│   ├── sprites.rs          # sprites.png tilemap parsing, tile extraction
│   ├── input.rs            # abstract input actions, keymap, gamepad binding, face-button glyphs
│   ├── keymap.rs           # keyboard remapping persistence (JSON file)
│   ├── pad_map.rs          # gamepad remapping persistence (JSON file)
│   ├── effect.rs           # hitstop, screen_shake, flash, slow_mo
│   ├── sfx.rs              # short sound effects (WAV, up to 256, 48 kHz, mono)
│   ├── music.rs            # background music (OGG/MP3/WAV/FLAC via raylib MusicStream)
│   ├── shader.rs           # GLSL fragment shader loading, compilation, Lua bindings
│   ├── vfs.rs              # VirtualFs trait: FsBacked (dev) / BundleBacked (exported)
│   ├── bundle.rs           # in-memory asset bundling for exported games
│   ├── save.rs             # save data: Lua table ↔ JSON, game_id, atomic writes
│   ├── game_id.rs          # game_id resolution (_config > project name > bundle hash)
│   ├── settings.rs         # engine settings (fullscreen, volume, vsync, etc.)
│   ├── msg.rs              # structured logging macros: msg::info!, msg::warn!, msg::error!
│   ├── export.rs           # binary game export (bundles assets, embeds Lua)
│   ├── web_export.rs       # wasm32-emscripten build orchestration
│   ├── tools.rs            # debug tools window (FPS, memory, VFS browser, input tester)
│   └── gamepad/            # per-game gamepad config subcommand
│       └── mod.rs
└── examples/               # example games (snake/, etc.)
```

---

## 2. Core Game Loop & Session Architecture

### 2.1 Session Lifecycle

The `Session` struct (`src/session.rs`) owns the entire game state:

```rust
pub struct Session {
    lua: Lua,                          // Lua 5.4 VM
    context: LuaContext,               // Lua state snapshot (globals, package.loaded, etc.)
    vfs: Box<dyn VirtualFs>,           // FsBacked or BundleBacked
    gfx: Gfx,                          // rendering state (texture, camera, RT)
    input: Rc<Cell<InputState>>,       // per-frame input snapshot (shared with Lua callbacks)
    pad_map: PadMap,                   // gamepad remap config
    keymap: Keymap,                    // keyboard remap config
    sfx: Sfx,                          // sound effect system
    music: Music,                      // background music player
    effect: Rc<RefCell<Effects>>,      // juice effects (hitstop, shake, flash, slow_mo)
    // ... more
}
```

### 2.2 Game Loop

```
┌─────────────────────────────────────────────────────────┐
│  Raylib game loop (poll_events, is_window_hidden)       │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Session::tick(dt)                                │  │
│  │                                                   │  │
│  │  1. input_state = input::InputState::new(rl, ...) │  │
│  │  2. effect.tick(dt)                               │  │
│  │  3. if effect.frozen() → skip _update, go to 5    │  │
│  │  4. call_lua_update(dt, &input_state)             │  │
│  │  5. call_lua_draw()                               │  │
│  │  6. render (RT → screen with shake/flash overlay) │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Live reload check (FsBacked only):               │  │
│  │    if vfs.freshest_lua_mtime() > last_reload:     │  │
│  │      reload all Lua scripts                       │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

**Key behaviors**:
- **Hitstop**: When `effect.frozen()` is true, `_update` is skipped but `_draw` still runs and effects continue to decay. This freezes game logic while preserving visual feedback.
- **Slow motion**: `dt` is multiplied by `effect.time_scale()` before being passed to `_update`. When no slow_mo is active, scale is 1.0.
- **Real-time decay**: All effect timers decay using real wall-clock `dt`, NOT affected by slow_mo.
- **Stacking rule**: For all four effects, longer duration wins; for magnitude parameters, the latest call wins.

### 2.3 Lua VM Context

```
Lua VM ──> _G (global environment)
              │
              ├── _config      ← user-defined table from _config.lua
              ├── _init        ← user-defined function
              ├── _update(dt)  ← user-defined function, called per frame
              ├── _draw()      ← user-defined function, called per frame
              │
              ├── gfx          ← rendering API (see §3)
              ├── input        ← input API (see §4)
              ├── sfx          ← sound effects API (see §5)
              ├── music        ← background music API (see §5)
              ├── effect       ← juice effects API (see §6)
              ├── usagi        ← engine utilities (see §7)
              ├── shader       ← shader API (see §8)
              ├── require      ← Lua module loader (see §2.4)
              └── package      ← standard Lua package (require, loaded, etc.)
```

### 2.4 Module Loading (`require`)

`module_candidates()` in `vfs.rs` translates dotted names to paths:

| Lua name         | Resolved paths (in order)       | Chunk name for traces     |
|------------------|----------------------------------|---------------------------|
| `"enemies"`      | `enemies.lua`, `enemies/init.lua` | `"enemies.lua"` or `"enemies/init.lua"` |
| `"world.tiles"`  | `world/tiles.lua`, `world/tiles/init.lua` | `"world/tiles.lua"` or `"world/tiles/init.lua"` |

**Security**: Path traversal (`..`, `/`, `\`, empty segments) is rejected. Only names matching `^[a-zA-Z_][a-zA-Z0-9_]*$` with dots for subdirectories are accepted.

**Meta chunk exclusion**: Files starting with `---@meta` (lua-language-server stubs) are detected by scanning the first 256 bytes for the marker on the first non-blank line. These are excluded from `require` and bundle walks.

---

## 3. Graphics API (`gfx`)

### 3.1 Overview

All rendering uses raylib's texture-based pipeline with a render-to-texture (RT) pattern:

```
┌──────────────────────────────────────────────────────────┐
│  Screen (window or fullscreen)                           │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Render Target (RT) — fixed resolution             │  │
│  │  ┌──────────────────────────────────────────────┐  │  │
│  │  │                                              │  │  │
│  │  │              _draw()                         │  │  │
│  │  │          (user game rendering)               │  │  │
│  │  │                                              │  │  │
│  │  └──────────────────────────────────────────────┘  │  │
│  │       ↑ shake offset applied                        │  │
│  │       ↑ flash overlay drawn on top                  │  │
│  └────────────────────────────────────────────────────┘  │
│          ↑ bilinear filter, stretched to screen           │
└──────────────────────────────────────────────────────────┘
```

### 3.2 API Surface

#### `gfx.width()` / `gfx.height()`
- Returns the RT resolution (not screen/window size).
- **1-based indexing** for tile calculations.

#### `gfx.screen_width()` / `gfx.screen_height()`
- Returns the current window/screen dimensions in pixels.
- Used for centering, HUD positioning, full-screen effects.

#### `gfx.set_resolution(w, h)`
- Sets the render target resolution.
- Must be called before the first `_draw` (or in `_init`).
- Changes the internal texture size; subsequent draws render at the new resolution.

#### `gfx.pixel(x, y, color)`
- Draws a single pixel at (x, y) in RT coordinates.
- `color`: integer 0–15 (Pico-8 palette index).

#### `gfx.rect(x, y, w, h, color, outline)`
- Filled rectangle. `outline > 0` draws a border of that thickness.
- Coordinates in RT pixels.

#### `gfx.rectf(x, y, w, h, color)`
- Filled rectangle (shorthand for `gfx.rect(x, y, w, h, color, 0)`).

#### `gfx.sprite(tile_index, x, y, frame, flip)`
- Draws a tile from `sprites.png` at position (x, y).
- `tile_index`: integer (0-based index into the sprite sheet).
- `frame`: optional frame number for animation (0 = default).
- `flip`: optional flags — `"h"` for horizontal, `"v"` for vertical flip.

#### `gfx.sprite_centered(tile_index, x, y, frame, flip)`
- Same as `sprite`, but (x, y) is the center of the sprite.

#### `gfx.print(text, x, y, color)`
- Draws text using the built-in bitmap font.
- `text`: string. `color`: integer 0–15.
- Font: 8×8 pixel bitmap, 128 characters (ASCII 32–127).

#### `gfx.print_centered(text, x, y, color)`
- Same as `print`, but (x, y) is the horizontal center of the text.

#### `gfx.clip(x, y, w, h)` / `gfx.clip()`
- Sets/clears the clipping region for subsequent draws.
- Coordinates in RT space.

#### `gfx.color(i)`
- Returns `{r, g, b, a}` table for palette index `i` (0–15).
- Default: Pico-8 palette. Custom palettes loaded from `palette.png`.

#### `gfx.map(map_data, tile_w, tile_h, offset_x, offset_y, camera)`
- Draws a tile map from user-provided data.
- `map_data`: 1D array, row-major, values are tile indices.
- `tile_w`, `tile_h`: tile dimensions in pixels.
- `offset_x`, `offset_y`: camera offset.
- `camera`: optional `{x, y, w, h}` viewport rect.

#### `gfx.draw_map(map_data, tile_w, tile_h, offset_x, offset_y)`
- Shorthand variant of `gfx.map`.

#### `gfx.line(x1, y1, x2, y2, color)`
- Draws a line segment.

#### `gfx.circle(x, y, radius, color, outline)`
- Draws a filled or outlined circle.

#### `gfx.ellipse(x, y, w, h, color, outline)`
- Draws a filled or outlined ellipse.

#### `gfx.tri(x1, y1, x2, y2, x3, y3, color)`
- Draws a filled triangle.

#### `gfx.tri3f(x1, y1, x2, y2, x3, y3, c1, c2, c3)`
- Draws a triangle with per-vertex colors (bilinear interpolation).

#### `gfx.arc(x, y, radius, start_angle, end_angle, color, outline)`
- Draws an arc or pie slice.

#### `gfx.bg(color)`
- Sets the background color for the RT.
- Called implicitly at the start of each frame; user can override.

#### `gfx.cam(x, y, w, h)`
- Sets the camera/viewport rectangle for the RT.
- After `gfx.cam(0, 0, w, h)`, all subsequent draws are relative to this viewport.
- Used for camera movement, split-screen, minimaps.

#### `gfx.get_tile(tilesheet, tile_index)`
- Extracts a single tile from a tilesheet image.
- Returns pixel data for the tile.

### 3.3 Coordinate System

- **Origin**: Top-left corner of the RT.
- **Units**: Render target pixels (1-based indexing for tile math).
- **Scaling**: The RT is stretched (bilinear filter) to fill the screen. No integer-scale mode.
- **1-based indexing**: Tile indices for map data are conceptually 1-based in user code (matching Pico-8 convention), though the underlying storage is 0-based.

### 3.4 Palette System

- **Default**: Pico-8 16-color palette (hardcoded in `palette.rs`).
- **Custom**: Drop `palette.png` at project root. Must be exactly 1 pixel tall, one color per pixel (16 pixels wide minimum).
- **API**: `gfx.color(i)` returns `{r, g, b, a}` for index `i` (0–15).
- **Format**: PNG, 1×N pixels, RGBA.

### 3.5 Sprite System

- **Source**: `sprites.png` at project root.
- **Format**: 16×16 pixel tiles, arranged in a grid.
- **Tile indexing**: 0-based linear index (row-major across the sprite sheet).
- **Flip flags**: `"h"` (horizontal), `"v"` (vertical). Can be combined: `"hv"`.
- **Animation**: `frame` parameter selects which tile to draw (for sprite-sheet animation).

---

## 4. Input API (`input`)

### 4.1 Abstract Input Actions

Actions are integer IDs (1-based). Each action is a union over keyboard, gamepad, and analog inputs:

| Action ID | Name   | Keyboard      | Gamepad (Xbox)              | Analog Stick        |
|-----------|--------|---------------|-----------------------------|---------------------|
| 1         | `LEFT` | Left, A       | D-pad Left, Left Stick Left | Left X < −0.3       |
| 2         | `RIGHT`| Right, D      | D-pad Right, Left Stick Right| Left X > +0.3       |
| 3         | `UP`   | Up, W         | D-pad Up, Left Stick Up     | Left Y < −0.3       |
| 4         | `DOWN` | Down, S       | D-pad Down, Left Stick Down | Left Y > +0.3       |
| 5         | `BTN1` | Z, J          | A (south), LB (left bumper) | —                   |
| 6         | `BTN2` | X, K          | B (east), RB (right bumper) | —                   |
| 7         | `BTN3` | C, L          | Y (north) + X (west)        | —                   |

**Nintendo Switch face-button swap**: On Nintendo gamepads, BTN1 maps to A (east) and BTN2 maps to B (south), matching Nintendo's "A=primary, B=cancel" convention.

### 4.2 API Surface

#### `input.action_down(action_id)` → `bool`
- Returns true while the action is held down.
- `action_id`: integer (1–7) or `input.LEFT`, `input.RIGHT`, etc.
- Samples all keyboards, gamepads, and analog sticks.

#### `input.action_pressed(action_id)` → `bool`
- Returns true on the frame the action transitions from up to down (edge-triggered).
- Used for single-press actions (jump, confirm).

#### `input.action_released(action_id)` → `bool`
- Returns true on the frame the action transitions from down to up (edge-triggered).

#### `input.key_down(key_id)` → `bool`
- Direct keyboard read. Bypasses Keymap overrides and gamepad bindings.
- `key_id`: integer (raylib `KeyboardKey` enum value) or `input.KEY_A`, `input.KEY_B`, etc.
- **Escape hatch**: For dev hotkeys, keyboard-only games. Not recommended for cross-device input.

#### `input.key_pressed(key_id)` → `bool`
- Edge-triggered version of `key_down`.

#### `input.mouse_x()` / `input.mouse_y()` → `number`
- Returns mouse position in screen coordinates.

#### `input.mouse_down(button_id)` → `bool`
- Returns true while mouse button is held.
- `button_id`: `input.MOUSE_LEFT` (0), `input.MOUSE_RIGHT` (1), `input.MOUSE_MIDDLE` (2).

#### `input.mouse_pressed(button_id)` → `bool`
- Edge-triggered version of `mouse_down`.

### 4.3 Keyboard Key Table

25 letters (A–Z), 10 digits (0–9), 12 function keys (F1–F12), and 18 special keys including SPACE, ENTER, ESCAPE, TAB, BACKSPACE, DELETE, arrows, modifiers (LSHIFT, RSHIFT, LCTRL, RCTRL, LALT, RALT), and punctuation (BACKTICK, MINUS, EQUAL, LBRACKET, RBRACKET, BACKSLASH, SEMICOLON, APOSTROPHE, COMMA, PERIOD, SLASH).

Total: 75 keys in `KEY_TABLE`. Bit position = index into bitmask.

### 4.4 Gamepad Support

- **Max gamepads**: 4 slots (`MAX_GAMEPADS = 4`).
- **Hot-swap detection**: `GamepadProbe::poll()` logs connect/disconnect events.
- **Face button families**: Xbox (A/B/X/Y), PlayStation (Cross/Circle/Triangle/Square), Nintendo (B/A/Y/X).
- **Trigger labels**: Xbox (LB/RB, LT/RT), PlayStation (L1/R1, L2/R2), Nintendo (L/R, ZL/ZR).
- **Deadzone**: 0.3 for analog stick direction checks.
- **Axis edge tracking**: `AxisEdgeTracker` tracks previous frame stick values for edge detection on stick directions.

---

## 5. Audio API

### 5.1 Sound Effects (`sfx`)

#### `sfx.play(sound_id, speed, volume)`
- Plays a sound effect.
- `sound_id`: integer (0-based index) or stem name (string, without `.wav` extension).
- `speed`: float multiplier for playback speed (default 1.0).
- `volume`: float 0.0–1.0 (default 1.0).

#### `sfx.stop()`
- Stops all currently playing sound effects.

#### `sfx.is_playing(sound_id)` → `bool`
- Returns true if the specified sound is currently playing.

#### Asset loading:
- **Directory**: `sfx/` at project root.
- **Format**: WAV files only (256 samples, 48 kHz, mono).
- **Naming**: Filenames without `.wav` extension become stem names.
- **Manifest**: Engine builds a `HashMap<stem, mtime>` for live-reload detection.

### 5.2 Background Music (`music`)

#### `music.play(track_name)`
- Starts playing a music track by stem name (without extension).
- Tracks are loaded from the `music/` directory.

#### `music.stop()`
- Stops the current music track.

#### `music.pause()`
- Pauses the current music track.

#### `music.resume()`
- Resumes a paused music track.

#### `music.is_playing()` → `bool`
- Returns true if music is currently playing (not paused).

#### `music.set_volume(volume)`
- Sets master music volume (0.0–1.0).

#### `music.get_volume()` → `number`
- Returns current music volume.

#### Asset loading:
- **Directory**: `music/` at project root.
- **Supported formats**: OGG, MP3, WAV, FLAC (case-insensitive extension matching).
- **Preferred format**: OGG (best cross-platform support, especially for web/emscripten builds).
- **Loading**: raylib's `LoadMusicStreamFromMemory` — streams from memory buffer.

---

## 6. Effects API (`effect`)

### 6.1 Overview

Four juice primitives, all with the same stacking semantics:
- **Duration**: longer duration wins
- **Magnitude**: latest call wins
- **Decay**: linear, using real wall-clock dt (NOT affected by slow_mo)
- **Negative inputs**: clamped to zero

### 6.2 API Surface

#### `effect.hitstop(time)`
- Freezes `_update` for `time` seconds. `_draw` continues running.
- `time`: float ≥ 0 (clamped). 0 = no-op.
- Use case: hit confirmation frames in fighting games.

#### `effect.screen_shake(time, intensity)`
- Shakes the render target by a randomized offset.
- `time`: float ≥ 0 (duration in seconds).
- `intensity`: float ≥ 0 (maximum pixel offset magnitude).
- Magnitude decays linearly: `offset = intensity * (shake_left / shake_total)`.
- Angle is randomized each frame using Xorshift32 (seed: `0xdeadbeef`).

#### `effect.flash(time, color_index)`
- Draws a full-screen color overlay with linear alpha decay.
- `time`: float ≥ 0.
- `color_index`: integer 0–15 (Pico-8 palette index).
- Alpha: `255 * (flash_left / flash_total)`, rounded.

#### `effect.slow_mo(time, scale)`
- Scales `dt` passed to `_update` by `scale`.
- `time`: float ≥ 0.
- `scale`: float ≥ 0 (typically 0.1–0.5 for dramatic effect). 0 = full freeze (use `hitstop` instead).
- When time expires, scale returns to 1.0.

### 6.3 Effect Interaction with Game Loop

```
Frame start:
  1. effect.tick(dt)                    → decay all timers
  2. if effect.frozen():                → skip _update
       skip lua_update()
  3. call _update(dt * effect.time_scale())
  4. call _draw()
  5. render:
       apply shake offset to RT-to-screen blit
       draw flash overlay on top
```

### 6.4 Reset

`effect.reset()` clears all active timers. Called automatically when the game is reset (`_init` re-entry).

---

## 7. Engine Utilities (`usagi`)

### 7.1 Configuration

#### `_config()` → table
- User-defined table from `_config.lua` at project root.
- Convention: `game_id`, `title`, `width`, `height`, `fullscreen`, etc.
- `game_id`: reverse-DNS string (`com.brettmakesgames.snake`). Required for save/load.

### 7.2 Data I/O

#### `usagi.save(table)`
- Serializes a Lua table to JSON and writes to disk.
- **Validation**: Rejects tables with mixed string+integer keys, sparse integer keys (non-1..n), and non-serializable values (functions, userdata).
- **Storage**: `<data_dir>/<game_id>/save.json` (native) or `localStorage` (web).
- **Atomic writes**: Writes to `.tmp` then `rename` (POSIX atomic on same filesystem).

#### `usagi.load()` → table or nil
- Returns the deserialized save table, or `nil` on first run / no save.

#### `usagi.clear_save()`
- Removes the save file. No-op if it doesn't exist.

#### `usagi.read_json(path)` → table or nil
- Reads and parses a JSON file from the `data/` directory.
- Path is relative to `data/`, slash-separated, no traversal.
- Returns `nil` on parse error or file not found.

#### `usagi.read_text(path)` → string or nil
- Reads a text file from the `data/` directory.
- Same path rules as `read_json`.

#### `usagi.to_json(table)` → string
- Serializes a Lua table to a pretty-printed JSON string.
- Same validation rules as `usagi.save`.

### 7.3 Random Number Generation

#### `usagi.random()` → number
- Returns a pseudo-random float in [0, 1).
- Seeded by the engine (not system time).

#### `usagi.random(min, max)` → number
- Returns a pseudo-random float in [min, max].

#### `usagi.random_int(min, max)` → number
- Returns a pseudo-random integer in [min, max] (inclusive).

#### `usagi.random_choice(table)` → any
- Returns a random element from a 1-indexed array.

#### `usagi.randomize(table)` → table
- Shuffles a table in place (Fisher-Yates).

### 7.4 Math Utilities

#### `usagi.round(x)` → number
- Rounds to nearest integer.

#### `usagi.clamp(x, min, max)` → number
- Clamps x to [min, max].

#### `usagi.lerp(a, b, t)` → number
- Linear interpolation: `a + (b - a) * t`.

#### `usagi.map(x, in_min, in_max, out_min, out_max)` → number
- Remaps x from one range to another.

### 7.5 String Utilities

#### `usagi.split(str, sep)` → table
- Splits a string by separator. Returns a 1-indexed array.

#### `usagi.sub(str, i, j)` → string
- Returns substring from index i to j (1-based, inclusive).

#### `usagi.len(str)` → number
- Returns string length.

### 7.6 Table Utilities

#### `usagi.len(table)` → number
- Returns the number of elements in a 1-indexed array.

#### `usagi.keys(table)` → table
- Returns a 1-indexed array of all keys.

#### `usagi.values(table)` → table
- Returns a 1-indexed array of all values.

### 7.7 File System Access (Lua-side)

#### `usagi.read_file(path)` → string or nil
- Reads an arbitrary file from the project root.
- Path is slash-separated, no traversal.
- Raw bytes as string.

#### `usagi.write_file(path, content)`
- Writes content to a file at the project root.
- Path is slash-separated, no traversal.

### 7.8 Game Lifecycle

#### `usagi.exit()`
- Signals the engine to shut down gracefully.
- Exits the main loop after the current frame.

---

## 8. Shader API (`shader`)

### 8.1 Overview

GLSL fragment shaders loaded from the `shaders/` directory. Raylib's shader system compiles and links GLSL source at runtime.

### 8.2 API Surface

#### `shader.load(name)` → shader handle
- Loads a fragment shader from `shaders/<name>.fs`.
- Vertex shader is a fixed built-in (simple passthrough).
- Returns a shader handle (integer or userdata).

#### `shader.bind(handle)`
- Binds the shader as the active draw target.
- All subsequent draw calls use this shader until `shader.unbind()`.

#### `shader.unbind()`
- Unbinds the current shader, returning to default rendering.

#### `shader.set_uniform_float(handle, name, value)`
- Sets a float uniform.

#### `shader.set_uniform_int(handle, name, value)`
- Sets an integer uniform.

#### `shader.set_uniform_vec2(handle, name, x, y)`
- Sets a vec2 uniform.

#### `shader.set_uniform_vec3(handle, name, x, y, z)`
- Sets a vec3 uniform.

#### `shader.set_uniform_vec4(handle, name, x, y, z, w)`
- Sets a vec4 uniform.

### 8.3 Shader File Convention

- **Directory**: `shaders/` at project root.
- **File extension**: `.fs` for fragment shaders.
- **Naming**: `shaders/<name>.fs` → `shader.load("<name>")`.
- **Built-in vertex shader**: Simple passthrough (position + texcoord passthrough).

---

## 9. Virtual Filesystem (VFS)

### 9.1 Trait Definition

```rust
pub trait VirtualFs {
    // Script (main Lua file)
    fn script_name(&self) -> String;
    fn read_script(&self) -> Option<Vec<u8>>;

    // Sprites
    fn read_sprites(&self) -> Option<Vec<u8>>;
    fn sprites_mtime(&self) -> Option<SystemTime>;

    // Palette
    fn read_palette(&self) -> Option<Vec<u8>>;
    fn palette_mtime(&self) -> Option<SystemTime>;

    // Sound effects
    fn sfx_stems(&self) -> Vec<String>;
    fn read_sfx(&self, stem: &str) -> Option<Vec<u8>>;
    fn sfx_manifest(&self) -> HashMap<String, SystemTime>;

    // Music
    fn music_entries(&self) -> Vec<(String, String)>;  // (stem, ext)
    fn read_music(&self, stem: &str, ext: &str) -> Option<Vec<u8>>;
    fn music_manifest(&self) -> HashMap<String, SystemTime>;

    // Lua modules
    fn read_module(&self, mod_name: &str) -> Option<(Vec<u8>, String)>;
    fn module_mtime(&self, mod_name: &str) -> Option<SystemTime>;

    // Arbitrary files
    fn read_file(&self, rel: &str) -> Option<Vec<u8>>;
    fn file_mtime(&self, rel: &str) -> Option<SystemTime>;

    // Live-reload
    fn freshest_lua_mtime(&self) -> Option<SystemTime>;
    fn freshest_data_mtime(&self) -> Option<SystemTime>;
    fn supports_reload(&self) -> bool;

    // Bundle access
    fn project_name_hint(&self) -> Option<String>;
    fn as_bundle(&self) -> Option<&Bundle>;
}
```

### 9.2 Implementations

| Backend        | Mode        | Reload | Mtimes | Source              |
|---------------|-------------|--------|--------|---------------------|
| `FsBacked`    | dev / run   | Yes    | Yes    | Real filesystem     |
| `BundleBacked`| exported    | No     | No     | In-memory assets    |

### 9.3 File Structure (FsBacked)

```
project/
├── main.lua              ← script (entry point)
├── sprites.png           ← sprite sheet (16×16 tiles)
├── palette.png           ← optional custom palette (1px tall)
├── _config.lua           ← optional game config
├── sfx/                  ← sound effects (*.wav)
│   ├── jump.wav
│   └── hit.wav
├── music/                ← background music (*.ogg, *.mp3, *.wav, *.flac)
│   ├── theme.ogg
│   └── boss.ogg
├── data/                 ← game data files (*.json, *.txt, etc.)
│   ├── levels.json
│   └── strings.txt
├── shaders/              ← GLSL fragment shaders (*.fs)
│   └── crt.fs
├── meta/                 ← LSP type stubs (optional, excluded from execution)
│   └── usagi.lua         ← @meta stub for autocomplete
└── <module>.lua          ← Lua modules (require'd by name)
```

### 9.4 Path Safety

`safe_rel_path()` rejects:
- Empty strings
- Backslashes (`\`)
- Leading forward slash (`/`)
- `.` or `..` segments
- Empty segments (consecutive slashes)

---

## 10. Save System

### 10.1 Storage Locations

| Platform | Location                                      |
|----------|-----------------------------------------------|
| Linux    | `~/.local/share/<game_id>/save.json`          |
| macOS    | `~/Library/Application Support/<game_id>/save.json` |
| Windows  | `%APPDATA%\<game_id>\save.json`               |
| Web      | `localStorage["usagi.save.<game_id>"]`        |

### 10.2 game_id Resolution

1. `_config().game_id` (explicit, recommended: reverse-DNS)
2. Project directory name / script stem name
3. Bundle hash (for exported games)

### 10.3 JSON Validation

Tables passed to `usagi.save()` are validated:
- **Allowed keys**: strings or dense 1..n integers
- **Nested tables**: recursively validated
- **Rejected**: mixed string+integer keys, sparse integer keys (e.g., `{[6]=1, [7]=2}`), non-serializable values (functions, threads, userdata)
- **Error messages**: human-readable with workarounds (e.g., "Convert integer keys with `tostring(k)` to save as a map")

### 10.4 Atomic Writes (Native)

```rust
write_to("save.json.tmp") → rename("save.json.tmp", "save.json")
```

A crash mid-write leaves the previous save intact and a stale `.tmp` that is ignored on read.

---

## 11. Build System & Dependencies

### 11.1 Cargo Dependencies

| Crate            | Version | Purpose                              |
|-----------------|---------|--------------------------------------|
| `sola_raylib`   | 0.11    | Raylib 5.5 bindings (rendering, audio, input, shaders) |
| `mlua`          | 0.10    | Lua 5.4 FFI bindings (feature = "lua54") |
| `serde`         | 1.0     | JSON serialization (derive)          |
| `serde_json`    | 1.0     | JSON parsing/serialization           |
| `directories`   | 5.0     | Platform-specific data directory paths |
| `clap`          | 4.4     | CLI argument parsing                 |
| `log`           | 0.4     | Logging facade                       |
| `env_logger`    | 0.11    | Log implementation                   |

### 11.2 Build Modes

| Mode              | Command              | Output              |
|-------------------|----------------------|---------------------|
| Development       | `cargo run`          | Native binary       |
| Export            | `cargo run -- export <project>` | Fused binary (assets embedded) |
| Web export        | `cargo run -- web-export <project>` | wasm32-emscripten bundle |
| Init (new project)| `cargo run -- init <name>` | Scaffolded project directory |
| Tools             | `cargo run -- tools <project>` | Debug tools window  |

### 11.3 Web Build Flags

Emscripten build enables:
- `USE_OGG=1`, `USE_VORBIS=1` (OGG music support)
- `USE_WEBGPU=0` (Canvas2D fallback)
- `--js-library` for localStorage save shim (`web/usagi_save.js`)

### 11.4 Shader Compilation

Shaders are compiled at runtime via raylib's `LoadShaderFromMemory()`. Vertex shader is hardcoded; fragment shaders are loaded from disk. No pre-compilation step.

---

## 12. Export System

### 12.1 Native Export

```
cargo run -- export <project_dir>
→ <project_dir>/<name> (executable with embedded assets)
```

The exported binary:
- Embeds all assets (sprites.png, sfx/, music/, shaders/, Lua scripts) into the binary.
- Uses `BundleBacked` VFS (in-memory, no mtimes, no reload).
- Uses bundle hash as game_id fallback.

### 12.2 Web Export

```
cargo run -- web-export <project_dir>
→ <project_dir>/web/ (HTML + WASM + JS)
```

The web build:
- Compiles to wasm32-unknown-emscripten.
- Uses `localStorage` for save data.
- OGG music support enabled.
- Includes custom shell HTML with fullscreen button.

---

## 13. Debug Tools Window

### 13.1 Access

Press `F1` or launch with `cargo run -- tools <project>`.

### 13.2 Panels

| Panel            | Content                                          |
|-----------------|--------------------------------------------------|
| FPS             | Current frames per second (1-frame rolling avg)  |
| Memory          | Approximate heap usage                           |
| VFS Browser     | Lists all assets in the VFS (scripts, sfx, music)|
| Input Tester    | Shows all action bindings (keyboard + gamepad)   |
| Keybind Editor  | Remap keyboard/gamepad bindings per action       |
| Gamepad Config  | Per-game gamepad binding editor                  |

### 13.3 Input Tester

- Shows each action with its keyboard and gamepad bindings.
- Highlights active bindings when the action is pressed.
- Face button labels change based on detected gamepad family (Xbox/PlayStation/Nintendo).

---

## 14. Logging & Error Handling

### 14.1 Structured Logging

`msg!` macro family (`msg::info!`, `msg::warn!`, `msg::error!`):
- Format: `[<level>] <message>`
- Output: stderr (via `env_logger`)
- Gamepad connect/disconnect events use `msg::info!`

### 14.2 Lua Error Handling

- Lua errors are caught and logged via `msg::error!`.
- Error messages include the Lua stack trace.
- Script reload failures don't crash the engine; the last known-good state is preserved.

### 14.3 Stack Traces

- Chunk names in stack traces match the resolved module path (e.g., `"world/tiles.lua"`).
- Meta chunk files (`---@meta`) are excluded so they don't appear in traces.

---

## 15. Example Game Patterns

### 15.1 Snake (from `examples/snake/`)

**Architecture**:
- `main.lua`: Entry point, defines `_config`, `_init`, `_update`, `_draw`.
- Uses `gfx.print`, `gfx.rect`, `gfx.color` for rendering.
- Uses `input.action_pressed` for directional input.
- Uses `sfx.play` for eat/death sounds.
- Uses `usagi.random_int` for food placement.

**Conventions observed**:
- `_config` defines `game_id`, `title`, `width`, `height`.
- Game state held in a single `state` table.
- Fixed timestep via `dt` accumulation.
- `gfx.cam` used for camera tracking.

### 15.2 General Patterns

1. **State table**: All game state in a single Lua table, passed through `_update`/`_draw`.
2. **Module separation**: Complex games split logic into modules (`require "entities"`, `require "ui"`).
3. **Sprite animation**: Frame counter incremented in `_update`, passed to `gfx.sprite(tile, x, y, frame)`.
4. **Input polling**: `input.action_pressed` in `_update` for one-shot actions; `input.action_down` for continuous movement.
5. **Audio cues**: `sfx.play` called on game events (collision, pickup, death).
6. **Juice effects**: `effect.hitstop` on hits, `effect.screen_shake` on impacts, `effect.flash` on transitions.

---

## 16. Rendering Pipeline Details

### 16.1 Frame Render Sequence

```
1. gfx.bg(color)          ← clear RT with background color
2. user _draw() calls     ← render game objects
3. apply shake offset     ← translate RT-to-screen blit
4. draw flash overlay     ← full-screen color with alpha decay
5. blit RT to screen      ← bilinear filter, stretched to window
```

### 16.2 Render Target

- Fixed resolution set by `gfx.set_resolution()` or `_config.width`/`_config.height`.
- Stored as a `rl::Texture2D` (raylib texture).
- Resized automatically when resolution changes.

### 16.3 Blit Configuration

- **Filter**: Bilinear (linear interpolation).
- **Scaling**: Stretch to fill window (no integer scaling).
- **Color mod**: None (palette colors are baked into pixel data).

---

## 17. Live-Reload System

### 17.1 Trigger

On each frame, `FsBacked::freshest_lua_mtime()` is compared against the last reload timestamp. If any `.lua` file under the project root is newer, all Lua scripts are reloaded.

### 17.2 Reload Process

1. Save the current Lua VM context (globals, C closures, registry).
2. Execute the new `main.lua` (which re-sources all `require`d modules).
3. Replace the old context with the new one.
4. Call `_init()` on the new state.
5. If reload fails mid-way, preserve the previous context.

### 17.3 Exclusions

- `meta/usagi.lua` (LSP stub) is excluded from mtime tracking.
- Non-`.lua` files trigger reload only via `freshest_data_mtime()` (for `usagi.read_json` / `usagi.read_text`).

### 17.4 Bundle Games

`BundleBacked` returns `None` for all mtime functions and `false` for `supports_reload()`. No live-reload in exported games.

---

## 18. Known Constraints & Edge Cases

### 18.1 Input

- **Key table limit**: Under 128 keys (bitmask size). Currently 75 keys.
- **Gamepad limit**: 4 slots (hardcoded).
- **Switch face buttons**: Automatically swapped for Nintendo family; no manual override.
- **Direct key reads bypass remapping**: `input.key_*` ignores `Keymap` overrides.

### 18.2 Audio

- **SFX limits**: 256 samples, 48 kHz, mono. No resampling at runtime (speed parameter stretches sample).
- **Music streaming**: Streams from memory buffer; no disk I/O during playback.
- **Web music**: OGG is the most tested format for emscripten builds.

### 18.3 Save Data

- **game_id required**: First save/load call validates game_id. Games without saves don't need one.
- **JSON limitations**: No functions, no userdata, no mixed keys, no sparse arrays.
- **Web saves**: localStorage has ~5MB limit per origin.

### 18.4 Rendering

- **No integer scaling**: RT is always stretched via bilinear filter.
- **No multi-RT**: Single render target per frame.
- **No alpha blending**: Default rendering is opaque (palette-based).

### 18.5 Lua

- **No `dofile`**: Only `require` is supported for module loading.
- **No `loadstring`**: Code execution via string is disabled for security.
- **Single VM**: One Lua state per session. Context is swapped on reload.

---

## 19. References

| Topic              | Source File(s)                              |
|--------------------|---------------------------------------------|
| Game loop, VM, API registration | `src/session.rs` (lines 501–1000+) |
| Graphics API       | `src/session.rs` (`setup_gfx_api`)          |
| Input actions      | `src/input.rs` (lines 1–500)                |
| Input key table    | `src/input.rs` (`KEY_TABLE`, `BINDINGS`)    |
| Gamepad families   | `src/input.rs` (`GamepadFamily`, `button_label`) |
| Sound effects      | `src/sfx.rs`                                |
| Background music   | `src/music.rs`                              |
| Juice effects      | `src/effect.rs` (lines 1–332)               |
| VFS trait          | `src/vfs.rs` (lines 1–100)                  |
| Module loading     | `src/vfs.rs` (`module_candidates`)          |
| Live-reload        | `src/vfs.rs` (`freshest_lua_mtime_under`)   |
| Sprite rendering   | `src/session.rs` (render pipeline)          |
| Palette system     | `src/palette.rs`                            |
| Save system        | `src/save.rs` (lines 1–418)                 |
| JSON validation    | `src/save.rs` (`validate_json_table`)       |
| Shader loading     | `src/shader.rs`                             |
| Entry point        | `src/main.rs`                               |
| Bundle             | `src/bundle.rs`                             |
| Export             | `src/export.rs`, `src/web_export.rs`        |
| Debug tools        | `src/tools.rs`                              |
| CLI args           | `src/main.rs` (mode dispatch)               |
| Dependencies       | `Cargo.toml`                                |
| Keymap persistence | `src/keymap.rs`                             |
| Gamepad map        | `src/pad_map.rs`                            |
| Game ID            | `src/game_id.rs`                            |
| Settings           | `src/settings.rs`                           |
| Logging            | `src/msg.rs`                                |

---

*Spec compiled from direct source code analysis of `usagi-source/`. All API surfaces, data structures, and behavioral descriptions are derived from the actual implementation.*
