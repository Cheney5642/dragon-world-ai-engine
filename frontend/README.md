# Dragon World Frontend Shell v0.1

This directory contains the read-only Next.js App Router shell for Dragon World. It visualizes the current persistent world state exposed by the FastAPI bridge. Action preview and commit are intentionally deferred to Step 5.4.3.

## Development

Start the backend from the project root:

```bash
python -m uvicorn api.app:app --reload
```

Start the frontend in a second terminal:

```bash
cd frontend
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Environment

Copy `.env.local.example` to `.env.local` and configure:

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

Only a public API base URL belongs in the frontend environment. Provider credentials such as `ARK_API_KEY` must remain in the backend root `.env` and must never use the `NEXT_PUBLIC_` prefix.
