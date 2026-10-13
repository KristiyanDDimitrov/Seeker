"""Source sweeps that keep every long task stoppable on quit.

A quit waits for the thread pool's running tasks (HISTORY §125), so a
service call that can outlast the 5 s bound takes `stop:
threading.Event | None`, and `ui/` passes it `PageContext.quitting`
(HISTORY §226). These sweeps read `src/seeker/` with `ast`: a service
method is any function defined outside `ui/`, and it is stoppable when
it takes a `stop` parameter.
"""
import ast
import builtins
import threading
from collections.abc import Iterator
from pathlib import Path

import seeker

SRC_DIR = Path(seeker.__file__).parent
UI_DIR = SRC_DIR / "ui"

# A stoppable call whose stop is an event of its caller's own, set on
# quit, rather than `quitting`: (file, method) -> why.
OWN_STOP = {
    ("sweep_scheduler.py", "run_sweep"):
        "SweepScheduler's own `_stop`, set by its stop() on quit; it "
        "also keeps the next sweep from starting.",
}


def _service_functions() -> dict[str, bool]:
    """Every function defined outside `ui/`, by name: whether any
    function of that name takes `stop`."""
    takes_stop: dict[str, bool] = {}
    for path in SRC_DIR.rglob("*.py"):
        if path.is_relative_to(UI_DIR):
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                arguments = node.args.args + node.args.kwonlyargs
                takes_stop[node.name] = takes_stop.get(node.name, False) or any(
                    argument.arg == "stop" for argument in arguments
                )
    # A name that is also a builtin type's method (`get`, `wait`,
    # `append`) is called on dicts, events and lists all over ui/; a
    # service method of that name could not be told apart by name.
    # None of them takes `stop` (asserted below), so leaving them out
    # hides no stoppable call.
    common = {
        name
        for kind in (dict, list, set, str, threading.Event, object)
        for name in dir(kind)
    } | set(dir(builtins))
    shadowed = {name for name in takes_stop if name in common}
    assert not any(takes_stop[name] for name in shadowed), shadowed
    return {
        name: stop for name, stop in takes_stop.items()
        if name not in shadowed
    }


SERVICE_FUNCTIONS = _service_functions()
STOPPABLE = {name for name, stop in SERVICE_FUNCTIONS.items() if stop}


def _ui_modules() -> Iterator[tuple[Path, ast.Module]]:
    for path in sorted(UI_DIR.rglob("*.py")):
        yield path, ast.parse(path.read_text(), filename=str(path))


def test_every_stoppable_service_call_in_ui_passes_quitting():
    # A call that leaves `stop` out runs to its end however long a quit
    # waits for it. Every call in ui/ is checked, not only those inside
    # a worker's lambda: a helper the lambda calls is where most of
    # them sit (Duplicates' per-folder loops).
    checked = 0
    violations = []
    for path, tree in _ui_modules():
        called = set()
        for node in ast.walk(tree):
            if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in STOPPABLE
                    and not _is_page_method(node.func)
            ):
                continue
            called.add(id(node.func))
            checked += 1
            if (path.name, node.func.attr) in OWN_STOP:
                continue
            stop = [k.value for k in node.keywords if k.arg == "stop"]
            if not stop or "quitting" not in ast.unparse(stop[0]):
                violations.append(f"{path.name}:{node.lineno}: {node.func.attr}")
        # Handed over uncalled (`run_worker(pool, service.scan_all)`),
        # a stoppable method can never be given its stop.
        violations += [
            f"{path.name}:{node.lineno}: {node.attr} passed uncalled"
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr in STOPPABLE
            and id(node) not in called
            and isinstance(node.ctx, ast.Load)
            and "application" in _receiver_names(node)
        ]

    # The sweep found the calls it exists for: a renamed parameter
    # would otherwise pass it vacuously.
    assert checked > 15
    assert violations == [], (
        "a stoppable service call that a quit cannot stop; pass "
        "stop=self._context.quitting:\n" + "\n".join(violations)
    )


def _receiver_names(node: ast.Attribute) -> list[str]:
    """The names along `node`'s receiver: `self._context.application.
    library_service.scan_all` gives `library_service`, `application`,
    `_context`, `self`."""
    names = []
    receiver = node.value
    while isinstance(receiver, ast.Attribute):
        names.append(receiver.attr)
        receiver = receiver.value
    if isinstance(receiver, ast.Name):
        names.append(receiver.id)
    return names


