"""Политика OLED-стека и разведение EQE/ECE в характеристиках устройства."""

from __future__ import annotations

from typing import Any

STACK_ENTITY_TARGETS = frozenset({"Device", "Layer", "Material"})
REQUIRED_LAYER_ROLES = frozenset({"anode", "cathode"})
MAX_LOCAL_STACK_PASSES = 8
LOCAL_ENTITY_CAP = 20

_STACK_STEP_IDS = frozenset({"extract_device_stack", "device_stack"})
_METRICS_STEP_IDS = frozenset({"extract_device_metrics", "device_metrics"})
_LUMINESCENCE_STEP_IDS = frozenset({"extract_luminescence", "luminescence"})

_REFERENCE_RULE = (
    "Если статья задаёт стек отсылкой (similar structure / reproducing the structure / "
    "same as Device N / same structure) — разверни все слои эталона и измени только "
    "явно названное отличие (эмиттер, толщина, состав EML)."
)

_LABEL_RULE = (
    "Label каждого Layer и Material включает имя устройства "
    "(например «HAT-CN layer (Device 5)»). Слои другого Device не переиспользуй."
)

# Исключение из «если данных нет — пропусти поле»: роль слоя выводится из типа материала.
_LAYER_ROLE_RULE = (
    "У каждого Layer поле role обязательно. Если статья не называет функцию слоя, "
    "всё равно назначь role по стандартному типу материала и его позиции в стеке. "
    "Это исключение из правила «если данных нет — пропусти поле»: толщину, концентрации "
    "и состав не выдумывай, а role не оставляй пустым. Quote — фрагмент, где назван "
    "материал или стек, даже если слова роли (HTL, EML, emissive) там нет. "
    "Стандартные типы: ITO/FTO/IZO → anode; Al/Ag/Au/Mg:Ag/Ca → cathode; "
    "LiF/Liq/CsF тонким слоем у катода → EIL; HAT-CN/MoO3/WO3/PEDOT:PSS → HIL; "
    "NPB/NPD/TAPC/TCTA/m-MTDATA до эмиттера → HTL; "
    "блокирующий слой дырок или экситонов перед эмиттером → EBL; "
    "host:guest, doped, emissive layer, либо neat/undoped плёнка эмиттера без host "
    "(OLED neat) → EML; барьер сразу после EML (часто BCP или TPBi) → HBL; "
    "TPBi/BPhen/TmPyPB/B3PYMPM/PO-T2T и прочий электронный транспорт → ETL; "
    "capping/CPL → capping. "
    "Для OLED neat дополнительно Material.material_role = neat. "
    "other — только если материал неузнаваем и позиция в стеке роль не подсказывает."
)

# EQE (%) и ECE (cd/A) — разные property_type; модель часто склеивает их в eqe.
_METRICS_EFFICIENCY_RULE = (
    "EQE и ECE — разные характеристики устройства. Если в тексте есть обе, создай два Property, "
    "не склеивай и не пропускай вторую.\n"
    "— property_type=eqe: external quantum efficiency, EQE, η_EQE, η_ext. Единица %. "
    "Это не quantum_yield молекулы (PLQY, Φ, QY в растворе или порошке).\n"
    "— property_type=current_efficiency: external current efficiency, ECE, current efficiency, "
    "CE, η_c, η_CE, luminous efficiency. Единица cd/A или cd A^-1. "
    "Аббревиатуру ECE всегда пиши как current_efficiency, не как eqe.\n"
    "— property_type=power_efficiency: power efficiency, PE, η_p. Единица lm/W.\n"
    "В JSON пиши ровно эти id (eqe, current_efficiency, power_efficiency), не EQE/ECE/CE. "
    "Если подпись неоднозначна, решай по единице: % → eqe, cd/A → current_efficiency, "
    "lm/W → power_efficiency. Не пересчитывай одну величину в другую. "
    "ηsens (sensitization efficiency) — не eqe и не current_efficiency."
)

# ηsens — эффективность сенсибилизации, не PLQY.
_LUMINESCENCE_SENS_RULE = (
    "ηsens — эффективность сенсибилизации, не квантовый выход. "
    "Не записывай её как quantum_yield, даже если значение в %.\n"
    "— property_type=sensitization_efficiency: ηsens, η_sens, η_sensitization, "
    "sensitization efficiency, ligand-to-metal sensitization efficiency. "
    "Единица часто % или доля.\n"
    "— property_type=quantum_yield: только квантовый выход люминесценции — "
    "PLQY, Φ, Φ_PL, Φ_Ln, quantum yield, QY. "
    "Φ_Ln (intrinsic quantum yield) тоже quantum_yield, не ηsens.\n"
    "Если в тексте есть и Φ, и ηsens — два отдельных Property. "
    "В JSON пиши id sensitization_efficiency, не ηsens и не quantum_yield."
)


