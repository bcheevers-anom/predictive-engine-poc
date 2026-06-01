import re
from html.parser import HTMLParser
from pte.convert.refang import refang
from pte.convert.tier2_parsers.registry import register

_DATE_RE = re.compile(r'\d{4}-\d{2}-\d{2}')
_TTP_RE = re.compile(r'T\d{4}(?:\.\d{3})?')
_IOC_IP = re.compile(r'\b(?:\d{1,3}[\.\[\]]{1,3}){3}\d{1,3}\b')


class _TimelineHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.events = []
        self._in_event = False
        self._current_text = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "div" and "event" in attrs_dict.get("class", ""):
            self._in_event = True
            self._current_text = []

    def handle_endtag(self, tag):
        if tag == "div" and self._in_event:
            text = " ".join(self._current_text)
            dates = _DATE_RE.findall(text)
            ttps = _TTP_RE.findall(text)
            iocs_raw = _IOC_IP.findall(text)
            iocs = [refang(i) for i in iocs_raw]
            self.events.append({
                "event_date": dates[0] if dates else None,
                "techniques": ttps,
                "ioc": iocs[0] if iocs else None,
                "raw_text": text[:500],
            })
            self._in_event = False

    def handle_data(self, data):
        if self._in_event:
            self._current_text.append(data.strip())


@register("gti_campaign_timeline")
def parse_gti_campaign_timeline(html: str, entity_id: str, run_id: str) -> list[dict]:
    parser = _TimelineHTMLParser()
    parser.feed(html)
    for event in parser.events:
        event["entity_id"] = entity_id
        event["run_id"] = run_id
        event["tier"] = "DERIVED"
    return parser.events
