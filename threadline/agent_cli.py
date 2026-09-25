"""Structured and snapshot-pinned command line queries for source review."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import webbrowser
from pathlib import Path
from typing import Any, NoReturn

from .changes import review_changes
from .schema import AnalysisCompleteness, ResponseEnvelope
from .server import make_server
from .service import SCHEMA_VERSION, SnapshotStore, ThreadlineError, _page, _snapshot_id

SESSION_FORMAT = "threadline-snapshot-1"
MAX_SESSION_BYTES = 256 * 1024 * 1024
CHANGE_CATEGORIES = (
    "files", "changedMethods", "renamedMethods", "previousMethods",
    "previousRenamedMethods", "knownCallers", "baselineCallers",
    "possibleImpact", "unassessedChanges", "parseErrors",
)
COMMANDS = {
    "review", "snapshot", "summary", "inspect", "symbols", "workflow",
    "method", "scope", "branch", "source", "diagnostics", "changes", "dataflow",
}


def _print_json(value: Any, *, compact: bool = False) -> None:
    options: dict[str, Any] = {"ensure_ascii": False}
    if compact:
        options["separators"] = (",", ":")
    else:
        options["indent"] = 2
    print(json.dumps(value, **options))


def _error(operation: str | None, code: str, message: str, *, compact: bool = False) -> None:
    _print_json({
        "schemaVersion": SCHEMA_VERSION,
        "operation": operation,
        "error": {"code": code, "message": message},
    }, compact=compact)


class JSONArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        _error(None, "invalid_arguments", message)
        raise SystemExit(2)


def _query_arguments(command: argparse.ArgumentParser, *, paged: bool = True) -> None:
    command.add_argument("project", nargs="?", help="repository directory; omit with --session")
    command.add_argument("--session", help="saved JSON snapshot created by `threadline snapshot`")
    command.add_argument("--snapshot", help="required snapshot ID; reject a different snapshot")
    command.add_argument("--source-root", action="append")
    command.add_argument("--exclude", action="append")
    if paged:
        command.add_argument("--cursor", type=int, default=0)
        command.add_argument("--limit", type=int, default=25)
    command.add_argument("--compact", action="store_true", help="emit compact JSON")
    command.add_argument("--strict-complete", action="store_true", help="exit 3 after a partial analysis result")
    command.add_argument("--format", choices=["json"], default="json")


def _parser() -> JSONArgumentParser:
    parser = JSONArgumentParser(
        prog="threadline",
        description="Review Python source without importing or running the target.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    review = sub.add_parser("review", help="open a live review or export a standalone HTML file")
    review.add_argument("project")
    review.add_argument("--port", type=int, default=4173)
    review.add_argument("--no-open", action="store_true")
    review.add_argument("--output", help="write a standalone HTML review and exit (no server)")
    review.add_argument("--source-root", action="append")
    review.add_argument("--exclude", action="append")
    review.add_argument("--file", action="append", dest="change_files")
    review.add_argument("--base", help="show Python changes against this Git revision")

    snapshot = sub.add_parser("snapshot", help="save a frozen source review for later queries")
    snapshot.add_argument("project")
    snapshot.add_argument("--output", required=True)
    snapshot.add_argument("--base", help="include a Git comparison and its retained baseline")
    snapshot.add_argument("--file", action="append", dest="change_files")
    snapshot.add_argument("--source-root", action="append")
    snapshot.add_argument("--exclude", action="append")
    snapshot.add_argument("--compact", action="store_true")

    summary = sub.add_parser("summary", help="coverage, diagnostics, and entrypoints")
    _query_arguments(summary)

    inspect = sub.add_parser("inspect", help="compatibility command: symbols or a workflow")
    _query_arguments(inspect)
    inspect.add_argument("--entrypoint")
    inspect.add_argument("--query", default="")
    inspect.add_argument("--kind", default="callable")
    inspect.add_argument("--detail", choices=["full", "references"], default="full")

    symbols = sub.add_parser("symbols", help="find definitions")
    _query_arguments(symbols)
    symbols.add_argument("--query", default="")
    symbols.add_argument("--kind", default="callable")

    workflow = sub.add_parser("workflow", help="paged workflow for a definition")
    _query_arguments(workflow)
    workflow.add_argument("--entrypoint", required=True)
    workflow.add_argument("--detail", choices=["full", "references"], default="full")

    method = sub.add_parser("method", help="flattened method operations")
    _query_arguments(method)
    method.add_argument("--symbol", required=True)

    dataflow = sub.add_parser("dataflow", help="paged method values, changes, and optional value trace")
    _query_arguments(dataflow)
    dataflow.add_argument("--symbol", required=True)
    dataflow.add_argument("--node", help="data-flow node ID to trace")
    dataflow.add_argument("--direction", choices=["both", "upstream", "downstream"], default="both")
    dataflow.add_argument("--model-cursor", type=int, default=0,
                          help="offset into referenced model definitions")
    dataflow.add_argument("--detail", choices=["full", "references"], default="full")

    scope = sub.add_parser("scope", help="paged scope statements and branch controls")
    _query_arguments(scope)
    scope.add_argument("--symbol", required=True)
    scope.add_argument("--shallow", action="store_true")

    branch = sub.add_parser("branch", help="paged statements in one branch arm")
    _query_arguments(branch)
    branch.add_argument("--symbol", required=True)
    branch.add_argument("--operation", required=True)
    branch.add_argument("--arm", type=int, required=True)

    source = sub.add_parser("source", help="original source by evidence ID or file span")
    _query_arguments(source, paged=False)
    source.add_argument("--evidence")
    source.add_argument("--file")
    source.add_argument("--start", type=int)
    source.add_argument("--end", type=int)

    diagnostics = sub.add_parser("diagnostics", help="parse errors, exclusions, and unmodeled calls")
    _query_arguments(diagnostics)
    diagnostics.add_argument("--category", default="errors")

    changes = sub.add_parser("changes", help="paged Git change records")
    _query_arguments(changes)
    changes.add_argument("--base")
    changes.add_argument("--file", action="append", dest="change_files")
    changes.add_argument("--category", choices=CHANGE_CATEGORIES, default="files")
    return parser


def _resolve(model: dict[str, Any], selector: str) -> dict[str, Any]:
    choices = [
        scope for scope in model["scopes"].values()
        if selector in (
            scope["id"], scope["qualified"],
            f"{scope['module']}:{scope['qualified']}",
            f"{scope['module']}:{scope['name']}",
        )
    ]
    if len(choices) != 1:
        raise ThreadlineError(
            f"symbol must identify exactly one definition; found {len(choices)} for {selector!r}"
        )
    return choices[0]


def _resolve_query_symbol(model: dict[str, Any], selector: str, args: argparse.Namespace) -> dict[str, Any]:
    selected = _resolve(model, selector)
    if not args.session and not args.snapshot and selector == selected["id"]:
        raise ThreadlineError(
            "--snapshot is required to follow a symbol ID in a live project; "
            "use its snapshotId or a saved --session"
        )
    return selected


def _analysis(model: dict[str, Any]) -> AnalysisCompleteness:
    coverage = model["coverage"]
    skipped = max(0, coverage.get("discovered", 0) - coverage.get("files", 0))
    errors = len(model["errors"])
    configuration_errors = sum(
        issue.get("kind") == "configuration" for issue in model["errors"]
    )
    return {
        "complete": errors == 0 and skipped == 0,
        "parsedFiles": coverage.get("files", 0),
        "discoveredFiles": coverage.get("discovered", 0),
        "skippedFiles": skipped,
        "analysisErrors": errors,
        "parseErrors": errors - configuration_errors,
        "configurationErrors": configuration_errors,
        "excludedPaths": len(model["excluded"]),
        "unmodeledCalls": len(coverage.get("unmodeledCalls", [])),
        "sourceOnly": True,
    }


def _pages(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: {field: value[field] for field in ("total", "nextCursor", "omitted")}
        for key, value in result.items()
        if isinstance(value, dict) and {"items", "total", "nextCursor", "omitted"} <= value.keys()
    }


def _evidence_references(value: Any) -> Any:
    """Keep traceable IDs while omitting repeated source spans in a workflow page."""
    if isinstance(value, list):
        return [_evidence_references(item) for item in value]
    if not isinstance(value, dict):
        return value
    projected = {}
    for key, item in value.items():
        if key == "span" and value.get("evidenceId"):
            continue
        projected[key] = _evidence_references(item)
    return projected


def _envelope(
    operation: str, model: dict[str, Any], result: dict[str, Any], *, detail: str = "full",
) -> ResponseEnvelope:
    pages = _pages(result)
    if operation == 'dataflow':
        pages['models'] = {
            'total': result['modelTotal'],
            'nextCursor': result['nextModelOffset'],
            'omitted': max(0, result['modelTotal'] - result['modelCursor'] - len(result['models'])),
        }
    return {
        "schemaVersion": model["schemaVersion"],
        "operation": operation,
        "detail": detail,
        "snapshotId": model["snapshotId"],
        "analysisOptions": model.get("analysisOptions", {}),
        "analysis": _analysis(model),
        "pagination": pages,
        "truncated": bool(result.get("truncated", False)),
        "omittedRecords": result.get("omitted", 0) + sum(page["omitted"] for page in pages.values()),
        "result": result,
    }


def _write_session(store: SnapshotStore, output: str) -> None:
    target = Path(output).expanduser().resolve()
    document = {
        "format": SESSION_FORMAT,
        "schemaVersion": SCHEMA_VERSION,
        "root": str(store.root),
        "currentSnapshotId": store.current_id,
        "models": list(store._models.values()),
    }
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent,
            prefix=".threadline-snapshot-", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            json.dump(document, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > MAX_SESSION_BYTES:
            raise ThreadlineError("saved snapshot exceeds the 256 MiB limit")
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _read_session(path: str) -> SnapshotStore:
    source = Path(path).expanduser().resolve()
    if source.stat().st_size > MAX_SESSION_BYTES:
        raise ThreadlineError("saved snapshot exceeds the 256 MiB limit")
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ThreadlineError("saved snapshot is not valid UTF-8 JSON") from exc
    if not isinstance(document, dict) or document.get("format") != SESSION_FORMAT:
        raise ThreadlineError("saved snapshot format is unsupported")
    if document.get("schemaVersion") != SCHEMA_VERSION:
        raise ThreadlineError("saved snapshot schema differs from this Threadline version")
    models = document.get("models")
    if not isinstance(models, list) or not models or len(models) > 4:
        raise ThreadlineError("saved snapshot must contain one to four retained models")
    for model in models:
        if not isinstance(model, dict) or model.get("snapshotId") != _snapshot_id(model):
            raise ThreadlineError("saved snapshot has a mismatched model ID")
    original_root = document.get("root")
    if not isinstance(original_root, str):
        raise ThreadlineError("saved snapshot has no source-root label")
    # Query methods use retained source only. The original directory may have
    # moved or disappeared since this artifact was written.
    store = SnapshotStore(source.parent, retention=len(models))
    store.root = Path(original_root)
    for model in models:
        store.retain(model)
    requested = document.get("currentSnapshotId")
    if requested not in store._models:
        raise ThreadlineError("saved snapshot has no current model")
    store.current_id = requested
    return store


def _store(args: argparse.Namespace) -> SnapshotStore:
    if args.session:
        if args.project or args.source_root or args.exclude:
            raise ThreadlineError("--session cannot be combined with project, --source-root, or --exclude")
        return _read_session(args.session)
    if not args.project:
        raise ThreadlineError("project or --session is required")
    store = SnapshotStore(args.project, source_roots=args.source_root, exclude=args.exclude)
    store.refresh()
    return store


def _selected_model(store: SnapshotStore, requested: str | None) -> dict[str, Any]:
    if requested and requested not in store._models:
        raise ThreadlineError(
            f"snapshot mismatch: selected {requested}, available {', '.join(store._models)}"
        )
    return store.model(requested)


def _change_page(changes: dict[str, Any], category: str, cursor: int, limit: int) -> dict[str, Any]:
    if category == "parseErrors":
        rows = [
            {"side": side, **row}
            for side, errors in changes.get("parseErrors", {}).items()
            for row in errors
        ]
    else:
        rows = changes.get(category, [])
    if not isinstance(rows, list):
        raise ThreadlineError(f"change category is unavailable: {category}")
    counts = {name: len(value) for name, value in changes.items() if name in CHANGE_CATEGORIES and isinstance(value, list)}
    counts["parseErrors"] = sum(len(value) for value in changes.get("parseErrors", {}).values())
    return {
        "base": changes["base"],
        "baseSnapshotId": changes["baseSnapshotId"],
        "workingSnapshotId": changes["workingSnapshotId"],
        "category": category,
        "counts": counts,
        "records": _page(rows, cursor, limit),
        "notice": changes.get("notice", ""),
    }


def _query(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    if not args.session and args.command == "changes" and args.cursor > 0:
        raise ThreadlineError(
            "--session is required for a later change page; "
            "a live Git base can move without changing the working snapshotId"
        )
    if not args.session and getattr(args, "cursor", 0) > 0 and not args.snapshot:
        raise ThreadlineError(
            "--snapshot is required for a later page from a live project; "
            "use the snapshotId from the first page or a saved --session"
        )
    if (not args.session and args.command == 'dataflow'
            and args.model_cursor > 0 and not args.snapshot):
        raise ThreadlineError(
            '--snapshot is required for a later model page from a live project; '
            'use the overview result\'s snapshotId or a saved --session'
        )
    if not args.session and not args.snapshot:
        if args.command == "source" and args.evidence:
            raise ThreadlineError(
                "--snapshot is required to retrieve an evidence ID from a live project; "
                "use its snapshotId or a saved --session"
            )
        if args.command == "source" and args.start is not None and args.start > 1:
            raise ThreadlineError(
                "--snapshot is required to continue source lines from a live project; "
                "use the first page's snapshotId or a saved --session"
            )
        if args.command == "branch":
            raise ThreadlineError(
                "--snapshot is required to follow a branch operation ID in a live project; "
                "use the scope result's snapshotId or a saved --session"
            )
        if args.command == "dataflow" and args.node:
            raise ThreadlineError(
                "--snapshot is required to trace a data-flow node ID in a live project; "
                "use the overview result's snapshotId or a saved --session"
            )
    store = _store(args)
    model = _selected_model(store, args.snapshot)
    snapshot_id = model["snapshotId"]
    page = {"cursor": getattr(args, "cursor", 0), "limit": getattr(args, "limit", 25)}

    if args.command == "summary":
        result = store.summary(
            snapshot_id=snapshot_id, cursor=page["cursor"], limit=page["limit"],
        )
    elif args.command in ("inspect", "symbols"):
        if args.command == "inspect" and args.entrypoint:
            selected = _resolve_query_symbol(model, args.entrypoint, args)
            result = store.get_workflow(selected["id"], snapshot_id=snapshot_id, **page)
        else:
            result = store.find_symbols(args.query, kind=args.kind, snapshot_id=snapshot_id, **page)
    elif args.command == "workflow":
        selected = _resolve_query_symbol(model, args.entrypoint, args)
        result = store.get_workflow(selected["id"], snapshot_id=snapshot_id, **page)
    elif args.command == "method":
        selected = _resolve_query_symbol(model, args.symbol, args)
        result = store.get_method(selected["id"], snapshot_id=snapshot_id, **page)
    elif args.command == "dataflow":
        selected = _resolve_query_symbol(model, args.symbol, args)
        result = store.get_dataflow(selected["id"], snapshot_id=snapshot_id,
                                    node_id=args.node, direction=args.direction,
                                    model_cursor=args.model_cursor, **page)
    elif args.command == "scope":
        selected = _resolve_query_symbol(model, args.symbol, args)
        result = store.get_scope(selected["id"], snapshot_id=snapshot_id, shallow=args.shallow, **page)
    elif args.command == "branch":
        selected = _resolve_query_symbol(model, args.symbol, args)
        result = store.get_branch(selected["id"], args.operation, args.arm, snapshot_id=snapshot_id, **page)
    elif args.command == "source":
        result = store.get_source(
            snapshot_id=snapshot_id, evidence=args.evidence, file=args.file,
            start=args.start, end=args.end,
        )
    elif args.command == "diagnostics":
        result = store.diagnostics(snapshot_id=snapshot_id, category=args.category, **page)
    elif args.command == "changes":
        if args.session:
            if args.change_files:
                raise ThreadlineError("--file cannot be applied after a change snapshot was saved")
            changes = model.get("changes")
            if not changes:
                raise ThreadlineError("saved snapshot has no change review; create it with snapshot --base")
            if args.base and args.base != changes["base"]:
                raise ThreadlineError("selected Git base differs from the saved change snapshot")
        else:
            changes = review_changes(store.root, args.base or "HEAD", args.change_files, store)
            model["changes"] = changes
        result = _change_page(changes, args.category, args.cursor, args.limit)
    else:
        raise ThreadlineError(f"unknown operation: {args.command}")
    if getattr(args, "detail", "full") == "references" and (
        args.command in ("workflow", "dataflow") or args.command == "inspect" and args.entrypoint
    ):
        result = _evidence_references(result)
    return model, result


def main(argv: list[str] | None = None, default_command: str | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if default_command and (not values or values[0] not in COMMANDS):
        values.insert(0, default_command)
    parser = _parser()
    args = parser.parse_args(values)
    try:
        if args.command == "review":
            print(
                "Reading Python source… Large repositories can take up to one minute; "
                "use --source-root to narrow the review.",
                flush=True,
            )
            if args.output:
                from .html_export import write_html

                store = SnapshotStore(args.project, source_roots=args.source_root, exclude=args.exclude)
                store.refresh()
                if args.base:
                    store.current["changes"] = review_changes(
                        store.root, args.base, args.change_files, store,
                    )
                output = write_html(store, args.output)
                print(f"Threadline HTML review: {output}\nOpen {output.as_uri()}", flush=True)
                if not args.no_open:
                    webbrowser.open(output.as_uri())
                return 0
            server = make_server(
                args.project, port=args.port, base=args.base,
                source_roots=args.source_root, exclude=args.exclude,
                change_files=args.change_files,
            )
            url = f"http://127.0.0.1:{server.server_address[1]}/"
            print(f"Threadline is reviewing {Path(args.project).resolve()}\nOpen {url}", flush=True)
            if not args.no_open:
                webbrowser.open(url)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
            return 0

        if args.command == "snapshot":
            store = SnapshotStore(args.project, source_roots=args.source_root, exclude=args.exclude)
            store.refresh()
            if args.base:
                store.current["changes"] = review_changes(
                    store.root, args.base, args.change_files, store,
                )
            _write_session(store, args.output)
            model = store.current
            result = {
                "file": str(Path(args.output).expanduser().resolve()),
                "retainedSnapshots": list(store._models),
                "hasChanges": "changes" in model,
            }
            _print_json(_envelope("snapshot", model, result), compact=args.compact)
            return 0

        model, result = _query(args)
        _print_json(
            _envelope(args.command, model, result, detail=getattr(args, "detail", "full")),
            compact=args.compact,
        )
        return 3 if args.strict_complete and not _analysis(model)["complete"] else 0
    except (ThreadlineError, ValueError, KeyError, TypeError) as exc:
        _error(args.command, "query_error", str(exc), compact=getattr(args, "compact", False))
        return 2
    except OSError as exc:
        _error(args.command, "io_error", str(exc), compact=getattr(args, "compact", False))
        return 1
