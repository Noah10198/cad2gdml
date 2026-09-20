"""
Rigid placement of an imported CAD file -- see ui/transform_dialog.py.

A CAD import is one rigid body, not a bag of solids: the parts are placed
together and keep their positions relative to each other, which is what makes an
assembly an assembly. The placement therefore belongs to the file node -- the
same row that carries Delete -- and never to a solid inside it.

The numbers are held as a `TransformSpec` on the file node, while every node
keeps the shape it was imported with. A spec is re-applied to *that* shape
rather than on top of the last result, which buys the two things the dialog
needs: re-opening it shows the placement actually in force, and Reset is a real
reset instead of undoing one step of an ever-growing stack.

Order of operations: rotate about the centre first, then translate -- "turn it
into place, then put it there". The centre is resolved from the shapes as
imported, so it does not drift as the model is moved.
"""

import math
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCC.Core.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
from OCC.Core.TopoDS import TopoDS_Shape

ABOUT_GEOMETRY = "geometry"
ABOUT_ORIGIN = "origin"

Point = Tuple[float, float, float]

# Below this, a number counts as nothing at all. A thousandth of a degree on a
# part that is metres across moves nothing a mesh can see, and it keeps "turned
# by zero" from being reported as a change.
_ZERO = 1e-9


@dataclass(frozen=True)
class TransformSpec:
    """One imported file's placement, spelled the way the dialog spells it."""

    tx: float = 0.0
    ty: float = 0.0
    tz: float = 0.0
    rx: float = 0.0
    ry: float = 0.0
    rz: float = 0.0
    about: str = ABOUT_GEOMETRY

    @property
    def translation(self) -> Point:
        return (self.tx, self.ty, self.tz)

    @property
    def rotation(self) -> Point:
        return (self.rx, self.ry, self.rz)

    def is_identity(self) -> bool:
        """Whether this leaves every part exactly where it was imported."""
        return all(abs(v) < _ZERO for v in self.translation + self.rotation)

    def describe(self) -> str:
        """One line for the log, in the units the dialog was filled in."""
        about = ("origin" if self.about == ABOUT_ORIGIN else "geometry centre")
        return (f"T({self.tx:g}, {self.ty:g}, {self.tz:g}) mm · "
                f"R({self.rx:g}, {self.ry:g}, {self.rz:g})° about {about}")


def bbox_centre(shapes: Iterable[Optional[TopoDS_Shape]]) -> Point:
    """Centre of the box around the given shapes; the origin if there is none."""
    box = Bnd_Box()
    for shape in shapes:
        if shape is not None:
            brepbndlib.Add(shape, box)
    if box.IsVoid():
        return (0.0, 0.0, 0.0)
    x0, y0, z0, x1, y1, z1 = box.Get()
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0, (z0 + z1) / 2.0)


def rotation_centre(spec: TransformSpec,
                    base_shapes: Iterable[Optional[TopoDS_Shape]]) -> Point:
    """Where `spec` turns about, resolved from the shapes as imported."""
    if spec.about == ABOUT_ORIGIN:
        return (0.0, 0.0, 0.0)
    return bbox_centre(base_shapes)


def trsf_for(spec: TransformSpec, centre: Point) -> gp_Trsf:
    """The OCC transform for `spec`: about `centre` first, then translation."""
    rotation = gp_Trsf()
    for direction, degrees in ((gp_Dir(1, 0, 0), spec.rx),
                               (gp_Dir(0, 1, 0), spec.ry),
                               (gp_Dir(0, 0, 1), spec.rz)):
        if abs(degrees) < _ZERO:
            continue
        one = gp_Trsf()
        one.SetRotation(gp_Ax1(gp_Pnt(*centre), direction), math.radians(degrees))
        # `one` on the left of what is already there, so it is applied after it:
        # X first, then Y, then Z -- the order the dialog lists them in.
        rotation = one.Multiplied(rotation)

    trsf = gp_Trsf()
    trsf.SetTranslation(gp_Vec(*spec.translation))
    # Translation on the left again: the turn happens about the centre in the
    # frame the model was imported in, and only then is the whole thing moved.
    return trsf.Multiplied(rotation)


def transformed(shape: TopoDS_Shape, trsf: gp_Trsf) -> TopoDS_Shape:
    """`shape` under `trsf`, as a copy -- the imported shape stays as it was.

    The copy is what makes a re-edit possible: the next spec is applied to the
    imported shape again, not to this result.
    """
    return BRepBuilderAPI_Transform(shape, trsf, True).Shape()
