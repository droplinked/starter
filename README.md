# Mintlify Starter Kit

Click on `Use this template` to copy the Mintlify starter kit. The starter kit contains examples including

- Guide pages
- Navigation
- Customizations
- API Reference pages
- Use of popular components

### Development

Install the [Mintlify CLI](https://www.npmjs.com/package/mintlify) to preview the documentation changes locally. To install, use the following command

```
npm i -g mintlify
```

Run the following command at the root of your documentation (where docs.json is)

```
mintlify dev
```

### Publishing Changes

Install our Github App to auto propagate changes from your repo to your deployment. Changes will be deployed to production automatically after pushing to the default branch. Find the link to install on your dashboard. 

#### Troubleshooting

- Mintlify dev isn't running - Run `mintlify install` it'll re-install dependencies.
- Page loads as a 404 - Make sure you are running in a folder with `docs.json`

### AI assistant RAG corpus (Mintlify-grounded)

The in-house merchant AI assistant (`droplinked-backend` `src/modules/ai`) grounds
its answers in an OpenAI vector store queried with the Responses API `file_search`
tool. That store's content is now ingested from these docs ONLY, via
`docs.droplinked.com/llms-full.txt` — the retired GitBook spaces
(`droplinked.gitbook.io`) are no longer ingested.

- **Source of truth:** [`scripts/rag_refresh.py`](./scripts/rag_refresh.py) — fetches
  `llms-full.txt`, splits it per page, and syncs an OpenAI vector store. sha256
  diff-driven, so unchanged pages are never re-embedded.
- **Dry-run (no key, no cost):** `python3 scripts/rag_refresh.py` prints the
  new/changed/removed page plan and writes the manifest.
- **Re-index:** run the [`rag-refresh`](./.github/workflows/rag-refresh.yml) workflow
  with `apply=true` (needs `OPENAI_API_KEY` + optional `RAG_VECTOR_STORE_ID` repo
  secrets). Pushes to `main` run a plan only — a real re-index is manual/gated so
  its embedding-token cost is always explicit. A full 233-page build is small
  (~0.4M tokens ≈ a few cents on `text-embedding-3-*`).
- **Repoint the backend:** after `--apply` mints a new store, set
  `AI_ASSISTANT_VECTOR_STORE_ID` to the printed id in `droplinked-backend`
  `.github/workflows/main.yml` + `dev.yml` and the default in
  `src/modules/ai/config/ai-assistant.config.ts`.
