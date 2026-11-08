from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_native_application_ownership_and_wrong_thread_guards() -> None:
    root = Path(__file__).resolve().parents[1]
    code = """
import threading
import weakref
from pathlib import Path
from pytaurix import BindingError, Commands, Emitter, EventTarget, Listener, Manager, builder_factory, context_factory
from pytaurix.ffi import Emitter as FfiEmitter

class Shared:
    pass

class Callback:
    def __call__(self, event):
        pass

context = context_factory(Path("examples/minimal"))
app = builder_factory().build(context=context, invoke_handler=Commands().generate_handler())
handle = app.handle()
assert Manager.get_webview_window(handle, "main") is None
shared = Shared()
callback = Callback()
shared_ref, callback_ref = weakref.ref(shared), weakref.ref(callback)
assert Manager.manage(handle, shared)
assert not Manager.manage(handle, Shared())
assert Manager.state(handle, Shared) is shared
try:
    Manager.manage(handle, None)
except BindingError as error:
    assert "invalid_state" in str(error)
else:
    raise AssertionError("None registered as managed state")
Listener.listen(handle, "cleanup-test", callback)

class Task:
    def __call__(self):
        raise AssertionError("Task ran after native application was dropped")

task = Task()
task_ref = weakref.ref(task)
submitted = []
def submit():
    submitted.append(handle.run_on_main_thread(task))
queue_worker = threading.Thread(target=submit)
queue_worker.start()
queue_worker.join(timeout=3)
assert not queue_worker.is_alive() and submitted == [None]
del task
assert task_ref() is not None

class ReentrantOnce:
    def __call__(self, event):
        calls.append(event.payload())
        Emitter.emit(handle, "recursive-once", 2)

calls = []
once = ReentrantOnce()
once_ref = weakref.ref(once)
Listener.once_any(handle, "recursive-once", once)
del once
Emitter.emit(handle, "recursive-once", 1)
Emitter.emit(handle, "recursive-once", 3)
assert calls == ["1"] and once_ref() is None
raw = ' { "large": 123456789012345678901234567890, "unicode": "界" } '
received = []
Listener.once(handle, "raw-preserved", lambda event: received.append(event.payload()))
FfiEmitter.emit_str_to(handle, EventTarget.App(), "raw-preserved", raw)
assert received == [raw]
del shared, callback
errors = []
def run():
    for operation in (app.run_return, app.handle):
        try:
            operation()
        except BindingError as error:
            errors.append(str(error))
worker = threading.Thread(target=run)
worker.start()
worker.join(timeout=3)
assert not worker.is_alive()
assert len(errors) == 2 and all("wrong_thread" in error for error in errors)
try:
    builder_factory().build(context=context, invoke_handler=Commands().generate_handler())
except BindingError as error:
    assert "runtime_consumed" in str(error)
else:
    raise AssertionError("Second native build succeeded")
del app
assert shared_ref() is None and callback_ref() is None and task_ref() is None
rejected = Task()
rejected_ref = weakref.ref(rejected)
try:
    handle.run_on_main_thread(rejected)
except BindingError as error:
    assert "app_closed" in str(error)
else:
    raise AssertionError("Closed app accepted task")
del rejected
assert rejected_ref() is None
try:
    handle.exit(0)
except BindingError as error:
    assert "app_closed" in str(error)
else:
    raise AssertionError("Dropped app handle remained active")
print("OWNERSHIP_AND_THREAD_GUARDS_OK")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        env=dict(os.environ, PYTHONUTF8="1"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OWNERSHIP_AND_THREAD_GUARDS_OK" in result.stdout
