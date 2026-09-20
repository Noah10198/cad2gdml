"""occ_quiet.py -- keep OCC's own console banner out of the application's output.

Building a viewer makes OCC print on the standard output with printf, in two
halves: Viewer3d() announces the driver, camera and structure manager, and
Create() adds the window plus the OpenGL capabilities block. Neither goes through
Qt, through logging, or through OCC's messenger, so the only thing left to move
is the file descriptor itself.

The capabilities block is worth reading once, for the main viewport, as a record
of the driver the session is running on. It is asked for separately through
GlInfo(), so it is printed while the descriptor is back in place, and not
captured: a redirected standard output is block buffered, and a block written to
a file only reaches the console when the process flushes it, well after startup.
"""

import contextlib
import os
import sys

from OCC.Display import OCCViewer


@contextlib.contextmanager
def occ_quiet():
    """Send the process' standard output to the null device for the duration.

    The application logs through its own logger, and OCC reports failures on
    stderr as well, so nothing that has to be read is lost with it.
    """
    sys.stdout.flush()
    try:
        saved = os.dup(1)
    except OSError:
        # No console to mute (a windowed build, or output already redirected
        # somewhere that cannot be duplicated).
        yield
        return
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, 1)
        yield
    finally:
        sys.stdout.flush()
        os.dup2(saved, 1)
        os.close(saved)
        os.close(devnull)


def new_viewer(window_handle: int = None, parent=None):
    """An OCC Viewer3d, bound to a Qt window when one is given.

    Creating a viewer and attaching it are the two calls that print the banner,
    so they are the two that run muted.
    """
    with occ_quiet():
        display = OCCViewer.Viewer3d()
        if window_handle is not None:
            display.Create(window_handle=window_handle, parent=parent)
    return display
