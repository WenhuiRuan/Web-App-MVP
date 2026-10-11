"""One shared, conservative surface sentence rule; never rewrite the utterance."""
import re

TERMINAL = re.compile(r'[。！？!?]+|(?<!\d)\.(?!\d)')
CLOSERS = '”’"\'」』）)] '
ABBREVIATIONS = re.compile(r'(?<![A-Za-z])(?:e\.g\.|i\.e\.|U\.S\.|U\.K\.|Dr\.|Mr\.|Mrs\.|Ms\.)(?![A-Za-z])', re.I)


def sentence_count(text):
    # Mask only punctuation classification; original text is never changed or truncated.
    protected = {i for match in ABBREVIATIONS.finditer(text) for i in range(*match.span())}
    for pattern in ('“([^“”]*)”', '‘([^‘’]*)’', '"([^"\\n]*)"', '「([^「」]*)」'):
        for quote in re.finditer(pattern, text):
            inner = list(TERMINAL.finditer(quote.group(1)))
            # An embedded single quoted question is an object of the outer sentence.
            # Multiple quoted sentences and standalone quoted speech remain counted.
            if len(inner) == 1 and text[quote.end():].strip(CLOSERS+'。！？!?'):
                protected.update(range(quote.start(1)+inner[0].start(), quote.start(1)+inner[0].end()))
    boundaries = [m for m in TERMINAL.finditer(text) if not all(i in protected for i in range(*m.span()))]
    count=0;start=0
    for boundary in boundaries:
        if text[start:boundary.start()].strip(CLOSERS+'\n\t'): count+=1
        start=boundary.end()
    if text[start:].strip(CLOSERS+'\n\t'): count+=1
    return count
