# AGENTS.md

## Cursor Cloud specific instructions

This repository is a single static HTML page: `index .html` (note the literal space in the filename). There is no backend, build system, package manager, or dependencies.

### Running the site
- Serve from the repo root with Python's built-in server: `python3 -m http.server 8000`
- Because the filename contains a space, open it at the URL-encoded path: `http://localhost:8000/index%20.html` (or just browse the directory listing at `http://localhost:8000/`).

### Notes
- There is nothing to install, lint, build, or test — it is plain HTML with inline CSS.
- The top hero image is loaded from a remote host (`nimg.ws.126.net`) and may render as a broken image due to external hotlink protection; this is expected and unrelated to local setup. The rest of the page (text + the `友情链接` link to `kangwenchang.com`) renders and works normally.
