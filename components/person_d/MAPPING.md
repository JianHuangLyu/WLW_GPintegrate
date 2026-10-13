# Person D vocabulary to diagnosticCriteria mapping

Generated from `mapping_acceptance.json` by `python -m components.person_d.mapping --write`; do not
edit by hand. `tests/test_mapping.py` keeps the two files, the mapping rule and the reference
assets in step.

| Item | Value |
|---|---|
| diagnosticCriteria version | `1.2.1` |
| Prompt asset (vocabulary) | `1.1.0`, SHA-256 `e61b7d784aa8959305c22db7eb71921d5487ab479ebbaa16abb3c3ca957099d4` |
| Label map | `1.0.0`, SHA-256 `e1f59e667358fbca6f6bfe70cbfc140cd6c0a4ed8f6661920b5562a042f46e38` |
| Attributes | 24 |
| Vocabulary options | 105 |
| Criteria options | 138 |
| Unmapped vocabulary options | 1 |
| Vocabulary options mapped to several criteria options | 1 |
| Unreachable criteria options | 33 |

## Rules

1. A vocabulary label reaches criteria options through, in order: the label map attribute alias,
   the label map global alias, an exact match, a case-insensitive match (`LabelMap.resolve`).
2. An **unmapped** vocabulary label is dropped. When it was the only agreed label, the attribute is
   not evaluated (`unmapped_label`).
3. A vocabulary label **mapped to several** criteria options counts once when those options carry
   the same condition in the query's criteria; when their conditions differ the label is ambiguous
   and dropped (`ambiguous_label`).
4. An **unreachable** criteria option is one no vocabulary label reaches, so the backend can never
   predict it. In matching:
   - a `Must_True` or `Must_False` condition on an unreachable option cannot be verified. It never
     counts as passed: the query is `skipped` (`insufficient_visual_evidence`) under
     `unverified_must_true: skip`, or `rejected` (`must_condition_failed`) under `reject`, and is
     never `selected`. A verified failure on another attribute still rejects first;
   - a miss on an attribute whose `Must_True` option is unreachable is unverified, not failed;
   - any other condition on an unreachable option simply never contributes to the score.

## Unreachable criteria options by category

| Category | Options | Meaning |
|---|---:|---|
| `filed_under_another_attribute` | 1 | Not covered for this attribute. The vocabulary carries the same concept under a different attribute than criteria 1.2.1. |
| `generic_not_otherwise_specified` | 2 | Not a prediction target. The vocabulary always assigns a specific type or Absent, never the generic 'present, type not specified' category. |
| `not_covered` | 16 | Not covered. The vocabulary of pipeline_quilt_1m.py predates criteria 1.2.1 and has no label for this option; the backend can never predict it. |
| `unable_to_confirm` | 14 | Not a prediction target. The attribute has no N/A label; the backend expresses that it cannot assess an attribute through model disagreement, which leaves the attribute unevaluated. |

