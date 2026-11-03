"""The notice the core gives when a marked file opens (spec section 8),
shown on sys.stderr, so that it shows in Jupyter, where C's stderr does
not; or given to the caller's function; or not shown."""

from __future__ import annotations

import sys
import traceback
from typing import Any, Callable, Union

from . import _lib
from ._lib import GamutError

_show: Union[bool, Callable[[str, str], Any]] = True


def _deliver(path: bytes, text: bytes, _context: Any) -> None:
    # The core's text is valid UTF-8; nothing raised here may reach it.
    try:
        if _show is True:
            print(text.decode("utf-8", "replace"), file=sys.stderr)
        elif _show is not False:
            _show(path.decode("utf-8", "replace"), text.decode("utf-8", "replace"))
    except Exception:
        traceback.print_exc()


_SINK = _lib.NOTICE_FN(_deliver)   # kept here, so the core's pointer stays valid


def set_marking_notice(show: Union[bool, Callable[[str, str], Any]] = True) -> None:
    """Where the notice on opening a marked file goes: True (the default)
    prints it on sys.stderr, False turns it off, and a function of (path,
    text) receives it. It comes once per file per process; setting it again
    shows every file anew. A program that turns it off takes on any duty to
    show the marking: the file carries it whatever reads it."""
    global _show
    if not isinstance(show, bool) and not callable(show):
        raise GamutError("", f"show is True, False or a function of (path, text), not {show!r}")
    _show = show
    _lib._lib.gamut_set_marking_notice(_SINK, None)


set_marking_notice(True)
