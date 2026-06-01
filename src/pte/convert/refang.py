import re

_DEFANG_DOT = re.compile(r'\[\.\]')
_DEFANG_HXX = re.compile(r'^hxxp', re.IGNORECASE)
_DEFANG_DOT_COM = re.compile(r'\[dot\]', re.IGNORECASE)

def refang(value: str) -> str:
    value = _DEFANG_DOT.sub(".", value)
    value = _DEFANG_DOT_COM.sub(".", value)
    value = _DEFANG_HXX.sub("http", value)
    return value
