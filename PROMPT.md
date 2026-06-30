#PROMPT
Model Context Protocol (MCP) Specification: Direct-to-Hardware Multimodal Expression Server (Usagi Engine Edition)

1. Executive Summary

This project specifies a Model Context Protocol (MCP) server that provides a local, direct-to-hardware 2D visual expression layer for upstream LLM agents. Operating on a headless, multi-user Linux machine without a desktop environment, this server exposes a tool that converts natural language intent into real-time pixel animations, juice effects, and retro graphics rendered straight to a connected monitor. 

The server encapsulates the Usagi Engine sandbox, handles the deployment of dynamic Lua scripts to Usagi's live-reload architecture, and relies on an OpenAI-compatible local endpoint to handle the code generation, visual evaluation, and console self-healing steps. 

2. Architecture & The MCP Interface

The system is exposed as an MCP server running over standard input/output (stdio). It provides a core tool designed to abstract the entire visual execution and verification lifecycle.

┌──────────────────────┐ ┌──────────────────────────────┐ │ │ Tool Call │ 🖥️ BARE-METAL MCP SERVER │ │ 🤖 UPSTREAM MASTER ├───────────────►│ │ │ AGENT │ (user_intent) │ 1. Queries Local OpenAI API │ │ │ │ 2. Writes to llm_output.lua │ └──────────────────────┘ │ 3. Snaps Framebuffer & Logs │ ▲ │ 4. Self-Heals Anomalies │ │ Tool Response └──────────────┬───────────────┘ └───────────────────────────────────────────┘ (Success Confirmation + Final Code) 

2.1 The Visual Expression Tool Schema

The server must expose a primary tool named render_expression accepting a single input parameter:

user_intent (string, required): A detailed description of the emotion, UI state, animation, or message the upstream agent wants to visually project onto the bare-metal screen.

2.2 Tool Execution Lifecycle

When the tool is called, the MCP server handles the following synchronous phases internally before returning a final response:

Payload Generation Phase: The server hits a local OpenAI-compatible API endpoint using structured JSON outputs (response_format: { "type": "json_object" }). The endpoint returns a JSON block containing its reasoning and a raw string of complete, valid Lua code. 

Direct Hardware Compilation: The server writes this code to llm_output.lua inside the Usagi project workspace. Usagi automatically detects the file write, preserving its global State table while hot-swapping the rendering logic directly over the Linux Direct Rendering Manager (DRM) or Kernel Mode Setting (KMS) layers.

Triangulated Sampling Phase: The server waits a designated rendering interval (~500ms), then scrapes the system's active standard output/error pipes and grabs a raw hardware snapshot of the Linux framebuffer (/dev/fb0).

Self-Correction & Healing Pass: The server bundles the visual snapshot (as a base64 Data URL) and console logs into a new chat completion request to the local OpenAI endpoint. If a crash or layout bug is found, the endpoint returns corrected Lua code, and the server updates llm_output.lua again.

Tool Return Execution: Once validated, the tool closes its cycle and returns a success status along with the clean executable code to the upstream master agent.

3. Core Technical & Environment Requirements

3.1 Local Intelligence Node Configuration

Endpoint Compatibility: The orchestration server must interact with an inference engine (such as Ollama, vLLM, or llama.cpp) utilizing the standard OpenAI Chat Completions endpoint (v1/chat/completions). 

Vision & Structured Capabilities: The target local model (e.g., Gemma 4 12B or equivalent multimodal weights) must support system prompt directives, JSON Schema mode, and vision array inputs (image_url data objects).

Deterministic Code Separation: System prompts provided to the local endpoint must enforce strict code insulation. The model must isolate executable Usagi code from its reasoning steps by packaging its thoughts inside an explicit, parseable JSON dictionary wrapper.

3.2 Bare-Metal Graphics Pipeline & Usagi Engine

Target Environment: Systemd headless target (multi-user.target) completely stripped of Wayland, X11, window managers, or desktop environments.

Direct Render Constraints: The Usagi game engine execution environment must be explicitly directed to bypass window servers. This is enforced by declaring the native hardware rendering backend (RAYLIB_BACKEND=drm) and targeting the kernel video memory node (FRAMEBUFFER=/dev/fb0).

System Privilege Mapping: The server process must run under a user profile with access to the system's video, render, and input hardware groups to execute without root elevation.

Console Cleanup: The server must suppress virtual terminal cursor blinking and TTY text bleed to ensure Usagi's 320x180 canvas remains completely unmarred on the physical monitor.

3.3 Usagi Workspace & State Memory Preservation

Persistent Skeleton Layer: A fixed main.lua container manages initialization properties, tracks delta time (dt) inside the engine frame loop, and runs the dynamic llm_output payload functions wrapped within protective runtime guards (pcall). This prevents unhandled model syntax crashes from tearing down the display daemon.

Capitalized State Preservation: The system prompt given to the local OpenAI endpoint must explicitly teach the model that Capitalized global variables survive Usagi hot-reloads. Persistent parameters (e.g., State.UserName, State.MoodScale) must be housed inside this global index to preserve memory between consecutive tool calls.

Layout Constraints: The local model must be instructed to target a locked resolution of exactly 320x180 pixels and utilize Usagi's built-in 16-color palette indices and kinetic juice functions (such as effect.screen_shake and effect.flash).

3.4 Non-Blind Verification Framework

Raw Frame Sampling: Screen captures must bypass window-manager tools and read directly from the kernel memory layer (/dev/fb0) using hardware capture binaries (such as fbgrab), downsampling or cropping the image as needed to align with the engine's true coordinate layout.

Telemetry Analysis Matrix: The verification check must map the stdout/stderr tracebacks alongside spatial layout checking (verifying that elements avoid layout collisions, remain legible against background color palettes, and do not clip beyond the 320x180 viewport bounds).

4. Evaluation Criteria for the Autonomous Building Agent

An agent tasked with constructing this MCP server can validate the implementation through the following automated acceptance tests:

MCP & API Handshake Test: The server initializes correctly over stdio, registers the tool schema, and successfully executes a connection handshake with the local OpenAI-compatible endpoint.

Bare-Metal Display Output Test: Executing the tool from a remote SSH terminal or a headless system account successfully launches Usagi, which draws shapes, animations, and kinetic text onto the locally connected physical monitor.

Self-Healing Verification: Providing an intent that forces bad placement or introducing synthetic code syntax breaks inside the payload file causes the server to catch the error via stderr/framebuffer sampling and execute an autonomous corrective pass through the local API before the tool call completes.
