# Material Assignment

## Overview

Materials can be assigned to geometry parts from two sources:

- **Global Materials** — NIST standard materials (prefixed `G4_*`), loaded from `data/nist.txt`. Read-only, cannot be modified or deleted.
- **Local Materials** — User-defined materials (custom elements, compounds, mixtures). Fully customizable, can be saved to / loaded from JSON files.

---

## Assigning Materials

1. Import a CAD file (STEP / BREP / IGES / STL).
2. Click the **Assign Material** button on the Ribbon toolbar.
3. The **Assign Material** dialog opens (non-modal — you can interact with the main window while it is open).

### Assign Material Dialog Layout

```
┌─────────────────────────────────────────────────┐
│  Assign Material                                │
├─────────────────────────────────────────────────┤
│  ┌──────────────┐   ┌────────────────────────┐  │
│  │  Part List    │   │  Material Selection    │  │
│  │               │   │                        │  │
│  │  ☑ Bracket    │   │  Global Materials      │  │
│  │  ☐ Shaft      │   │   └─ G4_Pb             │  │
│  │  ☐ Housing    │   │   └─ G4_Al             │  │
│  │               │   │                        │  │
│  │               │   │  Local Materials       │  │
│  │               │   │   └─ MyCustomSteel     │  │
│  │               │   │                        │  │
│  │  Select All   │   │  [Assign]  [Remove]    │  │
│  └──────────────┘   └────────────────────────┘  │
├─────────────────────────────────────────────────┤
│  [Save Assignments]                              │
└─────────────────────────────────────────────────┘
```

### Steps

1. Check the parts you want to assign a material to (left panel).
2. Select a material from the Global or Local material tree (right panel).
3. Click **Assign** to apply the material to all checked parts.
4. To remove a material assignment, select the part(s) and click **Remove**.
5. Click **Save Assignments** to persist the assignments back to the data model.
6. The logger panel shows a summary: `"Material assignments saved — X/Y part(s) have materials."`

---

## Local Materials

### Adding a Local Material

1. Right-click **Local Materials** in the Project Tree.
2. Select **Add Material...**.
3. The **Local Material** dialog opens, supporting three types:

| Type | Description | Key Parameters |
|------|-------------|----------------|
| **Element** | A single chemical element | Symbol, Atomic number, Atomic mass, Density |
| **Compound** | A chemical compound (fixed ratio) | Formula, Density, constituent elements |
| **Mixture** | A mixture of elements/compounds (fraction by mass) | Density, components with mass fractions |

4. On accept, the material is added to the Local Materials tree.

### Saving Local Materials to JSON

1. Right-click **Local Materials** in the Project Tree.
2. Select **Save Materials...**.
3. Choose a file location (default: `local_materials.json` in the last import directory).
4. All local materials are exported to a JSON file.

Example JSON output:

```json
{
  "elements": {
    "MyCustomElement": {
      "symbol": "Xe",
      "z": 54,
      "a": 131.29,
      "density": 5.9
    }
  },
  "compounds": {
    "Water": {
      "formula": "H2O",
      "density": 1.0,
      "components": [
        {"element": "H", "atom_count": 2},
        {"element": "O", "atom_count": 1}
      ]
    }
  }
}
```

### Loading Local Materials from JSON

1. Right-click **Local Materials** in the Project Tree.
2. Select **Load Materials...**.
3. Pick a previously saved `local_materials.json` file.
4. The materials are loaded and appear in the Local Materials tree.
5. The logger shows: `"Loaded X local materials from ..."`

> **Note**: Loading replaces the current local materials library — existing local materials will be overwritten.

### Deleting a Local Material

1. Right-click on a specific local material node in the tree.
2. Select **Delete Material**.
3. The material is removed from the library.

---

## Property Panel for Materials

When a material node is selected in the Project Tree:

### Global Material (NIST)

Shows General info: Name, Symbol, Z, A — plus a link reference to Geant4 documentation.

### Local Material

Shows General info plus Material Details:
- Density
- Symbol, Atomic number, Atomic mass
- Chemical composition table with elements, proportions, and Z values (HTML formatted)
