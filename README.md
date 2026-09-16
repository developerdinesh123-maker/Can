# Paper — Invoice Intelligence

AI-powered multi-document invoice and packing-list extraction app.

## Features

- Upload multiple PDF/JPG/PNG/WEBP documents.
- Ask for fields in natural language.
- Extract invoice and packing-list data with OpenRouter.
- Cross-document reconciliation.
- Packing-list net weight takes priority when a related invoice contains a different value.
- Conflict warnings and source-document tracking.
- JSON and Excel export.
- Docker + Render deployment.
- API key stays server-side in an environment variable.

## Local setup

1. Copy `.env.example` to `.env`.
2. Put your OpenRouter API key into `OPENROUTER_API_KEY`.
3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Start:

```bash
uvicorn app.main:app --reload
```

5. Open `http://localhost:8000`.

## Render deployment

Create a new Web Service from this repository and use the included `render.yaml`.
Set `OPENROUTER_API_KEY` as a Render secret/environment variable.

Do NOT commit `.env` or an API key to GitHub.

## GitHub upload

Upload the contents of this package into the root of your repository. If the repository already has an `app` directory, replace it only after backing up any custom code you want to keep.

## Security

The browser never receives the OpenRouter API key. The key is used only by the FastAPI server.

If a key has ever been pasted into a chat, public repository, screenshot, log, or frontend code, rotate/revoke it at the provider before production use.
