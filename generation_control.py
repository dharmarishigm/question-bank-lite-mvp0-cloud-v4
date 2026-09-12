"""Request-local cooperative cancellation, including interactive batch workers."""
from contextvars import ContextVar

pause_check = ContextVar('generation_pause_check', default=None)


def is_paused():
    check = pause_check.get()
    return bool(check and check())
