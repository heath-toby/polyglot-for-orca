#!/usr/bin/env python3
"""Setting BRLTTY's text table must never make Orca wait.

``brlapi.setParameter`` is a synchronous round trip, and with BRLTTY running
but no display attached it does not come back promptly. From Toby's own log,
with Orca's main thread inside the call:

    15:24:08 _set_brltty_text_table: en -> ru
    15:24:57 _set_brltty_text_table: ERROR Unexpected end of file

Forty-nine seconds of a wholly stopped screen reader -- no speech, no braille,
no keys -- against under a second when a display is attached (20:02:16 ->
20:02:16). An earlier line has no closing entry at all, so that call never
returned. The state is ordinary rather than exotic now: ``brltty.path`` starts
the service when the Bluetooth display appears and leaves it running once the
display goes away.

These rows stand a fake ``brlapi`` in front of the real one, with a
``setParameter`` that sleeps, so the hang is reproducible **without BRLTTY and
without a display**. What they assert is the shape of the fix: the caller
returns in milliseconds and the waiting happens somewhere that cannot stop a
screen reader.

Usage: python3 tests-brltty-worker.py
"""

from __future__ import annotations

import os
import sys
import threading
import time
import types

sys.path.insert(0, os.path.expanduser("~/.local/share/orca/extensions"))

rows, fails = [], 0


