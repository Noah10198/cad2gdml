"""
conformity.py -- "Conformity state": the only mesh property that changes physics.

Background: see doc/assembly_fragment_ui.md. The conclusion is:
    The root cause is not "whether the parts are merged", but whether the
    contact faces share the same facets. When solids are meshed one by one,
    both sides of a contact face get their own facet set (coincident in space,
    unrelated in topology). Geant4's G4TessellatedSolid decides inside/outside
    from the facet normal, so it reports a pile of false Overlaps. Only a
    whole-assembly BooleanFragments can make contact faces share one topology.

This state travels through three stages:
    after import  -> contact analysis (decides which mode to use)
    after meshing -> actual mesh mode + reassignment result (decides conformity)
    before export -> block on 🔴 and require an explicit user confirmation

The colours come from the same palette as the existing ✓ known / ⚠ not found
in ui/export_gdml_dialog.py; no new colour scheme is introduced.
"""

from dataclasses import dataclass, field
from typing import List, Tuple


# ---- State values ----

UNKNOWN = "unknown"              # ⚪ not meshed yet
CONFORMAL = "conformal"          # 🟢 conformal, contact faces share facets
PARTIAL = "partial"              # 🟡 some solids failed / degraded
NON_CONFORMAL = "non_conformal"  # 🔴 non-conformal, coincident facets exist

COLOR_OK = "#a6e3a1"
COLOR_WARN = "#f9e2af"
COLOR_BAD = "#f38ba8"
COLOR_IDLE = "#a6adc8"

_SPEC = {
    CONFORMAL:     (COLOR_OK, "Conformal"),
    PARTIAL:       (COLOR_WARN, "Partial"),
    NON_CONFORMAL: (COLOR_BAD, "Non-conformal"),
    UNKNOWN:       (COLOR_IDLE, "Not meshed"),
}

# The palette above is tuned for the dark theme; its pastel green / yellow / red
# are close to invisible on a light dialog background. These are the readable
# equivalents, picked with the same `dark` flag every state-coloured widget in
# this project carries (cf. RibbonToolBar / ProjectTreeWidget / GmshDialog).
_LIGHT_COLOR = {
    CONFORMAL:     "#2e7d32",
    PARTIAL:       "#9a6700",
    NON_CONFORMAL: "#d32f2f",     # == the light palette's BrightText
    UNKNOWN:       "#555555",
}


def color(kind: str) -> str:
    """Return the foreground colour (hex) for this state."""
    return _SPEC.get(kind, _SPEC[UNKNOWN])[0]


def state_color_for(kind: str, dark: bool) -> str:
    """Foreground colour readable for `kind` in the given theme."""
    if dark:
        return color(kind)
    return _LIGHT_COLOR.get(kind, color(kind))


def text(kind: str) -> str:
    """Return the short state name."""
    return _SPEC.get(kind, _SPEC[UNKNOWN])[1]


def rich(kind: str, dark: bool = True) -> str:
    """Return a coloured HTML fragment, matching export_gdml_dialog."""
    return (f'<span style="color:{state_color_for(kind, dark)}; '
            f'font-weight:bold;">{text(kind)}</span>')


# ---- Contact analysis result ----


@dataclass
class AnalysisResult:
    """Result of the "contact analysis" run right after import; the only input
    to mesh mode selection.

    The criterion is neither the number of files nor the number of solids, but
    whether **any two participating solids have a contact face**:
      - contact found -> per-solid meshing inevitably drops its own facet set on
                         both sides of the contact face (coincident facets > 0);
                         only assembly BooleanFragments can drive that to zero
                         -> assembly
      - all separated -> both modes give 0 coincident facets, take the cheaper
                         one -> per_solid
      - only 1 solid  -> nothing to fragment -> per_solid
    """

    n_solids: int = 0
    bbox_diag: float = 0.0
    tol: float = 0.0
    tested_pairs: int = 0
    contact_pairs: List[Tuple[str, str, float]] = field(default_factory=list)
    # The same pairs as *indices* into the `shapes` / `names` list the analysis
    # was handed (i.e. into the solids in tree order). `contact_pairs` addresses
    # solids by name, and a CAD reader can hand out one name twice -- measured on
    # exampleSTEP/as1-oc-214.stp the reader yields 18 solids but only 4 distinct
    # names -- which makes a name-keyed grouping merge parts that never touch.
    # Indices cannot collide, so they are what the scope grouping uses.
    contact_indices: List[Tuple[int, int, float]] = field(default_factory=list)
    min_dist: float = float("inf")
    mode: str = "per_solid"          # "assembly" | "per_solid"
    reason: str = ""
    elapsed: float = 0.0
    failed: bool = False

    @property
    def has_contact(self) -> bool:
        return bool(self.contact_pairs)

    @property
    def mode_label(self) -> str:
        return "Assembly (conformal)" if self.mode == "assembly" else "Per-solid"

    def summary(self) -> str:
        """One-line summary, used by the system log and the dialog summary box."""
        if self.failed:
            return "Contact analysis incomplete"
        return (f"{self.n_solids} solids · {len(self.contact_pairs)} contact pairs · "
                f"{self.mode_label}")


# ---- Meshing result ----


@dataclass
class MeshOutcome:
    """Final verdict of this meshing run, shared by the status bar, the progress
    panel and the export gate."""

    kind: str = UNKNOWN                  # one of the conformity constants
    requested_mode: str = "per_solid"    # mode requested by user / auto
    actual_mode: str = "per_solid"       # mode actually used (may be degraded)
    n_solids: int = 0
    n_meshed: int = 0
    overlap_facets: int = 0              # coincident facets found (0 = truly conformal)
    open_edges: int = 0                  # total number of non-closed edges
    bad_solids: List[str] = field(default_factory=list)
    elapsed: float = 0.0
    notes: List[str] = field(default_factory=list)

    @property
    def degraded(self) -> bool:
        return self.actual_mode != self.requested_mode

    @property
    def headline(self) -> str:
        """Text only -- no leading state dot: the same emoji used to drag a
        second font (Segoe UI Emoji) into the banner and the system log."""
        return f"{text(self.kind)} · {self.n_meshed} solids"

    def detail_lines(self) -> List[str]:
        """Lines shared by the export dialog "Mesh status" block and the outcome
        banner of the progress panel."""
        lines = [f"{self.n_meshed} solids · coincident facets {self.overlap_facets}"]
        if self.actual_mode == "assembly":
            lines.append("Mesh mode: assembly conformal (contact faces share facets)")
        else:
            lines.append("Mesh mode: per-solid")
        if self.degraded:
            lines.append("⚠ Assembly job failed, degraded to per-solid meshing")
        if self.kind == NON_CONFORMAL and self.overlap_facets:
            lines.append("⚠ Contact faces do not share facets; "
                         "Geant4 may report false Overlaps")
        if self.bad_solids:
            shown = ", ".join(self.bad_solids[:3])
            more = f" (+{len(self.bad_solids) - 3} more)" if len(self.bad_solids) > 3 else ""
            lines.append(f"⚠ Surface not closed: {shown}{more}")
        lines.extend(self.notes)
        return lines