| Attribute | Criteria option | Category | Note |
|---|---|---|---|
| `Cellular_and_Nuclear.Cell_Pleomorphism` | Unable to confirm | `unable_to_confirm` |  |
| `Cellular_and_Nuclear.Cytological_Atypia` | Unable to confirm | `unable_to_confirm` |  |
| `Cellular_and_Nuclear.Chromatin` | Salt-and-pepper | `not_covered` |  |
| `Cellular_and_Nuclear.Chromatin` | Smudged | `not_covered` |  |
| `Cellular_and_Nuclear.Chromatin` | Unable to confirm | `unable_to_confirm` |  |
| `Cellular_and_Nuclear.Nuclear_Size` | Enlargement | `not_covered` |  |
| `Cellular_and_Nuclear.Nuclear_Size` | Unable to confirm | `unable_to_confirm` |  |
| `Cellular_and_Nuclear.Nuclear_Shape` | Vesicular | `not_covered` |  |
| `Cellular_and_Nuclear.Nuclear_Shape` | Variable | `not_covered` |  |
| `Cellular_and_Nuclear.Nuclear_Shape` | Unable to confirm | `unable_to_confirm` |  |
| `Cellular_and_Nuclear.Prominent_Nucleoli` | Unable to confirm | `unable_to_confirm` |  |
| `Cellular_and_Nuclear.Epithelial_Cell_Shape` | Bilayered | `not_covered` |  |
| `Cellular_and_Nuclear.Epithelial_Cell_Shape` | Unable to confirm | `unable_to_confirm` |  |
| `Cellular_and_Nuclear.Polarity` | Unable to confirm | `unable_to_confirm` |  |
| `Architecture.Pattern` | Absent, No special pattern | `not_covered` |  |
| `Architecture.Pattern` | Simple Tubular/Branching Structures | `not_covered` |  |
| `Architecture.Pattern` | Tubular/Glandular | `not_covered` |  |
| `Architecture.Pattern` | Cystic/Microcystic | `not_covered` |  |
| `Architecture.Pattern` | Syncytial | `not_covered` |  |
| `Architecture.Pattern` | Nests/Morules | `not_covered` |  |
| `Architecture.Specific_Sub_Architectures` | Absent, No special pattern | `not_covered` |  |
| `Architecture.Specific_Sub_Architectures` | One to several layers | `filed_under_another_attribute` | The vocabulary files this label under Architecture.Pattern ('one to several layers'), where criteria 1.2.1 has no such option. |
| `Architecture.Architectural_Atypia` | Unable to confirm | `unable_to_confirm` |  |
| `Special_Features.Apocrine_Differentiation` | Unable to confirm | `unable_to_confirm` |  |
| `Special_Features.Apical_Snout` | Unable to confirm | `unable_to_confirm` |  |
| `Special_Features.Endoluminal_Secretion` | Physiological | `not_covered` |  |
| `Special_Features.Endoluminal_Secretion` | Mucin pools/Extracellular mucin | `not_covered` |  |
| `Special_Features.Endoluminal_Secretion` | Unable to confirm | `unable_to_confirm` |  |
| `Special_Features.Necrosis` | Present, Not Otherwise Specified | `generic_not_otherwise_specified` |  |
| `Special_Features.Necrosis` | Unable to confirm | `unable_to_confirm` |  |
| `Special_Features.Calcifications` | Coarse/Popcorn | `not_covered` |  |
| `Special_Features.Calcifications` | Present, Not Otherwise Specified | `generic_not_otherwise_specified` |  |
| `Special_Features.Calcifications` | Unable to confirm | `unable_to_confirm` |  |

## Attribute-level mapping

Each row is one vocabulary label, the criteria option or options it reaches, and the rule that
applied.

### Cellular_and_Nuclear.Cell_Pleomorphism

Criteria options: Monomorphic, Mild, Moderate, Severe, Unable to confirm

| Vocabulary label | Criteria option | Rule |
|---|---|---|
| Monomorphic | Monomorphic | exact |
| Mild | Mild | exact |
| Moderate | Moderate | exact |
| Severe | Severe | exact |

Unreachable: Unable to confirm

### Cellular_and_Nuclear.Cytological_Atypia

Criteria options: Absent, Low-grade/Mild, Intermediate-grade/Moderate, High-grade/Severe, Unable to confirm

| Vocabulary label | Criteria option | Rule |
|---|---|---|
| Absent | Absent | exact |
| Low-grade/Mild | Low-grade/Mild | exact |
| Intermediate-grade/Moderate | Intermediate-grade/Moderate | exact |
| High-grade/Severe | High-grade/Severe | exact |

Unreachable: Unable to confirm

### Cellular_and_Nuclear.Chromatin

Criteria options: Regular, Vesicular, Coarsely clumped, Hyperchromatic, Salt-and-pepper, Smudged, Unable to confirm