def check(name, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    # Record what was compared, not a reference to it: a live list appended to
    # later would print its final state beside a verdict reached earlier.
    rows.append((name, repr(want), repr(got), "ok" if ok else "FAIL"))


HANG_SECONDS = 1.5


class FakeConnection:
    """Records what it was asked for, slowly, and can refuse to connect."""

    calls: list[str] = []
    call_threads: list[str] = []
    closed = 0
    delay = HANG_SECONDS
    connect_error: Exception | None = None
    set_error: Exception | None = None

    def __init__(self):
        if FakeConnection.connect_error is not None:
            raise FakeConnection.connect_error

    def setParameter(self, _param, _subparam, _flags, value):  # noqa: N802
        time.sleep(FakeConnection.delay)
        if FakeConnection.set_error is not None:
            raise FakeConnection.set_error
        FakeConnection.calls.append(value)
        FakeConnection.call_threads.append(threading.current_thread().name)

    def closeConnection(self):  # noqa: N802
        FakeConnection.closed += 1


fake = types.ModuleType("brlapi")
fake.Connection = FakeConnection
fake.PARAM_COMPUTER_BRAILLE_TABLE = 1
fake.PARAMF_GLOBAL = 2
sys.modules["brlapi"] = fake

from polyglot import speech_interceptor as si  # noqa: E402

si._debug = lambda *_args, **_kwargs: None

# Most rows below are about what happens when there *is* a display, so say so.
# The display-absent rows set this themselves.
_display = [True]
si._braille_display_present = lambda: _display[0]


def reset(delay=HANG_SECONDS, connect_error=None, set_error=None):
    """A fresh worker and a fresh fake, between rows."""
    if si._brltty_queue is not None:
        si._brltty_queue.put(si._BRLTTY_STOP)
    if si._brltty_thread is not None:
        si._brltty_thread.join(timeout=HANG_SECONDS * 3)
    si._brltty_queue = None
    si._brltty_thread = None
    si._current_brltty_text_table = None
    FakeConnection.calls = []
    FakeConnection.call_threads = []
    FakeConnection.closed = 0
    FakeConnection.delay = delay
    FakeConnection.connect_error = connect_error
    FakeConnection.set_error = set_error
    _display[0] = True
    si._brltty_display_seen = True


def settle(seconds=HANG_SECONDS * 3):
    """Wait for the worker, which is the thing the caller no longer does."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not FakeConnection.calls:
        time.sleep(0.02)
    time.sleep(0.1)


# --- the whole point -----------------------------------------------------
reset()
started = time.monotonic()
si._set_brltty_text_table("ru")
elapsed = time.monotonic() - started
check("the caller returns in milliseconds, not seconds", elapsed < 0.1, True)
check("...and the call that blocks for over a second has not run yet",
      FakeConnection.calls, [])

settle()
check("the worker does get there", FakeConnection.calls, ["ru"])
check("...on its own thread, not the caller's",
      FakeConnection.call_threads, ["polyglot-brltty"])
check("...which is a daemon, so a stuck call cannot hold up Orca's exit",
      si._brltty_thread.daemon, True)

# --- the same table twice is one request ---------------------------------
reset(delay=0.0)
si._set_brltty_text_table("de")
si._set_brltty_text_table("de")
settle(1.0)
check("asking twice for the same table asks BRLTTY once",
      FakeConnection.calls, ["de"])

# --- a burst collapses to its last member --------------------------------
# Three language changes while one call is in flight should not become three
# round trips to arrive where the third one asked for.
reset()
si._set_brltty_text_table("de")
si._set_brltty_text_table("ru")
si._set_brltty_text_table("en")
settle()
check("a burst of changes sets only the last one", FakeConnection.calls, ["en"])

# --- the worker must not write what the main thread reads ---------------
# `_current_brltty_text_table` is read either side of a switch by
# `_apply_braille_language`, to decide whether anything moved, and compared
# against a snapshot by the flash restore. The first version of this fix had
# the worker clear it on failure, which changes those answers underneath the
# thread making them. The worker keeps its own record now.
reset(delay=0.0, set_error=RuntimeError("Unexpected end of file"))
si._set_brltty_text_table("ru")
time.sleep(0.4)
check("a failed set leaves the main thread's record alone",
      si._current_brltty_text_table, "ru")
check("...and the connection is dropped so the next try reconnects",
      FakeConnection.closed >= 1, True)

# --- a failure is retried, not latched -----------------------------------
# The old code set a _brltty_failed flag on the first failure and never tried
# again, so a session begun while BRLTTY was down never set a table again --
# including once a display was connected, which with brltty.path is the
# normal order of events.
FakeConnection.set_error = None
FakeConnection.calls = []
si._set_brltty_text_table("de")
settle(1.0)
check("a later table is attempted after an earlier one failed",
      FakeConnection.calls, ["de"])

# --- BRLTTY not running at all -------------------------------------------
reset(delay=0.0, connect_error=RuntimeError("cannot connect"))
si._set_brltty_text_table("de")
time.sleep(0.4)
check("a refused connection does not raise into the caller",
      FakeConnection.calls, [])

# A refused connection does start a backoff, so that a session begun with
# BRLTTY down does not try again on every single language change.
FakeConnection.connect_error = None
si._set_brltty_text_table("ru")
time.sleep(0.4)
check("...and the next change is held off rather than hammering BRLTTY",
      FakeConnection.calls, [])

# But only for as long as the backoff, not for the session.
_saved_backoff = si._BRLTTY_RETRY_SECONDS
si._BRLTTY_RETRY_SECONDS = 0.0
si._set_brltty_text_table("de")
settle(1.0)
check("...and once the backoff is up it connects again",
      FakeConnection.calls, ["de"])
si._BRLTTY_RETRY_SECONDS = _saved_backoff

# --- no brlapi module at all ---------------------------------------------
saved = sys.modules.pop("brlapi")
reset(delay=0.0)
si._set_brltty_text_table("en")
time.sleep(0.4)
check("a machine with no brlapi is silently fine", FakeConnection.calls, [])
sys.modules["brlapi"] = saved

# --- no display, no request ----------------------------------------------
# A computer braille table is a property of something being displayed. With no
# display there is nothing to set it for, and asking is the very call that took
# 49 seconds. Orca already knows, in braille.has_braille_device(), which is a
# local read of its own brlapi_ready -- so this costs nothing and polls
# nothing.
reset(delay=0.0)
_display[0] = False
si._brltty_display_seen = False
si._set_brltty_text_table("ru")
time.sleep(0.3)
check("with no display, BRLTTY is not asked at all", FakeConnection.calls, [])
check("...but the language's table is remembered",
      si._current_brltty_text_table, "ru")

# --- the display coming back is caught without polling -------------------
# No timer and no subscription: the next language change notices that a
# display is present when it was not, and re-applies the table that was
# skipped. In practice that is within a keystroke, because Polyglot's hooks
# run on caret moves and focus changes.
_display[0] = True
si._set_brltty_text_table("ru")
settle(1.0)
check("a display coming back re-applies the table that was skipped",
      FakeConnection.calls, ["ru"])

# And it must not re-apply for ever after -- once is the point.
FakeConnection.calls = []
si._set_brltty_text_table("ru")
time.sleep(0.3)
check("...once, not on every change after that", FakeConnection.calls, [])

# --- a missing Orca API must not silence us ------------------------------
# If has_braille_device ever stops existing, the right failure is to carry on
# as before -- the worker makes that safe -- not to go quietly silent.
reset(delay=0.0)
_saved_present = si._braille_display_present
si._braille_display_present = _saved_present
_probe_result = None
try:
    from orca import braille as _braille
    _saved_getter = getattr(_braille, "has_braille_device", None)
    del _braille.has_braille_device
    _probe_result = si._braille_display_present()
finally:
    if _saved_getter is not None:
        _braille.has_braille_device = _saved_getter
check("a missing has_braille_device is treated as 'display present'",
      _probe_result, True)
si._braille_display_present = lambda: _display[0]

# --- the stop honours the table queued before it -------------------------
# uninstall() asks for the default tables and then stops the worker. The
# restore has to get through, or disabling Polyglot would leave the display on
# whatever language happened to be live.
reset(delay=0.0)
si._set_brltty_text_table("de")
si._brltty_queue.put(si._BRLTTY_STOP)
si._brltty_thread.join(timeout=2.0)
check("a table queued before the stop is still applied",
      FakeConnection.calls, ["de"])
check("...and then the worker exits", si._brltty_thread.is_alive(), False)
check("...closing the connection on its way out", FakeConnection.closed >= 1, True)

# --- the request survives a dead worker ----------------------------------
reset(delay=0.0)
si._set_brltty_text_table("en")
settle(1.0)
si._brltty_queue.put(si._BRLTTY_STOP)
si._brltty_thread.join(timeout=2.0)
FakeConnection.calls = []
si._set_brltty_text_table("ru")
settle(1.0)
check("a request after the worker exited starts a new one",
      FakeConnection.calls, ["ru"])

reset(delay=0.0)
if si._brltty_queue is not None:
    si._brltty_queue.put(si._BRLTTY_STOP)

width = max(len(r[0]) for r in rows)
print()
for name, want, got, status in rows:
    print(f"  {status:4s} {name:<{width}}  want={want}  got={got}")
print(f"\n{len(rows) - fails}/{len(rows)} rows green")
sys.exit(1 if fails else 0)
