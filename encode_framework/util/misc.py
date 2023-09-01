import re

__all__: list[str] = [
    "markdownify"
]

def markdownify(string: str) -> str:
    """Markdownify a given string."""
    string = re.sub(r"\[bold\]([a-zA-Z0-9\.!?:\-]+)?\[\/\]", r"**\1**", str(string))
    string = re.sub(r"\[italics\]([a-zA-Z0-9\.!?:\-]+)?\[\/\]", r"_\1_", str(string))

    return string
