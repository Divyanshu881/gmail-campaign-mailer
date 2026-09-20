"""Provider registry.

Add future providers by implementing EmailProvider and registering the class
here; campaign logic only ever calls get_provider().
"""

import logging
from typing import Type

from app.providers.base import EmailProvider, ProviderError  # noqa: F401 (re-export)

logger = logging.getLogger(__name__)

_PROVIDERS: dict[str, Type[EmailProvider]] = {}


def register(provider_cls: Type[EmailProvider]) -> Type[EmailProvider]:
    _PROVIDERS[provider_cls.provider_type] = provider_cls
    return provider_cls


def available_providers() -> list[str]:
    return sorted(_PROVIDERS)


def get_provider(provider_type: str) -> EmailProvider:
    """Return a provider instance, raising a clear error for unknown types."""
    if provider_type not in _PROVIDERS:
        raise ProviderError(
            f"Unknown email provider '{provider_type}'. "
            f"Available: {', '.join(available_providers()) or 'none'}."
        )
    return _PROVIDERS[provider_type]()


# Importing this module registers GmailProvider.
from app.providers.gmail import GmailProvider  # noqa: E402,F401