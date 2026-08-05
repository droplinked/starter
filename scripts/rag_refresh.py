#!/usr/bin/env python3
"""Build / refresh the droplinked AI-assistant RAG corpus from the Mintlify docs.

The in-house merchant assistant (droplinked-backend `src/modules/ai`) grounds its
answers in an OpenAI vector store via the Responses API `file_search` tool. This
script is the *ingestion source of truth* for that store, and it pulls from the
published Mintlify docs ONLY:

    https://docs.droplinked.com/llms-full.txt

That single artifact is Mintlify's own concatenation of every published doc page
(this repo's .mdx tree, rendered), one block per page with a
`Source: https://docs.droplinked.com/...` line. It is always in lock-step with
what a reader sees, which makes it the ideal RAG source.

This REPLACES the previous ad-hoc pipeline that scraped the retired GitBook
spaces (droplinked.gitbook.io) into the same store. No GitBook is ingested here.

Design:
  * stdlib only (urllib) — no pip deps, mirrors scripts/curate-openapi.py.
  * sha256-keyed, diff-driven: unchanged pages are never re-uploaded / re-embedded,
    so a no-op refresh costs nothing. Only new/changed pages are uploaded and only
    removed pages are detached.
  * FAIL-SAFE by default. With no `--apply` (or no OPENAI_API_KEY) it runs in PLAN
    mode: it computes the diff, writes the manifest, prints what WOULD change, and
    exits 0 without touching OpenAI. A full (re)build only happens on an explicit
    `--apply` with a key present.

Usage:
  # plan only (no key needed, no cost) — shows new/changed/removed page counts
  python3 scripts/rag_refresh.py

  # apply into an EXISTING store (diff-driven; cheap on a small delta)
  OPENAI_API_KEY=sk-... RAG_VECTOR_STORE_ID=vs_xxx python3 scripts/rag_refresh.py --apply

  # apply with NO store id -> mints a fresh Mintlify-only store and prints its id
  OPENAI_API_KEY=sk-... python3 scripts/rag_refresh.py --apply

Env:
  OPENAI_API_KEY        required for --apply; absent => forced PLAN mode.
  RAG_VECTOR_STORE_ID   target store; if unset on --apply, a new store is minted.
  LLMS_FULL_URL         override source (default https://docs.droplinked.com/llms-full.txt).
  RAG_MANIFEST          manifest path (default scripts/rag-corpus-manifest.json).

After an --apply that mints a new store, repoint the backend at the printed id —
see the "REPOINT" note printed at the end.
"""
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.request

LLMS_FULL_URL = os.environ.get(
    "LLMS_FULL_URL", "https://docs.droplinked.com/llms-full.txt"
)
MANIFEST_PATH = os.environ.get(
    "RAG_MANIFEST",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "rag-corpus-manifest.json"),
)
OPENAI_BASE = "https://api.openai.com/v1"
SOURCE_RE = re.compile(r"^Source:\s*(https://docs\.droplinked\.com/\S+)\s*$", re.M)


def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "droplinked-rag-refresh"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def slugify(url):
    """docs.droplinked.com/a/b/c -> a__b__c ; used as the uploaded filename."""
    path = url.split("docs.droplinked.com/", 1)[-1].strip("/")
    slug = re.sub(r"[^a-zA-Z0-9]+", "__", path).strip("_")
    return (slug or "index") + ".md"


def split_pages(text):
    """Split llms-full.txt into per-page docs keyed by the Source: URL.

    Each page starts with an H1 line immediately followed by a `Source: <url>`
    line. We anchor on the Source lines and slice from the H1 above each one to
    the H1 above the next, so every page is a self-contained markdown doc.
    """
    lines = text.split("\n")
    # index every `Source:` line and the H1 that introduces its page
    starts = []  # (h1_line_index, source_url)
    for i, ln in enumerate(lines):
        m = SOURCE_RE.match(ln)
        if not m:
            continue
        # the page's H1 is the nearest preceding line starting with "# "
        h1 = i - 1
        while h1 >= 0 and not lines[h1].startswith("# "):
            h1 -= 1
        starts.append((h1 if h1 >= 0 else i, m.group(1)))
    pages = []
    for idx, (h1, url) in enumerate(starts):
        end = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        body = "\n".join(lines[h1:end]).strip() + "\n"
        pages.append({"source_url": url, "filename": slugify(url), "content": body})
    # de-dup by filename (defensive: keep the longest body per slug)
    dedup = {}
    for p in pages:
        cur = dedup.get(p["filename"])
        if cur is None or len(p["content"]) > len(cur["content"]):
            dedup[p["filename"]] = p
    return list(dedup.values())


