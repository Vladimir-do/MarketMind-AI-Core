import re


SCRIPT_STYLE_RE = re.compile(r"\s+")
INLINE_SPACE_RE = re.compile(r"[ \t\r\f\v]+")
NEWLINE_RE = re.compile(r"\n+")


def clean_text(text: str, *, preserve_newlines: bool = False) -> str:
    if preserve_newlines:
        text = INLINE_SPACE_RE.sub(" ", text)
        text = NEWLINE_RE.sub("\n", text)
        return "\n".join(line.strip() for line in text.splitlines() if line.strip())
    return SCRIPT_STYLE_RE.sub(" ", text).strip()
