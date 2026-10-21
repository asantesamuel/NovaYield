"""Central Beanie document registry with feature-module auto-discovery."""

from importlib import import_module
from pkgutil import iter_modules
from typing import TypeVar

from beanie import Document

DocumentType = TypeVar("DocumentType", bound=Document)

_registered_document_models: dict[str, type[Document]] = {}


def register_document_model(model: type[DocumentType]) -> type[DocumentType]:
    """Register a feature-owned Beanie document without editing shared bootstrap code."""

    if not issubclass(model, Document):
        raise TypeError("Registered models must inherit from Beanie Document")
    model_key = f"{model.__module__}.{model.__qualname__}"
    _registered_document_models[model_key] = model
    return model


def load_document_models() -> tuple[type[Document], ...]:
    """Import app.models feature modules and return their registered document classes.

    A feature adds a module such as ``app.models.farms`` and decorates each
    Beanie document with ``@register_document_model``. Importing the module
    here collects it before Beanie initializes collections and indexes.
    """

    models_package = import_module("app.models")
    for module_info in iter_modules(models_package.__path__):
        if module_info.name.startswith("_"):
            continue
        import_module(f"{models_package.__name__}.{module_info.name}")

    return tuple(_registered_document_models[key] for key in sorted(_registered_document_models))