| Vocabulary label | Criteria option | Rule |
|---|---|---|
| Regular | Regular | exact |
| Vesicular | Vesicular | exact |
| Coarsely clumped | Coarsely clumped | exact |
| Hyperchromatic | Hyperchromatic | exact |

Unreachable: Salt-and-pepper, Smudged, Unable to confirm

### Cellular_and_Nuclear.Nuclear_Size

Criteria options: Uniform, Enlargement, Variable, Unable to confirm

| Vocabulary label | Criteria option | Rule |
|---|---|---|
| Uniform | Uniform | exact |
| Variable | Variable | exact |

Unreachable: Enlargement, Unable to confirm

### Cellular_and_Nuclear.Nuclear_Shape

Criteria options: Uniform, Spindle, Irregular/Pleomorphic, Vesicular, Variable, Unable to confirm

| Vocabulary label | Criteria option | Rule |
|---|---|---|
| Uniform | Uniform | exact |
| Spindle | Spindle | exact |
| Irregular/Pleomorphic | Irregular/Pleomorphic | exact |

Unreachable: Vesicular, Variable, Unable to confirm

### Cellular_and_Nuclear.Prominent_Nucleoli

Criteria options: Absent, Present, Unable to confirm

| Vocabulary label | Criteria option | Rule |
|---|---|---|
| Absent | Absent | exact |
| Present | Present | exact |

Unreachable: Unable to confirm

### Cellular_and_Nuclear.Epithelial_Cell_Shape

Criteria options: Bilayered, Cuboidal, Columnar, Squamous, Polygonal, Plasmacytoid, Spindle, Unable to confirm

| Vocabulary label | Criteria option | Rule |
|---|---|---|
| Cuboidal/Columnar | Cuboidal, Columnar | attribute alias |
| Squamous | Squamous | exact |
| Polygonal | Polygonal | exact |
| Plasmacytoid | Plasmacytoid | exact |
| Spindle | Spindle | exact |

`Cuboidal/Columnar`: Maps to both 'Cuboidal' and 'Columnar'. When the two options carry different conditions in a criteria the label is ambiguous and dropped; when they carry the same condition it counts once with that condition.

Unreachable: Bilayered, Unable to confirm

### Cellular_and_Nuclear.Polarity

Criteria options: Maintained, Partially lost, Completely lost, Unable to confirm

| Vocabulary label | Criteria option | Rule |
|---|---|---|
| Maintained | Maintained | exact |
| Partially lost | Partially lost | exact |
| Completely lost | Completely lost | exact |

Unreachable: Unable to confirm

### Cellular_and_Nuclear.Cytoplasmic_Features

Criteria options: Amphophilic to Pale Eosinophilic, Eosinophilic/Granular, Clear/Glycogenated, Vacuolated/Foamy/Lipid-rich, Signet-ring, Hobnail, Unable to confirm

| Vocabulary label | Criteria option | Rule |
|---|---|---|
| Amphophilic to Pale Eosinophilic | Amphophilic to Pale Eosinophilic | exact |
| Eosinophilic/Granular | Eosinophilic/Granular | exact |
| Clear/Glycogenated | Clear/Glycogenated | exact |
| Vacuolated/Foamy/Lipid-rich | Vacuolated/Foamy/Lipid-rich | exact |
| Signet-ring | Signet-ring | exact |
| Hobnail | Hobnail | exact |
| N/A | Unable to confirm | global alias |

### Cellular_and_Nuclear.Mitotic_Activity

Criteria options: Inconspicuous, Present/Brisk, Atypical figures present, Unable to confirm

| Vocabulary label | Criteria option | Rule |
|---|---|---|
| Inconspicuous | Inconspicuous | exact |
| Present/Brisk | Present/Brisk | exact |
| Atypical figures present | Atypical figures present | exact |
| N/A | Unable to confirm | global alias |

### Architecture.Pattern

