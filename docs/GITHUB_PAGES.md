# GitHub Pages review generator

The `pages/` prototype turns a public GitHub repository URL into an interactive
Threadline review, entirely in the visitor's browser. It can be hosted on GitHub
Pages without a Python server or an API key.

## Use the generator

1. Paste a repository URL such as `https://github.com/psf/requests`.
2. Optionally open **Branch and source folder** to choose a branch, tag, commit,
   or source folder such as `src/requests`. Otherwise the default branch is used.
3. Select **Generate review**. The page fetches source, starts Python, and builds
   the same standalone HTML format as `threadline review --output`.
4. Explore the embedded review or select **Download HTML**. The file works offline.

**Cancel** stops downloads and terminates the analyzer worker. You can start a new
review afterward. Generating a review does not publish the reviewed source or
create a shareable review URL. The downloaded HTML includes the reviewed source.

## Run locally

From the repository root, with Python 3.12 or later:

```bash
python scripts/build_pages.py
python -m http.server 8080 --bind 127.0.0.1 --directory build/pages
```

Open `http://127.0.0.1:8080`. Use an HTTP server, not a `file://` URL: workers and
runtime downloads need HTTP. Production hosting must use HTTPS.

The builder packages the current Threadline source and its browser assets into
an archive with a content hash in its filename. It also downloads and caches
Pyodide 0.28.3, which supplies CPython 3.13. Runtime downloads and cache entries
are verified against pinned SHA-256 hashes; runtime license notices are included.
The output in `build/pages/` is the
complete static site. Do not commit `build/`.

## Publish on GitHub Pages

The workflow `.github/workflows/pages.yml` builds, tests, and deploys this site.

1. Push the generator and workflow to the repository's `main` branch.
2. In the repository's **Settings → Pages → Build and deployment**, choose
   **GitHub Actions** as the source.
3. Run **GitHub Pages review generator** from the **Actions** tab. Relevant
   subsequent changes on `main` deploy automatically after its checks pass.
4. Use the deployment URL reported by GitHub Actions. For this repository,
   without a custom domain, it is expected to be
   `https://raman369ai.github.io/threadline/`.

These are deployment instructions, not a statement that the site is already live.
If using a different default branch, update the workflow's branch filter. Relative
asset paths support both an account site and a repository subpath.

See GitHub's [custom Pages workflow documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

## How source is handled

- The page requests repository metadata and resolves the requested ref to a
  commit SHA. It fetches that commit's recursive Git tree, then selected files
  directly from `raw.githubusercontent.com` using the immutable commit SHA.
- Downloads retain the original bytes, and each file is checked against the
  tree's Git blob hash. A failed or incomplete download stops generation.
- Python files, root `pyproject.toml`, and HTML/Jinja template files are retained.
  Standard analyzer exclusions such as `.venv`, `node_modules`, and `build`
  apply. Symbolic links and submodules are not followed; the result reports them.
- Threadline's trusted package runs in a Web Worker using Pyodide's in-memory
  filesystem. Target source is never imported, installed, or executed, and its
  directory is never added to Python's import path.
- The preview runs in a sandboxed iframe. The exported review's existing content
  security policy blocks network requests and keeps source embedded as inert JSON.
- Only GitHub receives requests for the target repository. No source is uploaded
  to a separate analysis service or stored in a server-side database. The Python
  runtime and Threadline package are served as static assets from the Pages site.

## Prototype limits

- Public GitHub repositories only; no token input or private repository login.
- A single source snapshot, without Git history or baseline comparisons.
- At most 1,500 selected files, 16 MiB of downloaded source, and 2 MiB per file.
  The analyzer and HTML exporter retain their own additional budgets. Use a
  source folder or the local CLI for larger projects.
- GitHub's truncated recursive tree responses are rejected, so extremely large
  repositories require the local CLI even when only one source folder is wanted.
- The browser Python version is 3.13. Syntax requiring a newer Python may appear
  as parse errors; see **Instructions → Coverage**. Use the CLI with the needed
  Python version in that case.
- Selecting a source folder excludes Python and templates outside it. Cross-folder
  calls or templates may therefore remain unresolved.
- GitHub's unauthenticated API rate limits apply (normally three API requests per
  generation, with separate raw-file requests). Rate-limit errors are shown in the
  page. See [GitHub's rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api).
- A five-minute page deadline terminates stalled downloads or analysis. Browser
  memory and the initial runtime download can make the CLI preferable for big
  codebases. Chrome has automated coverage; other browsers still need validation.

## Validate

```bash
python -m pip install -e '.[browser-test]'
npm ci --prefix tests/browser-tools --ignore-scripts --no-audit --no-fund
node --test tests/pages.test.mjs
python scripts/build_pages.py
python tests/pages_browser.py
python tests/pages_browser.py --live
```

The default browser test uses deterministic GitHub responses and the real local
Pyodide runtime. It compares exported source and method evidence with native
Python, verifies source stays inert, exercises cancellation and retry, checks
preview navigation and standalone reopening, and checks landing accessibility
and mobile layout. `--live` additionally fetches `psf/requests` from GitHub and
generates its review without mocking network responses.
