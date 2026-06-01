import re
from html.parser import HTMLParser
from pte.schema.models import SRO, ProvenanceRecord
from pte.convert.tier2_parsers.registry import register

_VALID_SCOPES = {"direct", "indirect", "suspected", "unknown"}


class _AssocTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._rows = []
        self._in_row = False
        self._cells = []
        self._current_cell = []
        self._header_row = True

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._in_row = True
            self._cells = []
        elif tag in ("td", "th") and self._in_row:
            self._current_cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self._cells.append(" ".join(self._current_cell).strip())
        elif tag == "tr" and self._in_row:
            if self._header_row:
                self._header_row = False
            elif len(self._cells) >= 4:
                self._rows.append(self._cells[:4])
            self._in_row = False

    def handle_data(self, data):
        if self._in_row:
            self._current_cell.append(data.strip())


@register("mandiant_actor_assoc")
def parse_mandiant_actor_assoc(html: str, entity_id: str, run_id: str) -> list[SRO]:
    parser = _AssocTableParser()
    parser.feed(html)
    sros = []
    for row in parser._rows:
        actor, rel_type, target, scope = row[0], row[1], row[2], row[3]
        scope = scope.lower().strip()
        if scope not in _VALID_SCOPES:
            scope = "unknown"
        sros.append(SRO(
            relationship_type=rel_type.strip(),
            source_ref=actor.strip(),
            target_ref=target.strip(),
            attribution_scope=scope,
            provenance=ProvenanceRecord(run_id=run_id, tier="DERIVED", skill_version="relationship_parse-v1"),
        ))
    return sros
