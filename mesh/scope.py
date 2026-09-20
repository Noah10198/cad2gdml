"""
scope.py -- "Which parts does this re-mesh touch?": the re-mesh scope model.

Background: see doc/remesh_scope_mockup.html. The contact pairs found by the
import-time contact analysis form a graph (nodes = solids, edge = "these two
share a contact face"). Its connected components are exactly the smallest units
that can be re-meshed on their own:

  - a component with edges -> *coupled*: both sides of its contact faces share
    one facet set. Re-meshing a single member would drop a fine facet set on one
    side of that face and keep the coarse one on the other -> unrelated
    topologies -> coincident facets > 0 -> Geant4 reports false Overlaps. The
    whole component has to be re-fragmented together (one assembly job).
  - an isolated node -> *independent*: it shares no face with anybody, so it can
    be re-meshed alone (one per-solid job), cheaply and without side effects.

The user never sees the words "contact graph" or "connected component": the
panel shows each group with an `Assembly conformal` / `Per-solid` chip, which
turns a constraint of the mesher into a visible fact (mockup §1).

Nothing here talks to gmsh: it is pure bookkeeping over an AnalysisResult, so it
can be read and tested on its own.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple


@dataclass
class MeshGroup:
    """One re-mesh unit: the parts that are re-meshed together, or not at all."""

    index: int = 0
    entry_ids: List[str] = field(default_factory=list)
    # A unit that is not a whole component -- one solid of one, in per-solid
    # mode -- carries the solid's name instead of a group letter: "Group C" is
    # not what the user sees in the tree, and two rows both called "Group C"
    # would be two different answers to the same question.
    name: str = ""

    @property
    def coupled(self) -> bool:
        """True when the group holds contact faces -> it needs an assembly job.

        `build_groups` only ever merges two nodes through a contact pair, so a
        group of more than one member always has at least one edge.
        """
        return len(self.entry_ids) > 1

    @property
    def n_parts(self) -> int:
        return len(self.entry_ids)

    @property
    def letter(self) -> str:
        """A / B / ... -- how the group is named in the log and the status bar."""
        if self.index < 26:
            return chr(ord("A") + self.index)
        return str(self.index + 1)

    @property
    def label(self) -> str:
        """Group A / Group B ... (used in the scope panel and the log).

        A named unit -- a single solid shown on its own -- is called by its name:
        that is the one thing the reader can match against the tree.
        """
        return self.name or f"Group {self.letter}"

    @property
    def short_label(self) -> str:
        """The name in one line of the log: `A`, or the solid's name."""
        return self.name or self.letter

    @property
    def mode(self) -> str:
        return "assembly" if self.coupled else "per_solid"

    @property
    def mode_label(self) -> str:
        """The chip next to the group name; the only place this appears."""
        return "Assembly conformal" if self.coupled else "Per-solid"


