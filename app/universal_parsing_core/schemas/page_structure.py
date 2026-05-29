from enum import StrEnum


class PageStructure(StrEnum):
    UNKNOWN = "unknown"
    UNKNOWN_JS = "unknown_js"
    SINGLE = "single"
    CATALOG = "catalog"
    MIXED = "mixed"
    ARTICLE = "article"
    EMPTY = "empty"