def _is_page_method(node: ast.Attribute) -> bool:
    # ui/ reaches a service only through Application (CLAUDE.md →
    # Architecture), so a `self.` chain with no `application` link is a
    # widget's own method sharing a service method's name
    # (`self._tagging_panel.tag_playlist(feedback)`). A local holding a
    # service (`service = …duplicate_service`) is still checked.
    names = _receiver_names(node)
    return names[-1:] == ["self"] and "application" not in names


def _worker_tasks(tree: ast.Module) -> Iterator[tuple[ast.Call, ast.expr]]:
    """Each call that starts a pool task, with the task it starts:
    `run_worker(pool, fn)` (or a host's `run_worker(fn)`, its pool
    bound), `run_busy_worker(key, button, fn)` and a `RunningRows`'
    `run(pool, key, buttons, fn)`."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else (
            func.id if isinstance(func, ast.Name) else None
        )
        if name == "run_worker":
            pool_first = node.args and "pool" in ast.unparse(node.args[0])
            index = 1 if pool_first else 0
        elif name in ("run_busy_worker", "_run_busy_worker"):
            index = 2
        elif (
                name == "run"
                and isinstance(func, ast.Attribute)
                and ast.unparse(func.value).startswith("self._running")
        ):
            index = 3
        else:
            continue
        if len(node.args) > index:
            yield node, node.args[index]


def _local_definitions(
        tree: ast.Module,
) -> dict[str, list[ast.FunctionDef]]:
    definitions: dict[str, list[ast.FunctionDef]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            definitions.setdefault(node.name, []).append(node)
    return definitions


def _service_calls(
        task: ast.expr, definitions: dict[str, list[ast.FunctionDef]],
) -> set[str]:
    """The service functions a task calls, or is (a bound method handed
    over uncalled), followed through the module's own functions it
    calls (a nested `def fetch()`, a page's `self._gather_snapshot`).
    A property read on the way (`application.library_service`) is not
    a call, and does no work a quit waits for."""
    found: set[str] = set()
    seen: set[int] = set()

    def reach(callee: ast.expr, pending: list[ast.AST]) -> None:
        if isinstance(callee, ast.Attribute) and not _is_page_method(callee):
            if callee.attr in SERVICE_FUNCTIONS:
                found.add(callee.attr)
            return
        name = (
            callee.attr if isinstance(callee, ast.Attribute)
            else callee.id if isinstance(callee, ast.Name)
            else None
        )
        if name is None:
            return
        local = definitions.get(name, [])
        if not local and name in SERVICE_FUNCTIONS:
            # A service function imported and called bare.
            found.add(name)
        for definition in local:
            if id(definition) not in seen:
                seen.add(id(definition))
                pending.append(definition)

    pending: list[ast.AST] = []
    if isinstance(task, ast.Lambda):
        pending.append(task.body)
    else:
        reach(task, pending)
    while pending:
        for node in ast.walk(pending.pop()):
            if isinstance(node, ast.Call):
                reach(node.func, pending)
    return found


# Measured on a copy of the real database (6,921 files, 215 playlists,
# 56 cached tracks), HISTORY §233: the slowest read took 78 ms.
_DB_READ = "A database read: at most 78 ms on the real DB's copy."
_DB_WRITE = "A short database or config write: under 1 ms on the copy."
# slskd answers on loopback; down, it refuses the connection at once.
_SLSKD = (
    "slskd REST calls, each bounded by its 10 s timeout; only a hung "
    "slskd holds a quit past 5 s (UNVERIFIED that one ever hangs)."
)

# Every service function a pool task in ui/ calls that takes no stop,
# with why a quit need not wait on it (working agreement 5: a call
# absent from here and from the stoppable set fails the sweep).
TAKES_NO_STOP = {
    "add_location_from_path": _DB_WRITE + " Its nesting check stats "
    "each registered location's root.",
    "apply_upgrade_decision": "One upgrade's replace: one file moved "
    "(a cross-volume copy of one track; UNVERIFIED how long on USB).",
    "cancel_download": _SLSKD,
    "check_for_update": "One GitHub request, bounded by its 10 s "
    "timeout (update_check.REQUEST_TIMEOUT_SECONDS).",
    "check_slskd_health": _SLSKD,
    "check_slskd_web_login": _SLSKD,
    "clear_finished_downloads": _DB_WRITE,
    "confirm_match": _DB_WRITE,
    "confirm_review_candidate": _SLSKD + " One enqueue.",
    "connect_spotify": "Its login wait takes `cancel`, which a quit "
    "sets through stop_for_quit() (HISTORY §231).",
    "count_files_for_scopes": _DB_READ,
    "delete_leftover_files": "Unlinks on slskd's folder, on the "
    "internal disk: 1,000 took 29 ms. " + _SLSKD + " One re-list.",
    "delete_local_files": "One duplicate group's files: each row "
    "deleted, then its file (a handful of unlinks).",
    "describe_error": "Formats text; no I/O.",
    "detect_docker_state": "`docker` subprocesses, bounded at 5-10 s "
    "each (docker_setup's timeouts).",
    "download_manual": _SLSKD + " One enqueue.",
    "find_nested_locations": _DB_READ,
    "get_active_downloads": _DB_READ,
    "get_cleanup_totals": _DB_READ,
    "get_needs_review_matches": _DB_READ,
    "get_pending_upgrade_reviews": _DB_READ,
    "get_playlist_summaries": _DB_READ,
    "get_playlist_track_status": _DB_READ,
    "get_reconciliation": _SLSKD,
    "get_recent_events": _DB_READ,
    "get_resolved_destination": _DB_READ,
    "get_review_candidates": _DB_READ,
    "get_status": _SLSKD,
    "get_uploads": _SLSKD,
    "has_scanned_library": _DB_READ,
    "is_self_managed": "One `docker inspect`, bounded by its timeout.",
    "list_leftover_files": _SLSKD + " Then a walk of slskd's two "
    "folders on the internal disk.",
    "list_locations": _DB_READ,
    "list_playlists": _DB_READ,
    "match_all": "0.1 s at the real DB's scale (HISTORY §233).",
    "merge_location": "0.17 s at the real DB's scale, 3,454 files "
    "merged (HISTORY §233).",
    "persist_default_destination": _DB_WRITE,
    "plan_renames": _DB_READ,
    "poll_downloads": _SLSKD + " A transport error aborts the poll "
    "(HISTORY §151).",
    "preview_merge_location": "0.09 s at the real DB's scale "
    "(HISTORY §233).",
    "preview_remove_location": _DB_READ,
    "reject_match": _DB_WRITE,
    "reject_review_candidate": _DB_WRITE + " " + _SLSKD + " A backup "
    "it activates is one enqueue.",
    "remove_location": "0.02 s at the real DB's scale, 3,458 files "
    "forgotten (HISTORY §233).",
    "rename_location": _DB_WRITE,
    "resolve_folder_scopes": _DB_READ,
    "restart_slskd": "A slskd bring-up: waited for by design, never "
    "killed mid-recreate (HISTORY §232).",
    "set_destination": _DB_WRITE,
    "slskd_start_defaults": "Reads the saved settings and checks a "
    "few paths.",
    "start_slskd": "A slskd bring-up: waited for by design, never "
    "killed mid-recreate (HISTORY §232).",
    "summarize_scopes": _DB_READ,
}


def test_every_worker_task_is_stoppable_or_listed_with_a_reason():
    # A new long call in a pool task must either take `stop` (the
    # sweep above then checks it gets `quitting`) or be listed here
    # with a measured reason. A task that calls only ui/ code or no
    # service at all (a forwarded `fn`, `row_actions.run`'s own
    # `run_worker`) reaches nothing here: its callers are swept where
    # they hand over their task.
    reached: set[str] = set()
    tasks = 0
    for _path, tree in _ui_modules():
        definitions = _local_definitions(tree)
        for _call, task in _worker_tasks(tree):
            tasks += 1
            reached |= _service_calls(task, definitions)

    assert tasks > 60
    unlisted = sorted(reached - STOPPABLE - TAKES_NO_STOP.keys())
    assert unlisted == [], (
        "a pool task calls a service that takes no stop; give it a "
        "stop, or list it in TAKES_NO_STOP with a measured reason: "
        + ", ".join(unlisted)
    )
    stale = sorted(TAKES_NO_STOP.keys() - reached)
    assert stale == [], "listed but no task calls it: " + ", ".join(stale)
    assert not TAKES_NO_STOP.keys() & STOPPABLE