Criteria options: Absent, No special pattern, Simple Tubular/Branching Structures, Solid, Comedo, Cribriform, Papillary, Trabecular/Cords, Micropapillary, Single-file/Linear cords, Fenestrated, Tubular/Glandular, Cystic/Microcystic, Syncytial, Nests/Morules, Unable to confirm

| Vocabulary label | Criteria option | Rule |
|---|---|---|
| N/A | Unable to confirm | global alias |
| Comedo | Comedo | exact |
| Solid | Solid | exact |
| Cribriform | Cribriform | exact |
| Papillary | Papillary | exact |
| Trabecular/Cords | Trabecular/Cords | exact |
| Single file | Single-file/Linear cords | attribute alias |
| one to several layers | none | unmapped |
| fenestrated | Fenestrated | case-insensitive |
| micropapillary | Micropapillary | case-insensitive |

`one to several layers`: Unmapped: criteria 1.2.1 lists 'One to several layers' under Specific_Sub_Architectures, not under Pattern. The label is dropped; when it is the only agreed label the attribute is not evaluated.

Unreachable: Absent, No special pattern, Simple Tubular/Branching Structures, Tubular/Glandular, Cystic/Microcystic, Syncytial, Nests/Morules

### Architecture.Specific_Sub_Architectures

Criteria options: Absent, No special pattern, Rigid bridges, Arches, Bulbous, Thin/Stretched bridge, Bars, Microrosettes, One to several layers, Unable to confirm

| Vocabulary label | Criteria option | Rule |
|---|---|---|
| N/A | Unable to confirm | global alias |
| Rigid bridges | Rigid bridges | exact |
| Arches | Arches | exact |
| Bulbous | Bulbous | exact |
| thin/stretched bridge | Thin/Stretched bridge | case-insensitive |
| bars | Bars | case-insensitive |
| microrosettes | Microrosettes | case-insensitive |

Unreachable: Absent, No special pattern, One to several layers

### Architecture.Architectural_Atypia

Criteria options: Absent, Mild/Moderate, Severe, Unable to confirm

| Vocabulary label | Criteria option | Rule |
|---|---|---|
| Absent | Absent | exact |
| Mild/Moderate | Mild/Moderate | exact |
| Severe | Severe | exact |

Unreachable: Unable to confirm

### Architecture.Lumina_Shape

Criteria options: Round/Oval, Slit-like/Compressed, Irregular/Angulated, Unable to confirm

| Vocabulary label | Criteria option | Rule |
|---|---|---|
| Round/Oval | Round/Oval | exact |
| Slit-like/Compressed | Slit-like/Compressed | exact |
| Irregular/Angulated | Irregular/Angulated | exact |
| N/A | Unable to confirm | global alias |

### Architecture.Tumour_Border

Criteria options: Absent, No tumour, Well-circumscribed/Pushing, Irregular/Infiltrative, Pseudoinfiltrative, Unable to confirm

| Vocabulary label | Criteria option | Rule |
|---|---|---|
| Absent, No tumour | Absent, No tumour | exact |
| Well-circumscribed/Pushing | Well-circumscribed/Pushing | exact |
| Irregular/Infiltrative | Irregular/Infiltrative | exact |
| Pseudoinfiltrative | Pseudoinfiltrative | exact |
| N/A | Unable to confirm | global alias |

### Architecture.Myoepithelial_Cell_Layer

Criteria options: Visibly Intact/Prominent, Attenuated/Indiscernible, Visibly Absent, Unable to confirm

| Vocabulary label | Criteria option | Rule |
|---|---|---|
| Visibly Intact/Prominent | Visibly Intact/Prominent | exact |
| Attenuated/Indiscernible | Attenuated/Indiscernible | exact |
| Visibly Absent | Visibly Absent | exact |
| N/A | Unable to confirm | global alias |

### Special_Features.Apocrine_Differentiation

Criteria options: Absent, Present, Unable to confirm

| Vocabulary label | Criteria option | Rule |
|---|---|---|
| Absent | Absent | exact |
| Present | Present | exact |