def is_device_stack_step(step: dict[str, Any] | None) -> bool:
    """Шаг OLED-стека по id или по целям Device+Layer+Material."""
    if not step:
        return False
    sid = str(step.get("id") or "").strip()
    if sid in _STACK_STEP_IDS or "device_stack" in sid:
        return True
    targets = step.get("targets") or {}
    ents = {str(e).strip() for e in (targets.get("entities") or []) if str(e).strip()}
    return STACK_ENTITY_TARGETS.issubset(ents)


def is_device_metrics_step(step: dict[str, Any] | None) -> bool:
    """Шаг характеристик OLED: id device_metrics или связь HAS_CHARACTERISTIC."""
    if not step:
        return False
    sid = str(step.get("id") or "").strip()
    if sid in _METRICS_STEP_IDS or sid.endswith("device_metrics"):
        return True
    targets = step.get("targets") or {}
    rels = {str(r).strip() for r in (targets.get("relations") or []) if str(r).strip()}
    ents = {str(e).strip() for e in (targets.get("entities") or []) if str(e).strip()}
    return "HAS_CHARACTERISTIC" in rels and "Property" in ents


def metrics_policy_instructions() -> str:
    """Оверлей шага характеристик: не путать EQE (%) и ECE (cd/A)."""
    return _METRICS_EFFICIENCY_RULE


def is_luminescence_step(step: dict[str, Any] | None) -> bool:
    """Шаг люминесценции молекул: id luminescence или связь HAS_PROPERTY."""
    if not step:
        return False
    sid = str(step.get("id") or "").strip()
    if sid in _LUMINESCENCE_STEP_IDS or sid.endswith("luminescence"):
        return True
    targets = step.get("targets") or {}
    rels = {str(r).strip() for r in (targets.get("relations") or []) if str(r).strip()}
    ents = {str(e).strip() for e in (targets.get("entities") or []) if str(e).strip()}
    return "HAS_PROPERTY" in rels and "Property" in ents and "HAS_CHARACTERISTIC" not in rels


def luminescence_policy_instructions() -> str:
    """Оверлей шага люминесценции: ηsens не является quantum_yield."""
    return _LUMINESCENCE_SENS_RULE


def stack_policy_instructions(*, local_llm: bool) -> str:
    """Оверлей, отменяющий старые фразы рецепта про «нет слоёв» и «20 entities»."""
    if local_llm:
        return (
            "ОТМЕНЯЕТ лимит «20 entities» и правило «только устройства, у которых ещё нет "
            "слоёв» из рецепта, заменяя их следующим:\n"
            f"— За ответ — ровно один неполный Device (нет слоя anode или cathode). "
            f"Не более {LOCAL_ENTITY_CAP} новых entities.\n"
            f"— {_REFERENCE_RULE}\n"
            f"— {_LABEL_RULE}\n"
            f"— {_LAYER_ROLE_RULE}"
        )
    return (
        "ОТМЕНЯЕТ лимит «20 entities» и правило «только устройства, у которых ещё нет "
        "слоёв» из рецепта, заменяя их следующим:\n"
        "— Извлеки все устройства и их полные стеки за этот ответ. Число entities "
        "не ограничивай.\n"
        f"— {_REFERENCE_RULE}\n"
        f"— {_LABEL_RULE}\n"
        f"— {_LAYER_ROLE_RULE}"
    )


def _node_visible(node: dict[str, Any], run_id: int | None) -> bool:
    status = str(node.get("status") or "")
    if status in {"accepted", "manual"}:
        return True
    if status == "proposed" and run_id is not None and node.get("run_id") == run_id:
        return True
    return False


def _edge_visible(edge: dict[str, Any], run_id: int | None) -> bool:
    status = str(edge.get("status") or "")
    if status in {"accepted", "manual"}:
        return True
    if status == "proposed" and run_id is not None and edge.get("run_id") == run_id:
        return True
    return False


