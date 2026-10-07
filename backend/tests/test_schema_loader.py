"""Тесты загрузки YAML-шаблонов и разрешения imports."""

from __future__ import annotations

from pathlib import Path

import pytest

from paper2data.schema.loader import list_templates, resolve_template, templates_root


def test_templates_root_exists():
    root = templates_root()
    assert root.is_dir()
    assert (root / "compounds_core.yaml").is_file()
    assert (root / "coordination_compounds.yaml").is_file()
    assert (root / "oled.yaml").is_file()
    assert (root / "luminescence.yaml").is_file()
    assert (root / "toxicity.yaml").is_file()


def test_list_templates():
    items = list_templates()
    ids = {t["id"] for t in items}
    assert "compounds_core" in ids
    assert "coordination_compounds" in ids
    assert "oled" in ids
    assert "luminescence" in ids
    assert "toxicity" in ids


def test_resolve_coordination_compounds():
    schema = resolve_template("coordination_compounds")
    assert schema["id"] == "coordination_compounds"
    assert schema["kind"] == "schema"
    entity_ids = {e["id"] for e in schema["entity_types"]}
    assert {"Paper", "Compound", "Component", "Property", "Condition"}.issubset(entity_ids)
    relation_ids = {r["id"] for r in schema["relation_types"]}
    assert "HAS_COMPONENT" in relation_ids
    assert "HAS_PROPERTY" in relation_ids
    assert "compounds_core" in schema["resolved_imports"]
    # Роли лигандов из overlay
    has_comp = next(r for r in schema["relation_types"] if r["id"] == "HAS_COMPONENT")
    role_attr = next(a for a in has_comp["attributes"] if a["id"] == "role")
    assert role_attr["type"] == "enum"
    assert "central_cation" in role_attr["enum_values"]
    # Lum enum через attribute_extensions
    prop = next(e for e in schema["entity_types"] if e["id"] == "Property")
    prop_type = next(a for a in prop["attributes"] if a["id"] == "property_type")
    assert "lifetime" in prop_type["enum_values"]
    assert "radiative_lifetime" in prop_type["enum_values"]
    assert "quantum_yield" in prop_type["enum_values"]
    group_ids = {g["id"] for g in schema.get("extraction_groups") or []}
    assert "compounds" in group_ids
    assert "luminescence" in group_ids


def test_oled_imports_coordination_compounds():
    schema = resolve_template("oled")
    assert schema["id"] == "oled"
    assert "coordination_compounds" in schema["imports"]
    assert "coordination_compounds" in schema["resolved_imports"]
    assert "compounds_core" in schema["resolved_imports"]

    entity_ids = {e["id"] for e in schema["entity_types"]}
    # Из импорта
    assert "Compound" in entity_ids
    assert "Property" in entity_ids
    # OLED-специфичные
    assert "Device" in entity_ids
    assert "Layer" in entity_ids
    assert "Material" in entity_ids

    relation_ids = {r["id"] for r in schema["relation_types"]}
    assert "HAS_LAYER" in relation_ids
    assert "IS_COMPOUND" in relation_ids
    assert "HAS_COMPONENT" in relation_ids  # из импорта

    group_ids = {g["id"] for g in schema.get("extraction_groups") or []}
    assert "compounds" in group_ids
    assert "device_stack" in group_ids
    assert "device_metrics" in group_ids
    assert "luminescence" in group_ids
    stack = next(g for g in schema["extraction_groups"] if g["id"] == "device_stack")
    assert "Layer" in stack["entities"]
    assert "IS_COMPOUND" in stack["relations"]


def test_oled_attribute_extensions_merge_enum():
    schema = resolve_template("oled")
    prop = next(e for e in schema["entity_types"] if e["id"] == "Property")
    prop_type = next(a for a in prop["attributes"] if a["id"] == "property_type")
    enums = prop_type["enum_values"]
    # Базовые из coordination_compounds
    assert "lifetime" in enums
    assert "radiative_lifetime" in enums
    assert "quantum_yield" in enums
    # Расширения OLED
    assert "eqe" in enums
    assert "turn_on_voltage" in enums
    assert "cie_coordinates" in enums
    assert "sensitization_efficiency" in enums


