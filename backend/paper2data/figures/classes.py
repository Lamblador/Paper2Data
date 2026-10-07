"""Базовые классы рисунков (seed) и создание пользовательских."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from paper2data.db.models import FigureClass


@dataclass(frozen=True)
class BuiltinClassDef:
    slug: str
    name: str
    description: str = ""


# Порядок и набор из плана архитектуры (M5).
BUILTIN_FIGURE_CLASSES: tuple[BuiltinClassDef, ...] = (
    BuiltinClassDef("data_figure", "Данный рисунок", "Общий научный график / data figure"),
    BuiltinClassDef("illustration", "Иллюстрация", "Схема-иллюстрация без спектральных данных"),
    BuiltinClassDef("table", "Таблица", "Таблица, сохранённая как изображение"),
    BuiltinClassDef("structural_formula", "Структурная формула", "Химическая структура / OCSR-кандидат"),
    BuiltinClassDef("reaction_scheme", "Схема реакции", "Реакционная схема"),
    BuiltinClassDef("emission_spectrum", "Спектр эмиссии", "Emission / PL spectrum"),
    BuiltinClassDef("excitation_spectrum", "Спектр возбуждения", "Excitation spectrum"),
    BuiltinClassDef("absorption_spectrum", "Спектр поглощения", "Absorption / UV-Vis"),
    BuiltinClassDef("decay_curve", "Кривая затухания", "Lifetime / fluorescence decay"),
    BuiltinClassDef("xrd_pattern", "Дифрактограмма XRD", "Powder / single-crystal XRD"),
    BuiltinClassDef("tga_dsc", "TGA / DSC", "Термический анализ"),
    BuiltinClassDef("cv_curve", "Циклическая вольтамперометрия", "CV curve"),
    BuiltinClassDef("microscopy", "Микроскопия", "SEM / TEM / AFM / оптика"),
    BuiltinClassDef("crystal_structure", "Кристаллическая структура", "Packing / ORTEP"),
    BuiltinClassDef("energy_diagram", "Энергетическая диаграмма", "Jablonski / уровни"),
    BuiltinClassDef("device_architecture", "Архитектура устройства", "OLED / device stack"),
    BuiltinClassDef("eqe_jv_curve", "EQE / J–V", "Квантовая эффективность / вольт-амперная"),
)


def seed_builtin_classes(session: Session) -> list[FigureClass]:
    """Идемпотентно создать базовые классы, если их ещё нет."""
    existing = {
        c.slug: c for c in session.scalars(select(FigureClass)).all()
    }
    created: list[FigureClass] = []
    for item in BUILTIN_FIGURE_CLASSES:
        if item.slug in existing:
            continue
        row = FigureClass(
            slug=item.slug,
            name=item.name,
            description=item.description,
            is_builtin=True,
        )
        session.add(row)
        created.append(row)
    if created:
        session.flush()
    return list(session.scalars(select(FigureClass).order_by(FigureClass.id)).all())


def create_user_class(
    session: Session,
    *,
    slug: str,
    name: str,
    description: str = "",
) -> FigureClass:
    slug_clean = _normalize_slug(slug)
    if not slug_clean:
        raise ValueError("Пустой идентификатор класса")
    existing = session.scalar(select(FigureClass).where(FigureClass.slug == slug_clean))
    if existing is not None:
        raise ValueError(f"Класс уже существует: {slug_clean}")
    row = FigureClass(
        slug=slug_clean,
        name=(name or slug_clean).strip(),
        description=(description or "").strip(),
        is_builtin=False,
    )
    session.add(row)
    session.flush()
    return row


def _normalize_slug(raw: str) -> str:
    text = (raw or "").strip().lower().replace(" ", "_")
    allowed = []
    for ch in text:
        if ch.isalnum() or ch in "_-":
            allowed.append(ch)
    return "".join(allowed).strip("_-")
