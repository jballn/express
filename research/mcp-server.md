# MCP Server Architecture Research

## Model Context Protocol (MCP) Overview
- MCP uses JSON-RPC 2.0 over stdio for client-server communication
- Messages MUST be UTF-8 encoded
- Two standard transports: stdio and Streamable HTTP
- Protocol defines tools, resources, prompts, and sampling

## MCP Server Implementation

### Python SDK (mcp)
- Package: `mcp` on PyPI
- Key classes: `MCPServer`, `Tool`, `Resource`
- Tools defined with decorators or explicit registration
- Responses formatted as JSON with content arrays
- Supports images via base64 data URLs in content

### Tool Schema Format
```python
@server.tool()
def render_expression(expression: str) -> list:
    """Render a Lua expression and return result"""
    return [{"type": "text", "text": result}]
```

### Tool Response Format
```json
{
  "content": [
    {"type": "text", "text": "Result text"},
    {"type": "image", "data": "base64...", "mimeType": "image/png"}
  ],
  "isError": false
}
```

## Server Architecture Pattern
1. Server initializes over stdio
2. Registers tool schema with name, description, parameters
3. Client sends tool call request via JSON-RPC
4. Server executes tool synchronously
5. Returns structured response with content
6. Server shuts down after response (for one-shot tools)

## Key Design Decisions
- Synchronous execution within tool call (no async/await for simple tools)
- Timeout handling: Python `signal.alarm` or threading with timeout
- Image capture: framebuffer read -> PNG encode -> base64 encode
- Console log capture: subprocess stderr/stdout collection
- Self-healing: call local LLM API with screenshot + logs -> get corrected code

## Local LLM Integration
- OpenAI-compatible API endpoint (llama.cpp server, Ollama, vLLM)
- Structured output via JSON schema
- Vision models for screenshot analysis
- System prompt enforcement for code generation style