def test_luminescence_and_toxicity_templates():
    lum = resolve_template("luminescence")
    assert "coordination_compounds" in lum["resolved_imports"]
    prop = next(e for e in lum["entity_types"] if e["id"] == "Property")
    enums = next(a for a in prop["attributes"] if a["id"] == "property_type")["enum_values"]
    assert "fwhm" in enums
    assert "stokes_shift" in enums
    assert "sensitization_efficiency" in enums
    assert "lifetime" in enums

    tox = resolve_template("toxicity")
    assert "compounds_core" in tox["resolved_imports"]
    assert "Compound" in {e["id"] for e in tox["entity_types"]}
    prop_t = next(e for e in tox["entity_types"] if e["id"] == "Property")
    tox_enums = next(a for a in prop_t["attributes"] if a["id"] == "property_type")[
        "enum_values"
    ]
    assert "ic50" in tox_enums
    assert "ld50" in tox_enums
    cond = next(e for e in tox["entity_types"] if e["id"] == "Condition")
    cond_attrs = {a["id"] for a in cond["attributes"]}
    assert {"organism", "cell_line", "assay_name", "exposure_time", "route"}.issubset(
        cond_attrs
    )
    assert {g["id"] for g in tox["extraction_groups"]} >= {"compounds", "toxicity"}


def test_extraction_groups_merge_on_import(tmp_path: Path):
    base = tmp_path / "base.yaml"
    child = tmp_path / "child.yaml"
    base.write_text(
        """
version: '1'
id: base
name: Base
kind: schema
entity_types:
  - id: A
    name: A
    attributes: []
  - id: B
    name: B
    attributes: []
relation_types:
  - id: R1
    name: r1
    from: A
    to: B
extraction_groups:
  - id: g1
    name: Group1
    entities: [A]
    relations: [R1]
    instructions: from base
""",
        encoding="utf-8",
    )
    child.write_text(
        """
version: '1'
id: child
name: Child
kind: schema
imports: [base]
entity_types:
  - id: C
    name: C
    attributes: []
relation_types:
  - id: R2
    name: r2
    from: B
    to: C
extraction_groups:
  - id: g1
    name: Group1 extended
    entities: [B]
    relations: [R2]
    instructions: from child
  - id: g2
    name: Group2
    entities: [C]
    relations: []
""",
        encoding="utf-8",
    )
    schema = resolve_template("child", root=tmp_path)
    groups = {g["id"]: g for g in schema["extraction_groups"]}
    assert set(groups) == {"g1", "g2"}
    assert groups["g1"]["entities"] == ["A", "B"]
    assert groups["g1"]["relations"] == ["R1", "R2"]
    assert groups["g1"]["instructions"] == "from child"
    assert groups["g1"]["name"] == "Group1 extended"


def test_schema_to_yaml_dict_keeps_extraction_groups():
    from paper2data.schema.loader import schema_to_yaml_dict

    schema = resolve_template("oled")
    dumped = schema_to_yaml_dict(schema)
    assert "extraction_groups" in dumped
    ids = {g["id"] for g in dumped["extraction_groups"]}
    assert "device_stack" in ids


def test_cyclic_import_raises(tmp_path: Path):
    a = tmp_path / "a.yaml"
    b = tmp_path / "b.yaml"
    a.write_text(
        "version: '1'\nid: a\nname: A\nkind: schema\nimports: [b]\nentity_types: []\nrelation_types: []\n",
        encoding="utf-8",
    )
    b.write_text(
        "version: '1'\nid: b\nname: B\nkind: schema\nimports: [a]\nentity_types: []\nrelation_types: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Циклический"):
        resolve_template("a", root=tmp_path)


def test_missing_template_raises():
    with pytest.raises(FileNotFoundError):
        resolve_template("does_not_exist_xyz")
