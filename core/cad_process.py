"""
Out-of-process CAD reading for files that are too big to read inline.

STEPControl_Reader.TransferRoots() converts a whole file in a single OCC call
and the pythonocc binding holds the GIL for its entire duration: measured
27.7 s on a 30 MB STEP, during which a QThread worker handed the Qt main
thread the GIL once (1 heartbeat of an expected 57).  Nothing in the importing
process can repaint while that call runs -- not even a fake progress bar.

A child process has its own interpreter and its own GIL, so the UI keeps
running, the progress box can advance and Cancel can actually kill the work.
This is the same conclusion as mesh/assembly_analysis.py.

The child hands the geometry back flattened as
(name, node_type, shape, parent_index) records: GDataNode cannot cross a
process boundary because it is a QObject, but TopoDS_Shape pickles.
"""

import multiprocessing as mp
import os
import pickle
import queue
import time
from typing import List, Optional, Tuple

from core.g_data_node import GDataNode

# The in-process read stays the fast path for ordinary parts: a spawned
# interpreter costs about 2 s before it reads anything, which only pays off
# once the blocking read is longer than that.
BIG_FILE_BYTES = 4 * 1024 * 1024

_CHILD_TIMEOUT_S = 15 * 60.0
_POLL_S = 0.05


def needs_child_process(file_path: str) -> bool:
    """True when reading this file inline would visibly freeze the UI."""
    try:
        return os.path.getsize(file_path) >= BIG_FILE_BYTES
    except OSError:
        return False


def _convert_child(in_q, out_q):
    """Child entry point: read one CAD file, send back its geometry tree."""
    try:
        payload = in_q.get(timeout=60.0)
    except Exception:
        return
    if payload is None:
        return

    file_path = payload
    try:
        from core.cad_reader import CADReader        # OCC loads here

        errors: List[str] = []
        node = CADReader().read_file(file_path, errors)
        if node is None:
            out_q.put(("error", "; ".join(errors) or "unknown read error"))
            return
        out_q.put(("done", pickle.dumps(_flatten(node)), errors))
    except BaseException as e:       # a worker process must not die silently
        try:
            out_q.put(("error", f"{type(e).__name__}: {e}"))
        except Exception:
            pass


def _flatten(node: GDataNode) -> list:
    """Pre-order dump of a node tree: (name, node_type, shape, parent_index)."""
    records: list = []

    def walk(current: GDataNode, parent: int):
        index = len(records)
        records.append((current.name, current.node_type, current.shape, parent))
        for child in current.children:
            walk(child, index)

    walk(node, -1)
    return records


def _rebuild(records: list) -> Optional[GDataNode]:
    """Rebuild the tree the child sent; the nodes are created in this process."""
    root: Optional[GDataNode] = None
    nodes: List[GDataNode] = []
    for name, node_type, shape, parent in records:
        node = GDataNode(node_type, name)
        node.shape = shape
        if parent < 0:
            root = node
        else:
            nodes[parent].add_child(node)
        nodes.append(node)
    return root


def read_file_in_child_process(file_path: str, pump=None
                               ) -> Tuple[Optional[GDataNode], List[str]]:
    """Read one CAD file in a child process.

    Args:
        file_path: CAD file to read.
        pump: Optional callable invoked every ~50 ms while the child works, so
              the caller can keep its UI alive and show progress.  Returning
              False cancels the read (the child is killed).

    Returns:
        (file node, error messages). The node is None if nothing was read.
    """
    errors: List[str] = []
    ctx = mp.get_context("spawn")
    in_q = ctx.Queue()
    out_q = ctx.Queue()
    proc = ctx.Process(target=_convert_child, args=(in_q, out_q),
                       name="CadImport", daemon=True)

    msg = None
    try:
        proc.start()
        in_q.put(file_path)

        deadline = time.time() + _CHILD_TIMEOUT_S
        while True:
            try:
                msg = out_q.get(timeout=_POLL_S)
                break
            except queue.Empty:
                pass
            except (EOFError, OSError, ValueError):
                break

            if not proc.is_alive():
                # The child is gone: give the queue one last look before
                # blaming it for a crash rather than a slow exit.
                try:
                    msg = out_q.get(timeout=0.5)
                except (queue.Empty, EOFError, OSError, ValueError):
                    errors.append(f"Import process died while reading: {file_path}")
                break

            if time.time() > deadline:
                errors.append(f"Timed out reading: {file_path}")
                break

            if pump is not None and not pump():
                errors.append("Import cancelled by user.")
                break
    except Exception as e:
        errors.append(f"Could not start the import process: {e}")
    finally:
        try:
            if proc.is_alive():
                proc.terminate()
            proc.join(timeout=2.0)
        except Exception:
            pass
        for q in (in_q, out_q):
            try:
                q.close()
            except Exception:
                pass

    if msg is None:
        return None, errors
    if msg[0] == "error":
        errors.append(msg[1])
        return None, errors

    _, blob, child_errors = msg
    errors.extend(child_errors)
    try:
        records = pickle.loads(blob)
    except Exception as e:
        errors.append(f"Could not rebuild geometry: {type(e).__name__}: {e}")
        return None, errors
    return _rebuild(records), errors
