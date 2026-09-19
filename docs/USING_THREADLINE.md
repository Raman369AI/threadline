# Using Threadline

[Documentation home](README.md) · [Project home](../README.md)

Threadline is a standalone visual reviewer. Give it a local directory containing Python source; it parses the files without installing, importing, or running the target project.

## Install from PyPI

Python 3.12 or later is required. On Linux or macOS, create a virtual environment and install the published beta:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --pre threadline-review
.venv/bin/threadline review /path/to/python-repository
```

To update an existing installation, run `.venv/bin/python -m pip install --upgrade --pre threadline-review`.

The last command prints and opens a local address, normally <http://127.0.0.1:4173/>. Use **Endpoints**, **Commands & tasks**, or **Modules & methods**. The search box finds items across all three pages. Endpoints has tabs for the HTTP verbs found in the repository. Choose a module to see its functions and methods; filter within that module, then select a method to open the existing workflow. Supported calls into other modules show the caller and target module names. The first page defaults to Endpoints when routes exist, then Commands & tasks, then Modules & methods. No method is selected automatically. One click opens the selected workflow and method. Route paths reflect declarations in source; runtime mounts and registration may add prefixes. Select a step to open the exact source while the surrounding flow remains visible.

## Install from a source checkout

For development or to try the bundled example:

```bash
git clone https://github.com/Raman369AI/threadline.git
cd threadline
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/threadline review example
```

The `example` directory is included in the source repository. For a PyPI installation, point `threadline review` at your own Python source directory.

## Share this beta

To share a local build directly, build a wheel and give the resulting file to another reviewer:

```bash
python3 -m pip wheel . --no-deps --wheel-dir dist
```

They install and run it locally:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install threadline_review-0.2.0b2-py3-none-any.whl
.venv/bin/threadline review /path/to/python-repository
```

No target-project installation or configuration is needed. Maintainers can follow the [PyPI publishing guide](PUBLISHING.md) to configure and publish package releases.

## Review a change

From a Git working tree, compare Python changes with an explicit baseline:

```bash
threadline review /path/to/git-repository --base HEAD
```

Open the **Changes** view for paged lists of changed methods, previous methods, current callers, baseline callers, and possible impact. Select a current method to inspect its source, choose **Compare before / after** to read both retained versions together, or choose **Trace workflow** to follow its calls. Comparisons support added and deleted definitions and file renames; ambiguous duplicate names or parse failures are shown without inventing a counterpart.

**Open baseline** shows the retained previous source. The baseline banner includes **Return to change review**. Baseline callers preserve historical source-linked calls to changed or deleted definitions; they do not establish that those calls still resolve in the working tree. Possible calls remain separate from known relationships.

Threadline does not check out or execute either version. Temporary loading failures appear with a **Retry** action; a failed refresh keeps the previous review available.

## Use structured commands

The browser is the primary interface. These commands are available for scripts and CI:

```bash
threadline inspect /path/to/python-repository --query create_order
threadline inspect /path/to/python-repository --entrypoint package.module:create_order
threadline changes /path/to/git-repository --base HEAD
```

Use `--source-root` for an application source directory and repeat `--exclude` for generated, vendored, or irrelevant trees.

## Validate public repositories

The maintained corpus pins Flask, Requests, FastAPI, Celery, Django, OpenTelemetry, and Pants commits. See the [public repository validation record](ONLINE_VALIDATION.md) for the corpus and measured results. The runner clones source into a temporary directory and checks parsing, statement and call accounting, method inputs and outputs, branches, workflow pagination, uncertainty labels, original evidence retrieval, absence of target imports, and an unchanged Git working tree.

```bash
python tests/online_repo_smoke.py
python tests/online_repo_smoke.py --repo fastapi
python tests/online_repo_smoke.py \
  --cache-dir /tmp/threadline-online \
  --report artifacts/online-validation.json
```

After the first cached run, use `--offline` to prove the check does not need the network. The scheduled GitHub Actions workflow stores the JSON report as an artifact.

These checks validate static source representation. They do not observe runtime dispatch or prove program correctness.

## Read larger workflows

Workflow steps appear one page at a time. **Load more workflow details** adds steps,
control-flow alternatives, and uncertainty records while keeping the selection in
place. A count always shows how much has loaded. Existing stage and depth limits
remain explicit.

Open a branch to fetch its body. **Load more branch statements** continues that body;
opening a nested branch fetches its own statements. **Expand visible branches** opens
the branch controls currently present in the method view. It does not recursively
expand the whole repository.
