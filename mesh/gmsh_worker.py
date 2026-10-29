"""One meshing job, run by the Python gmsh module in a child process.

Usage:  python -u gmsh_worker.py job.json

Why a child process at all, if the gmsh package is importable?  Because a
surface solve cannot be interrupted from the inside: the only way to honour
Cancel or the timeout is to kill something.  The child imports the `gmsh`
module (pip install gmsh, which ships the full kernel and the OCC bindings),
so no gmsh executable is needed anywhere, on any platform.

The job file is written by mesh/mesh_runner.py and holds only paths and
numbers, so it stays readable when a job has to be reproduced by hand.
"""

import json
import sys


def apply_mesh_options(gmsh, spec):
    """Same six options the old .geo template set, in API form."""
    gmsh.option.setNumber("Mesh.Algorithm", spec["algorithm"])
    gmsh.option.setNumber("Mesh.Smoothing", spec["smoothing"])
    gmsh.option.setNumber("Mesh.CharacteristicLengthFactor",
                          spec["elem_factor"])
    gmsh.option.setNumber("Mesh.MeshSizeMin", spec["size_min"])
    gmsh.option.setNumber("Mesh.MeshSizeMax", spec["size_max"])
    gmsh.option.setNumber("Mesh.ElementOrder", spec["order"])


def run(spec):
    import gmsh

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 1)
    gmsh.option.setNumber("General.AbortOnError", 2)
    try:
        gmsh.model.add("easy2rad")
        for step_file in spec["steps"]:
            gmsh.model.occ.importShapes(step_file)
        gmsh.model.occ.synchronize()

        if spec.get("fragment"):
            # Conformal assembly: split every solid against the others, so both
            # sides of a contact face end up with the same topology.
            gmsh.model.occ.fragment(gmsh.model.getEntities(3), [])
            gmsh.model.occ.synchronize()

        apply_mesh_options(gmsh, spec)
        # 2D only: a STEP solid needs its surfaces tessellated, not filled.
        gmsh.model.mesh.generate(2)

        for path in spec["outputs"]:
            gmsh.write(path)
    finally:
        gmsh.finalize()


def main(argv):
    if len(argv) < 2:
        print("usage: gmsh_worker.py job.json", file=sys.stderr)
        return 2
    # utf-8-sig: the file is ours, but an editor may have saved it with a BOM
    with open(argv[1], "r", encoding="utf-8-sig") as f:
        spec = json.load(f)
    run(spec)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
