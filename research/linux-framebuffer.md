# Linux Framebuffer & DRM Research

## Framebuffer Capture Methods

### /dev/fb0 (Legacy Framebuffer Console)
- Direct read of framebuffer memory
- `cat /dev/fb0 > screenshot.rgb` captures raw pixels
- Resolution: typically matches console mode (e.g., 320x200, 640x480)
- Can be resized with `fbset`
- Access requires `video` group or root
- Headless systems may not have /dev/fb0 without framebuffer console enabled

### DRM/KMS (Direct Rendering Manager / Kernel Mode Setting)
- Modern replacement for fbcon
- Uses /dev/dri/card0 for display control
- Requires `render` group access
- Programs like `fbgrab` capture physical display via DRM
- Supports atomic modesetting for tear-free rendering
- Can run without X11/Wayland (headless DRM mode)

### Raylib DRM Backend
- Raylib supports `RAYLIB_BACKEND=drm` for Linux headless
- Uses KMS/DRM directly for rendering to physical display
- Targets `/dev/fb0` via kernel video memory node
- No X11 dependency required
- Runs as non-root with proper group memberships (video, render, input)

## Console Cleanup for Headless Display
- `KD_GRAPHICS` mode suppresses VT text cursor
- `chvt` or `openvt` to switch virtual terminals
- `fbset` to configure framebuffer console resolution
- Kernel ioctl `KDSETMODE` to toggle between text/graphics
- Console cleanup: suppress cursor blinking, clear VT before starting

## Screenshot Capture
- `fbgrab` utility: captures DRM framebuffer to PNG
- Python ctypes can ioctl VT operations for mode switching
- Downsampling to 320x180 for analysis: simple nearest-neighbor scale
- `/dev/fb0` read + manual RGB parsing as fallback

## Linux Groups Required
- `video`: access to /dev/fb0, /dev/dri/*
- `render`: DRM render node access
- `input`: access to input devices (if needed)
