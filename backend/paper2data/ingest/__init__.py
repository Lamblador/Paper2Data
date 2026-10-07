"""Ingest PDF: секции, блоки, таблицы, подписи, DOI, ESI."""

__all__ = ["captions", "doi", "esi", "parser", "sections", "service"]


def __getattr__(name: str):
    if name in __all__:
        import importlib

        return importlib.import_module(f"paper2data.ingest.{name}")
    raise AttributeError(name)