def sha256(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ---- OpenAI (stdlib multipart; only reached on --apply) ---------------------


def _api(method, path, key, body=None, ctype="application/json"):
    data = None
    headers = {"Authorization": f"Bearer {key}"}
    if body is not None:
        if ctype == "application/json":
            data = json.dumps(body).encode()
            headers["Content-Type"] = ctype
        else:
            data, headers["Content-Type"] = body  # (bytes, multipart-content-type)
    req = urllib.request.Request(OPENAI_BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def _multipart_upload(filename, content, key):
    boundary = "----droplinkedrag" + hashlib.md5(filename.encode()).hexdigest()
    buf = io.BytesIO()
    def w(s):
        buf.write(s.encode() if isinstance(s, str) else s)
    w(f"--{boundary}\r\n")
    w('Content-Disposition: form-data; name="purpose"\r\n\r\nassistants\r\n')
    w(f"--{boundary}\r\n")
    w(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n')
    w("Content-Type: text/markdown\r\n\r\n")
    w(content)
    w(f"\r\n--{boundary}--\r\n")
    return _api("POST", "/files", key,
                body=(buf.getvalue(), f"multipart/form-data; boundary={boundary}"),
                ctype="multipart")


def mint_store(key):
    name = f"droplinked Assistant — Mintlify-only {time.strftime('%Y-%m-%d')}"
    return _api("POST", "/vector_stores", key, {"name": name})["id"]


def attach(store, file_id, key):
    return _api("POST", f"/vector_stores/{store}/files", key, {"file_id": file_id})


def detach(store, file_id, key):
    try:
        _api("DELETE", f"/vector_stores/{store}/files/{file_id}", key)
        _api("DELETE", f"/files/{file_id}", key)
    except Exception as e:  # noqa: BLE001 - best-effort cleanup
        print(f"  warn: detach {file_id} failed: {e}")


def main():
    apply = "--apply" in sys.argv
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    store = os.environ.get("RAG_VECTOR_STORE_ID", "").strip()

    print(f"[rag] source: {LLMS_FULL_URL}")
    text = fetch(LLMS_FULL_URL)
    pages = split_pages(text)
    print(f"[rag] parsed {len(pages)} Mintlify pages ({len(text)} bytes)")
    if not pages:
        print("[rag] ERROR: no pages parsed — refusing to touch the store")
        return 2

    old = {}
    if os.path.exists(MANIFEST_PATH):
        prev = json.load(open(MANIFEST_PATH))
        old = {f["filename"]: f for f in prev.get("files", [])}

    new_files, changed, unchanged = [], [], []
    for p in pages:
        p["sha256"] = sha256(p["content"])
        o = old.get(p["filename"])
        if o and o.get("sha256") == p["sha256"]:
            p["openai_file_id"] = o.get("openai_file_id")
            unchanged.append(p)
        elif o:
            changed.append(p)
        else:
            new_files.append(p)
    removed = [o for fn, o in old.items() if fn not in {p["filename"] for p in pages}]

    print(f"[rag] plan: {len(new_files)} new, {len(changed)} changed, "
          f"{len(unchanged)} unchanged, {len(removed)} removed")

    manifest = {
        "source": LLMS_FULL_URL,
        "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "gitbook_ingested": False,
        "target_store": store or None,
        "files": [{k: p.get(k) for k in ("filename", "source_url", "sha256", "openai_file_id")}
                  for p in pages],
    }

    if not apply or not key:
        reason = "no --apply flag" if not apply else "no OPENAI_API_KEY"
        print(f"[rag] PLAN mode ({reason}) — writing manifest, NOT touching OpenAI (0 cost)")
        json.dump(manifest, open(MANIFEST_PATH, "w"), indent=2)
        return 0

    if not store:
        store = mint_store(key)
        print(f"[rag] minted new Mintlify-only store: {store}")
        manifest["target_store"] = store
        # nothing is "unchanged" against a brand-new store
        new_files, changed, unchanged, removed = pages, [], [], []

    for p in changed:
        o = old.get(p["filename"])
        if o and o.get("openai_file_id"):
            detach(store, o["openai_file_id"], key)
    for p in new_files + changed:
        up = _multipart_upload(p["filename"], p["content"], key)
        attach(store, up["id"], key)
        p["openai_file_id"] = up["id"]
        print(f"  + {p['filename']} -> {up['id']}")
    for o in removed:
        if o.get("openai_file_id"):
            detach(store, o["openai_file_id"], key)
            print(f"  - {o['filename']}")

    manifest["files"] = [{k: p.get(k) for k in ("filename", "source_url", "sha256", "openai_file_id")}
                         for p in pages]
    manifest["target_store"] = store
    json.dump(manifest, open(MANIFEST_PATH, "w"), indent=2)

    counts = _api("GET", f"/vector_stores/{store}", key).get("file_counts", {})
    print(f"[rag] store {store} file_counts: {counts}")
    print(f"\n[rag] REPOINT the backend at this store:")
    print(f"      AI_ASSISTANT_VECTOR_STORE_ID={store}")
    print(f"      (droplinked-backend .github/workflows/main.yml + dev.yml,")
    print(f"       and the default in src/modules/ai/config/ai-assistant.config.ts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
