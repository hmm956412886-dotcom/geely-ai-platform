"""HK CoreTest embedded Copilot integration."""

__all__ = ["CoreTestCopilot"]


def __getattr__(name: str):
    if name == "CoreTestCopilot":
        from .integration import CoreTestCopilot

        return CoreTestCopilot
    raise AttributeError(name)
