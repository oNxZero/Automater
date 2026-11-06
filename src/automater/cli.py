"""Run saved workflows without an editor or a resident service."""

import asyncio
import json
import os
import signal
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from functools import partial
from pathlib import Path

from . import cli_control
from .engine import DryRun, PlaybackOptions, Replay
from .storage import load


@contextmanager
def stop_signals(stop):
    received = [0]

    def handle(signum, frame):
        received[0] = signum
        stop()

    previous = {}
    try:
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            previous[signum] = signal.signal(signum, handle)
        yield received
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def close_pointer(connection):
    if connection is not None:
        connection.close()
        if connection.thread is not None:
            connection.thread.join(3)


def authorize_pointer(cancelled, pump, revoked=lambda: None):
    from .portal_session import PortalSession

    connection = PortalSession(on_revoked=revoked)
    try:
        connection.connect_pointer()
        while not connection.authorization_done.is_set() and not cancelled.is_set():
            pump()
            if not connection.thread.is_alive() and not connection.authorization_done.is_set():
                raise RuntimeError("Pointer connection ended before approval")
        if cancelled.is_set():
            close_pointer(connection)
            return None
        if not connection.active:
            raise RuntimeError(connection.error or "Wayland pointer permission was not granted")
        return connection
    except BaseException:
        close_pointer(connection)
        raise


def run_workflow(args):
    path = Path(args.workflow).expanduser().resolve()
    script = load(path)
    if args.no_start_position:
        script = replace(script, start=None)
    options = PlaybackOptions(
        speed=args.speed,
        repeats=args.repeat,
        countdown=args.countdown,
        loop_gap=args.loop_gap,
    )
    if not any(step.runnable for step in script.steps):
        raise ValueError("The workflow has no enabled actions")
    if not args.test and os.geteuid() == 0:
        raise ValueError("Run Automater as your regular desktop user, without sudo")
    if script.start and script.start["space"] != "desktop" and not args.test:
        raise ValueError(
            "This workflow has window-relative starting coordinates. "
            "Use --no-start-position for desktop playback."
        )
    for warning in script.warnings():
        print(f"Warning: {warning}", file=sys.stderr)

    cancelled = threading.Event()
    portal_error = []
    connection = None
    replay = None

    def stop():
        cancelled.set()
        if replay is not None:
            replay.stop()

    def revoked():
        portal_error.append("Wayland pointer permission ended; playback stopped")
        stop()

    def status():
        timeline = replay.timeline if replay is not None else None
        return {
            "running": True,
            "pid": os.getpid(),
            "workflow": str(path),
            "test_mode": args.test,
            "stopping": cancelled.is_set(),
            "phase": timeline["phase"] if timeline else "pointer_permission",
            "loop": timeline["loop"] if timeline else 0,
            "completed_events": timeline["completed_events"] if timeline else 0,
        }

    try:
        with stop_signals(stop) as received, cli_control.listen() as server:

            def pump():
                cli_control.serve(server, status, stop)

            factory = DryRun
            if not args.test:
                from .linux_input import UInputBackend

                factory = UInputBackend
                if script.start:
                    from .compatibility import session_type
                    from .pointer import capability

                    if session_type() == "wayland" and not capability()[0]:
                        if not args.quiet:
                            print(
                                "Connecting Wayland pointer control; approve the desktop dialog if asked."
                            )
                        connection = authorize_pointer(cancelled, pump, revoked)
                        if portal_error:
                            raise RuntimeError(portal_error[0])
                        if cancelled.is_set():
                            return 128 + (received[0] or signal.SIGINT)
                        from .portal_session import PortalPointer

                        factory = partial(
                            UInputBackend, pointer_factory=lambda: PortalPointer(connection)
                        )
            replay = Replay(factory)
            if cancelled.is_set():
                return 128 + (received[0] or signal.SIGINT)
            if not args.quiet:
                print(
                    f"{'Testing' if args.test else 'Running'} {path.name}. Use automater stop or Ctrl+C to stop."
                )
            replay.start(script, options)
            if cancelled.is_set():
                replay.stop()
            try:
                while replay.running:
                    pump()
            finally:
                replay.stop()
                while not replay.join(0.1):
                    pass
            timeline = replay.timeline
            if portal_error or timeline["error"]:
                raise RuntimeError(portal_error[0] if portal_error else timeline["error"])
            if cancelled.is_set() or timeline["outcome"] == "stopped":
                if not args.quiet:
                    print("Stopped; held inputs released.")
                return 128 + (received[0] or signal.SIGINT)
            if not args.quiet:
                print("Finished.")
            return 0
    finally:
        close_pointer(connection)


def stop_workflow():
    current = cli_control.request("stop")
    if current is None:
        print("No CLI workflow is running.")
        return 0
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        status = cli_control.request("status")
        if status is None or status["pid"] != current["pid"]:
            print("Stopped; held inputs released.")
            return 0
        time.sleep(0.05)
    raise RuntimeError("Stop requested; input cleanup is still in progress")


def pointer_command(action):
    if action == "forget":
        from .portal_tokens import PortalTokens

        asyncio.run(PortalTokens().forget())
        print("Forgot the saved Wayland pointer approval. Existing sessions are unchanged.")
        return 0
    cancelled = threading.Event()
    connection = None
    try:
        with stop_signals(cancelled.set) as received:
            print(
                "Approve pointer control and select physical monitors in the desktop dialog if asked."
            )
            connection = authorize_pointer(cancelled, lambda: time.sleep(0.05))
            if cancelled.is_set():
                return 128 + (received[0] or signal.SIGINT)
            print("Pointer access granted. Approval will be reused if your desktop supports it.")
            return 0
    finally:
        close_pointer(connection)


def dispatch(args):
    try:
        if args.command == "run":
            return run_workflow(args)
        if args.command == "stop":
            return stop_workflow()
        if args.command == "pointer":
            return pointer_command(args.action)
        status = cli_control.request("status")
        if args.json:
            print(json.dumps(status or {"running": False}))
        elif status:
            print(
                f"{status['workflow']} · {status['phase']} · loop {status['loop']} · PID {status['pid']}"
            )
        else:
            print("No CLI workflow is running.")
        return 0
    except cli_control.AlreadyRunning as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Automater: {exc}", file=sys.stderr)
        return 1
