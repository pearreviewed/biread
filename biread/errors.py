"""Every failure the pipeline raises on purpose.

Library modules raise these; only the CLI decides what to print and which exit
code to use. Nothing below `cli.py` calls `sys.exit` or `input`.
"""


class BireadError(Exception):
    """Base class for expected, user-actionable failures."""


class ConfigError(BireadError):
    pass


class ExtractError(BireadError):
    pass


class CacheError(BireadError):
    pass


class CacheSchemaError(CacheError):
    """On-disk cache was written by an incompatible version of the code."""

    def __init__(self, path, found, expected):
        super().__init__(
            f"cache at {path} has schema version {found!r}, but this code expects {expected}"
        )
        self.path = path


class TranslationError(BireadError):
    pass


class GlossError(BireadError):
    pass


class AlignmentError(BireadError):
    pass