def _layers_for_device(
    device: dict[str, Any],
    *,
    nodes_by_id: dict[Any, dict[str, Any]],
    all_nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    run_id: int | None,
) -> list[dict[str, Any]]:
    """Слои устройства: HAS_LAYER и Layer с label, содержащим имя Device."""
    device_id = device["id"]
    label = str(device.get("label") or "").strip().lower()
    found: dict[Any, dict[str, Any]] = {}
    for edge in edges:
        if str(edge.get("relation_type") or "") != "HAS_LAYER":
            continue
        if edge.get("source_node_id") != device_id:
            continue
        if not _edge_visible(edge, run_id):
            continue
        layer = nodes_by_id.get(edge.get("target_node_id"))
        if (
            layer
            and _node_visible(layer, run_id)
            and str(layer.get("entity_type") or "") == "Layer"
        ):
            found[layer["id"]] = layer
    if label:
        for node in all_nodes:
            if str(node.get("entity_type") or "") != "Layer":
                continue
            if not _node_visible(node, run_id):
                continue
            nlabel = str(node.get("label") or "").strip().lower()
            if label and label in nlabel:
                found[node["id"]] = node
    return list(found.values())


def _roles_from_layers(layers: list[dict[str, Any]]) -> set[str]:
    roles: set[str] = set()
    for layer in layers:
        attrs = layer.get("attributes") or {}
        role = str(attrs.get("role") or "").strip().lower()
        if role:
            roles.add(role)
    return roles


def audit_incomplete_device_stacks(
    graph: dict[str, Any],
    *,
    run_id: int | None = None,
) -> list[dict[str, Any]]:
    """Devices без anode или cathode (принятые / предложенные этим прогоном)."""
    nodes = [n for n in (graph.get("nodes") or []) if _node_visible(n, run_id)]
    edges = list(graph.get("edges") or [])
    nodes_by_id = {n["id"]: n for n in nodes}
    gaps: list[dict[str, Any]] = []
    for node in nodes:
        if str(node.get("entity_type") or "") != "Device":
            continue
        layers = _layers_for_device(
            node,
            nodes_by_id=nodes_by_id,
            all_nodes=nodes,
            edges=edges,
            run_id=run_id,
        )
        roles = _roles_from_layers(layers)
        missing = sorted(REQUIRED_LAYER_ROLES - roles)
        if not missing:
            continue
        gaps.append(
            {
                "device_id": node["id"],
                "label": str(node.get("label") or "").strip() or f"Device#{node['id']}",
                "layer_count": len(layers),
                "missing_roles": missing,
                "present_roles": sorted(roles),
            }
        )
    gaps.sort(key=lambda g: str(g.get("label") or ""))
    return gaps


def format_incomplete_stacks_summary(gaps: list[dict[str, Any]]) -> str:
    if not gaps:
        return ""
    parts: list[str] = []
    for gap in gaps:
        missing = gap.get("missing_roles") or []
        missing_ru = []
        for role in missing:
            if role == "anode":
                missing_ru.append("анода")
            elif role == "cathode":
                missing_ru.append("катода")
            else:
                missing_ru.append(role)
        miss_text = ", ".join(missing_ru) if missing_ru else "слоёв"
        parts.append(f"{gap.get('label')} (нет {miss_text})")
    return "неполный стек: " + "; ".join(parts)


def focus_incomplete_device_instruction(gap: dict[str, Any]) -> str:
    """Инструкция локального добора: одно устройство с дырами."""
    label = str(gap.get("label") or "Device").strip()
    missing = ", ".join(gap.get("missing_roles") or []) or "anode/cathode"
    present = ", ".join(gap.get("present_roles") or []) or "—"
    return (
        f"В этом проходе дозаполни только «{label}». "
        f"Сейчас есть роли: {present}; не хватает: {missing}. "
        f"Создай недостающие Layer/Material для полного стека. "
        f"Не более {LOCAL_ENTITY_CAP} новых entities. "
        f"{_REFERENCE_RULE}"
    )


def focus_incomplete_devices_instruction(gaps: list[dict[str, Any]]) -> str:
    """Инструкция облачного добора: перечисление дыр без лимита 20."""
    if not gaps:
        return ""
    labels = ", ".join(str(g.get("label") or "").strip() for g in gaps if g.get("label"))
    details = "; ".join(
        f"{g.get('label')} (нет {', '.join(g.get('missing_roles') or [])})" for g in gaps
    )
    return (
        f"Дозаполни неполные стеки: {labels}. "
        f"Детали: {details}. "
        "Число entities не ограничивай. "
        f"{_REFERENCE_RULE}"
    )
