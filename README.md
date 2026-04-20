# Claude OAuth Chat Demo

Minimal local demo that reuses the local OAuth session already stored by `claude` CLI.

## Why this shape

- The backend keeps one persistent `claude` process alive and talks to it using `stream-json` over stdin/stdout.
- The frontend is served by `FastAPI`, so the repo stays small while still getting a browser UI.
- The app reuses the machine's existing Claude Code OAuth credentials instead of asking for an API key.

## Stack

- Backend: `FastAPI`
- Frontend: plain `HTML`, `CSS`, and `JavaScript`
- Claude integration: local `claude` CLI session with SSE streaming

## Run locally

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Ensure the Claude CLI is already authenticated on this machine:

```bash
claude auth login
```

4. Copy `.env.example` to `.env` if you want to change the default model.
5. Start the app:

```bash
uvicorn backend.app.main:app --reload
```

6. Open `http://127.0.0.1:8000`.

## How it works

```text
Browser
  -> POST /api/chat (SSE)
FastAPI
  -> persistent claude process
claude CLI
  -> local OAuth credentials
Anthropic
```

The backend sends a warmup prompt on startup so the first real request usually hits a process that is already ready.

## API

- `GET /health`
- `GET /api/status`
- `POST /api/chat`
- `POST /api/reset`

### `POST /api/chat`

```json
{
  "messages": [
    {"role": "user", "content": "Hola Claude"}
  ],
  "model": "claude-haiku-4-5-20251001"
}
```

The response is `text/event-stream` with `data: {"type":"text","text":"..."}` chunks and a final `data: [DONE]`.

### `POST /api/reset`

```json
{
  "model": "claude-sonnet-4-6"
}
```

Resets the persistent session and optionally switches model.

## Environment

- `API_TOKEN`: optional Bearer token required for `/api/*` when set
- `CLAUDE_MODEL`: startup model
- `CLAUDE_ALLOWED_MODELS`: comma-separated model allowlist
- `CLAUDE_WARMUP_PROMPT`: initial probe prompt for warming the session
- `CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS`: defaults to `true` for parity with the local-demo behavior of the reference architecture

## Security notes

- This project is for local/personal use, not production exposure.
- When `CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS=true`, Claude can execute tools without approval if prompted to do so.
- If you set `API_TOKEN`, all `/api/*` endpoints require `Authorization: Bearer <token>`.
- Do not expose this backend openly without adding your own auth layer.
- The OAuth credentials remain on your machine through the Claude CLI setup; they are not stored in this repo.

### Frontend with API token

If you enable `API_TOKEN`, the browser UI will only work after storing the token locally:

```js
localStorage.setItem("claude_api_token", "tu-token")
```

The frontend then sends it as `Authorization: Bearer <token>` on API calls.

## Tests

```bash
pytest
```

## Notes

- The browser keeps local message history only for rendering; the real conversation context lives in the persistent Claude CLI process.
- Switching model or clicking `Nueva conversacion` restarts the CLI session.
- This is a demo scaffold, not a hardened remote service.