def build_groups(nodes: Sequence,
                 contact_pairs: Sequence[Tuple[str, str, float]] = (),
                 id_of: Optional[Callable] = None,
                 name_of: Optional[Callable] = None,
                 index_pairs: Optional[Sequence[Tuple[int, int, float]]] = None,
                 ) -> List[MeshGroup]:
    """Turn the contact pairs into the list of re-mesh units.

    `nodes` are the solids in tree order. `contact_pairs` is what
    `AnalysisResult.contact_pairs` holds after import, i.e. ``(name_a, name_b,
    distance)`` -- names, not entry ids (assembly_analysis.py builds it from
    ``node.name``). A pair naming something that is no longer in the tree is
    ignored: the geometry changed under the analysis.

    `index_pairs` is `AnalysisResult.contact_indices`: the same pairs with the
    solids addressed by their position in `nodes`. It is preferred when it is
    usable, because names are not guaranteed to be unique -- the reader names
    solids per parent, so a nested assembly can yield several `_Solid_1` (18
    solids / 4 distinct names on exampleSTEP/as1-oc-214.stp). A name-keyed merge
    would then join parts that never touch and hide the contact edges that the
    analysis actually found. When the indices do not fit the current tree (the
    model was imported again) the name map is used instead.

    Result order follows the tree, and the groups are returned in the order of
    their first member, so the panel and the log are stable across runs.
    """
    id_of = id_of or (lambda n: n.entry_id)
    name_of = name_of or (lambda n: n.name or n.entry_id)

    order: List[str] = []
    ids_by_key: Dict[str, str] = {}
    for n in nodes:
        eid = id_of(n)
        order.append(eid)
        # Both spellings are registered: the analysis may have used the name, and
        # a nameless node falls back to its entry id.
        ids_by_key.setdefault(name_of(n), eid)
        ids_by_key.setdefault(eid, eid)

    parent: Dict[str, str] = {eid: eid for eid in order}

    def find(x: str) -> str:
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:            # path compression
            parent[x], x = root, parent[x]
        return root

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    usable_indices = bool(index_pairs) and all(
        0 <= int(i) < len(order) and 0 <= int(j) < len(order)
        for i, j, _ in index_pairs)

    if usable_indices:
        for i, j, _d in index_pairs:
            if i != j:
                union(order[int(i)], order[int(j)])
    else:
        for pair in contact_pairs:
            a = ids_by_key.get(pair[0])
            b = ids_by_key.get(pair[1])
            if a is None or b is None or a == b:
                continue
            union(a, b)

    buckets: Dict[str, List[str]] = {}
    for eid in order:
        buckets.setdefault(find(eid), []).append(eid)

    return [MeshGroup(index=i, entry_ids=members)
            for i, members in enumerate(buckets.values())]


def group_key(entry_ids: Sequence[str]) -> Tuple[str, ...]:
    """A group's identity across sessions: its members, in a fixed order.

    Indices are recomputed on every panel open and move as soon as the contact
    analysis lands, names repeat inside an assembly; the member set is the one
    thing that still identifies "the parts that were meshed together", so that is
    what the per-group values and the reuse test are keyed by.
    """
    return tuple(sorted(entry_ids))


def group_index_of(groups: Sequence[MeshGroup], entry_id: str) -> Optional[int]:
    """Index of the group holding `entry_id`, or None if it is not in the tree."""
    for g in groups:
        if entry_id in g.entry_ids:
            return g.index
    return None


def part_param_rows(meshed_nodes: Dict[str, str],
                    meshed_params: Dict[Tuple[str, ...], dict],
                    groups: Sequence[MeshGroup],
                    names: Dict[str, str],
                    fallback: dict) -> List[dict]:
    """One row per meshed part: the unit it belongs to and the values behind it.

    The preview used to print one parameter set over every mesh it showed, which
    is only the truth while every unit shares one set. This is the per-part
    reading of the same records the panel writes, and it follows the panel's own
    rule for finding them (remesh_scope_dialog._unit_params): a part's own values
    when it has a record of its own, otherwise the record of the unit it is in,
    otherwise the values of the last run.

    Iterating `names` is what puts the rows in tree order, and what drops a part
    whose mesh is no longer in the tree.
    """
    unit_of: Dict[str, MeshGroup] = {}
    for g in groups:
        for eid in g.entry_ids:
            unit_of[eid] = g

    rows: List[dict] = []
    for eid, name in names.items():
        path = meshed_nodes.get(eid)
        if not path:
            continue
        g = unit_of.get(eid)
        own = meshed_params.get(group_key([eid]))
        if own is None and g is not None:
            own = meshed_params.get(group_key(g.entry_ids))
        rows.append({
            "part": name,
            "unit": g.label if g else "—",
            "unit_parts": g.n_parts if g else 1,
            "file": path,
            "params": dict(own or fallback),
        })
    return rows


def scope_text(selected: Sequence[MeshGroup], kept: Sequence[MeshGroup]) -> str:
    """`scope: A B C (5 parts) · keep: D` -- the header of one re-mesh block in
    the log, so that a history of a dozen runs stays readable.

    A named unit is listed by its name (see MeshGroup.short_label): a per-solid
    run has no group letters to point at, only the solids it touched.
    """
    sel = " ".join(g.short_label for g in selected) or "-"
    n_sel = sum(g.n_parts for g in selected)
    text = f"scope: {sel} ({n_sel} parts)"
    if kept:
        text += f" · keep: {' '.join(g.short_label for g in kept)}"
    return text