Unreachable: Unable to confirm

### Special_Features.Apical_Snout

Criteria options: Absent, Present, Unable to confirm

| Vocabulary label | Criteria option | Rule |
|---|---|---|
| Absent | Absent | exact |
| Present | Present | exact |

Unreachable: Unable to confirm

### Special_Features.Endoluminal_Secretion

Criteria options: Absent, Physiological, Eosinophilic/Proteinaceous, Mucinous, Cellular debris, Mucin pools/Extracellular mucin, Present, Not Otherwise Specified, Unable to confirm

| Vocabulary label | Criteria option | Rule |
|---|---|---|
| Absent | Absent | exact |
| Present | Present, Not Otherwise Specified | attribute alias |
| Eosinophilic/Proteinaceous | Eosinophilic/Proteinaceous | exact |
| Mucinous | Mucinous | exact |
| Cellular debris | Cellular debris | exact |

Unreachable: Physiological, Mucin pools/Extracellular mucin, Unable to confirm

### Special_Features.Necrosis

Criteria options: Absent, Focal/Punctate, Comedonecrosis, Present, Not Otherwise Specified, Unable to confirm

| Vocabulary label | Criteria option | Rule |
|---|---|---|
| Absent | Absent | exact |
| Focal/Punctate | Focal/Punctate | exact |
| Comedonecrosis | Comedonecrosis | exact |

Unreachable: Present, Not Otherwise Specified, Unable to confirm

### Special_Features.Calcifications

Criteria options: Absent, Coarse/Popcorn, Psammomatous, Microcalcifications, Linear, Branching, Fine pleomorphic/Clustered, Amorphous, Present, Not Otherwise Specified, Unable to confirm

| Vocabulary label | Criteria option | Rule |
|---|---|---|
| Absent | Absent | exact |
| Psammomatous | Psammomatous | exact |
| Fine pleomorphic/Clustered | Fine pleomorphic/Clustered | exact |
| microcalcifications | Microcalcifications | case-insensitive |
| amorphous | Amorphous | case-insensitive |
| linear | Linear | case-insensitive |
| branching | Branching | case-insensitive |

Unreachable: Coarse/Popcorn, Present, Not Otherwise Specified, Unable to confirm

### Special_Features.Squamous_Sebaceous_Differentiation

Criteria options: Absent, Squamous, Sebaceous, Present, Not Otherwise Specified, Unable to confirm

| Vocabulary label | Criteria option | Rule |
|---|---|---|
| Absent | Absent | exact |
| Squamous | Squamous | exact |
| Sebaceous | Sebaceous | exact |
| Present, Not Otherwise Specified | Present, Not Otherwise Specified | exact |
| N/A | Unable to confirm | global alias |

### Special_Features.Stromal_Characteristics

Criteria options: Fibrofatty/Loose Intralobular, Desmoplastic/Fibrotic, Fibroelastotic, Myxoid/Chondromyxoid, Oedematous, Unable to confirm

| Vocabulary label | Criteria option | Rule |
|---|---|---|
| Fibrofatty/Loose Intralobular | Fibrofatty/Loose Intralobular | exact |
| Desmoplastic/Fibrotic | Desmoplastic/Fibrotic | exact |
| Fibroelastotic | Fibroelastotic | exact |
| Myxoid/Chondromyxoid | Myxoid/Chondromyxoid | exact |
| Oedematous | Oedematous | exact |
| N/A | Unable to confirm | global alias |

### Special_Features.Tumour_Infiltrating_Lymphocytes

Criteria options: Absent/Sparse, Mild/Moderate, Prominent/Rich, Unable to confirm

| Vocabulary label | Criteria option | Rule |
|---|---|---|
| Absent/Sparse | Absent/Sparse | exact |
| Mild/Moderate | Mild/Moderate | exact |
| Prominent/Rich | Prominent/Rich | exact |
| N/A | Unable to confirm | global alias |
