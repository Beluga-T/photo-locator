"""Read a JSON object while it is still being written.

The model streams its answer token by token, and RESULT_SCHEMA is ordered so the
cheap, coarse fields land first — precision, then country, region, city, locality,
then the coordinates — long before the evidence array that dominates the byte
count. Waiting for the closing brace throws that head start away; this module
hands each top-level field to the caller the moment its value is provably closed,
so the country can be painted, then the map, while the model is still writing.
(`precision` leads deliberately: it is the cap on how fine an answer the model
will stand behind, and knowing it first is what stops the page from painting a
street name it is about to have to walk back.)

Every intermediate state of the input is invalid JSON by definition, so nothing
here may assume the document parses. The scanner tracks strings, escapes and
container depth itself, one character at a time, over a cursor that never rewinds,
and calls `json.loads` only on a slice it has already proved complete — so the
values handed back are real Python types, not hand-rolled ones.

Malformed input degrades to silence, never to an exception: a caller in the middle
of a stream has nothing useful to do with a traceback, and it still holds the whole
text to parse once the stream ends. Degrading is also kept as local as it can be —
one value that will not parse costs that one field, and a '{' that turns out to
have been prose costs only the seek that latched onto it.

What `feed` returns
-------------------
A list of `Report`s, in the order the reader proved them complete. A `Report` IS
the `(field, value)` pair this module has always returned — it unpacks, compares
and `dict()`s exactly like that two-tuple — carrying two extra attributes:

    report.field    the top-level key
    report.value    the parsed value
    report.index    None for a whole field; N for element N of an array field
    report.restart  True only on the one synthetic report described under
                    "Applying the reports" below; False on everything the model
                    actually wrote

Element reports appear only for arrays whose key was named up front, and only for
those at the top level:

    reader = PartialJSON(arrays=("evidence", "alternatives"))
    for report in reader.feed(chunk):
        if report.index is None:
            ...  # the whole of report.field
        else:
            ...  # element report.index of the array report.field

That matters because the fields worth painting are cheap and land early, while
`evidence` is most of the document: on a measured 29s call the screen went still
at 8.5s and stayed still for 20.6s, all of it spent writing an array the reader
could only hand over at the very end. Element N is reported the moment element N
closes, so a six-entry array paints six times, the first of them ~14s earlier.

When the array itself finally closes it is ALSO reported as an ordinary
whole-field report with `index is None`, holding every element over again. That
is deliberate: whether the caller has already painted those elements and should
drop the repeat is a decision for the layer that knows the wire format, not for
the scanner.

Applying the reports
--------------------
Two rules, applied in the order the reports arrive, and they are the whole of it:

    index is None   →  state[field] = value               replace outright
    index is N      →  state[field][N] = value            assign that position,
                       on an empty list if the field is not held yet, padding
                       with None if N is past the end

The padding is not pedantry. Indices are array positions, not a count of what was
emitted, so an element that could not be parsed leaves a hole rather than shifting
its neighbours down: `{"evidence": [1, NaN, 3]}` reports index 0 and index 2, and
a caller that took the rule literally would raise IndexError on the second.

Follow both and the state left at the end of a complete document is exactly what
`json.loads` returns for the same text. (The one deliberate divergence is the one
this module already documents: a value holding NaN or Infinity is dropped rather
than reported, because it cannot survive the wire.)

A repeated key is where that needs help. The whole-field path corrects itself for
free — the second value replaces the first, positions and all — but the element
path can only overwrite the positions the second array actually reaches, so on
`{"evidence": [a, b, c], "evidence": [x]}` re-emitting index 0 would leave the
caller still holding b and c at 1 and 2: rows `json.loads` on the finished text
says do not exist. So when a key that has already been reported opens another
array whose elements are being streamed, the reader first reports that field
whole as `[]` — "discard what you hold for this field, it is being written
again" — and only then starts the count at 0 again. Rule one absorbs that with no
extra client logic, and it lands the moment the '[' arrives, so a stream cut off
part-way through the second array is left short rather than wrong.

Those resets are the one whole-field report a caller must not suppress. They
carry `report.restart is True`, so a layer that drops the whole-array repeat
because it has already painted the elements can tell them apart; drop them too
and the stale rows come straight back.

A caller that also de-duplicates by slot — "I already sent this exact value for
this (field, index), do not send it again" — has a second thing to do on a
restart: forget every remembered slot for that field. Otherwise the reset clears
the far end's rows while the near end still remembers the abandoned array's
values, and any element of the replacement that happens to match is suppressed.
The result is a row the model really wrote going missing, which is worse than the
stale row the reset was there to remove. `app/providers.py` does both.

`index` deliberately sits outside the tuple identity — `Report("evidence", e, 0)`
compares equal to `("evidence", e)`, and to any Report with the same field and
value whatever its index — because that is what lets every existing caller and
test keep working untouched. Compare `.index` explicitly when position matters.
Copies and pickles of a Report do carry both attributes; see `Report`.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any

# Scanner states. The cursor never rewinds, so this plus a handful of indices is
# everything needed to resume mid-key, mid-string, mid-number or mid-escape.
_SEEK = "seek"  # before the first top-level '{' — ```json fences, stray newlines
_KEY_OR_END = "key-or-end"  # after '{' or ',': a key, or the end of the object
_KEY = "key"  # inside the key string
_COLON = "colon"  # between a key and its value
_VALUE = "value"  # at the first character of a value
_STRING = "string"  # inside a top-level string value
_BARE = "bare"  # number / true / false / null — no closing token of its own
_NESTED = "nested"  # inside an object or array value, tracked by depth
_NEXT = "next"  # after a value: ',' or '}'
_DONE = "done"
_BROKEN = "broken"

# What kind of array element is currently open, which decides what closes it.
_EL_STRING = "el-string"  # closed by its own unescaped quote
_EL_CONTAINER = "el-container"  # closed by the brace/bracket that matches its own
_EL_BARE = "el-bare"  # number / true / false / null — closed by a delimiter


def _continues_bare(ch: str) -> bool:
    """True while `ch` can still be part of a number or of true/false/null.

    Numbers and bare words are the only values with no closing token: they end at
    the first character that cannot continue them, which is why they can never be
    reported at the end of the buffer — `95` may yet become `951`.
    """
    return ch.isalnum() or ch in "+-."


def _reject_constant(name: str) -> Any:
    """Refuse NaN / Infinity / -Infinity, which `json.loads` accepts by default.

    `coordinates` goes straight into an SSE frame, and a bare NaN in the JSON body
    makes `JSON.parse` throw in the browser — that loses the whole event, not just
    the one number. Rejecting it here makes the value merely unparseable, which
    this module already knows how to do quietly.
    """
    raise ValueError(f"{name} is not valid JSON")


class Report(tuple):
    """One proved-complete thing: `(field, value)`, plus where it sat in an array.

    A tuple subclass with exactly two members, never three, because `feed` has
    returned `(field, value)` pairs since this module existed and callers unpack
    them, compare them against literals and `dict()` the list. `index` rides
    alongside as an attribute, so gaining it cannot change any of that — the one
    shape that adds the new information without a flag day in `providers.py`.

    Shadowing `tuple.index` (the method that searches for a member) is the price;
    `collections.namedtuple` allows exactly the same shadowing for exactly the
    same reason, and nothing here ever searches a two-member tuple.

    `restart` marks the synthetic `(field, [])` report that precedes a repeated
    array — see "Applying the reports" in the module docstring. It is False on
    every report of something the model wrote.
    """

    # No __slots__: tuple is variable-length, so a non-empty one is rejected and
    # an empty one would take away the __dict__ these live in.
    index: int | None
    restart: bool

    def __new__(
        cls, field: str, value: Any, index: int | None = None, restart: bool = False
    ) -> Report:
        self = super().__new__(cls, (field, value))
        self.index = index
        self.restart = restart
        return self

    def __getnewargs__(self) -> tuple[str, Any, int | None, bool]:
        """The arguments `__new__` wants, which is not what a tuple's would be.

        `tuple.__getnewargs__` hands back the whole tuple as ONE argument —
        `(('evidence', {...}),)` — and every generic copier goes through it:
        `copy.copy`, `copy.deepcopy` (of a report or of a list of them) and
        pickle at protocol 2 and up all called `Report.__new__(cls, the_pair)`
        and raised `TypeError: missing 1 required positional argument: 'value'`,
        on a class whose whole point is to be a drop-in for the plain two-tuple
        that copied and pickled fine. Spelling out the real signature fixes all
        of them at once, and rebuilds `index` and `restart` in the `__new__` call
        rather than leaving them to the `__dict__` that arrives afterwards — so
        the round trip holds even for a copier that carries no instance state.
        """
        return (self[0], self[1], self.index, self.restart)

    @property
    def field(self) -> str:
        """The top-level key this report is about."""
        return self[0]

    @property
    def value(self) -> Any:
        """The parsed value: the whole field, or one element of it."""
        return self[1]

    def __repr__(self) -> str:
        extra = ""
        if self.index is not None:
            extra += f", index={self.index}"
        if self.restart:
            extra += ", restart=True"
        return f"Report({self[0]!r}, {self[1]!r}{extra})"


class PartialJSON:
    """Incremental reader for one top-level JSON object arriving in pieces."""

    def __init__(self, arrays: Iterable[str] = ()) -> None:
        # Chunks are kept apart and joined only when `text` asks for them:
        # `self._buf += chunk` on an attribute gets none of CPython's in-place
        # concat optimisation, so it re-copies the whole document per chunk.
        self._parts: list[str] = []
        self._state = _SEEK
        self._tok: int | None = None  # start of the open token in the current chunk
        self._tokbuf: list[str] = []  # that token's text from earlier chunks
        self._key = ""  # key whose value is currently being scanned
        self._esc = False  # the previous character was a backslash
        self._depth = 0  # container depth inside a nested value
        self._instr = False  # inside a string inside a nested value
        self._after_comma = False  # the '{' we are inside was followed by a field

        # Element reporting, off unless a caller names the arrays it wants it for.
        # A bare string is the easy mistake — frozenset("evidence") is a set of
        # eight letters, and would then match no key at all, silently.
        self._arrays = frozenset([arrays] if isinstance(arrays, str) else arrays)
        self._arr = False  # the value being scanned is one of those arrays
        self._elidx = 0  # position in it of the element being scanned
        self._elkind: str | None = None  # what kind of element that is, if any
        self._eltok: int | None = None  # its start in the current chunk
        self._elbuf: list[str] = []  # its text from earlier chunks
        # Keys the caller has been told something about. Only a repeat needs the
        # reset report, so the set holds one entry per distinct top-level key.
        self._reported: set[str] = set()

    # ------------------------------------------------------------------ public

    def feed(self, chunk: str) -> list[Report]:
        """Append `chunk`; return what it completed, in order.

        Every report is a `(field, value)` pair; those for an element of a named
        array also carry `.index`. See the module docstring for the full shape.
        """
        if not isinstance(chunk, str):
            # bytes from an SDK that forgot to decode, or a None at end of stream.
            # A caller bug, but raising is the worse failure: providers.py reads a
            # TypeError out of feed() as "the model rejected the request" and
            # silently downgrades the entire call to non-streaming.
            return []
        if not chunk:
            return []
        self._parts.append(chunk)
        if self._state in (_DONE, _BROKEN):
            return []
        out: list[Report] = []
        try:
            self._scan(out, chunk)
        except Exception:
            # Belt and braces around the explicit degradations below: whatever
            # went wrong, the contract is that feed() does not raise.
            self._state = _BROKEN
        return out

    @property
    def text(self) -> str:
        """Everything fed so far, untouched — the caller's fallback at end of stream.

        The join happens here rather than in `feed`, and collapses the parts so a
        second read is free; the caller normally wants this exactly once.
        """
        if len(self._parts) != 1:
            self._parts = ["".join(self._parts)]
        return self._parts[0]

    @property
    def done(self) -> bool:
        """True once the top-level object has closed."""
        return self._state == _DONE

    @property
    def broken(self) -> bool:
        """True once the reader has given up — nothing further will be reported.

        Lets a caller tell "still streaming, nothing yet" from "stopped looking",
        which otherwise look identical from outside: both are `not done`.
        """
        return self._state == _BROKEN

    # ----------------------------------------------------------------- scanner

    def _open(self, i: int) -> None:
        """Start a token at `i` in the current chunk."""
        self._tok = i
        self._tokbuf.clear()

    def _take(self, buf: str, i: int) -> str:
        """The open token up to `i`, rejoined across however many chunks it spans."""
        tail = buf[self._tok : i]
        raw = "".join((*self._tokbuf, tail)) if self._tokbuf else tail
        self._tokbuf.clear()
        self._tok = None
        return raw

    def _emit(self, out: list[Report], raw: str) -> None:
        """Parse one proved-complete slice and hand it over — or drop it, quietly.

        `strict=False` stops a literal control character inside a string from
        costing every field after it, and `parse_constant` refuses the NaN and
        Infinity that `json.loads` would otherwise invent. Anything still
        unparseable is one dead field, not a dead reader: the scanner has proved
        where the value ends, so it can carry straight on with the next one.

        A key completing twice is two events, not one: `{"a": 1, "a": 2}` parses as
        `a=2`, so suppressing the second would leave the UI showing a value the
        caller's end-of-stream `json.loads` contradicts. Each COMPLETED value is
        still reported exactly once — the cursor never rewinds — so a later
        duplicate arrives as a correction.
        """
        try:
            value = json.loads(raw, strict=False, parse_constant=_reject_constant)
        except ValueError:
            return
        self._reported.add(self._key)
        out.append(Report(self._key, value))

    # ------------------------------------------------------------- array elements

    def _open_el(self, i: int, kind: str) -> None:
        """Start an element of the current array at `i` in the current chunk."""
        self._eltok = i
        self._elbuf.clear()
        self._elkind = kind

    def _take_el(self, buf: str, i: int) -> str:
        """The open element up to `i`, rejoined across however many chunks it spans."""
        tail = buf[self._eltok : i]
        raw = "".join((*self._elbuf, tail)) if self._elbuf else tail
        self._elbuf.clear()
        self._eltok = None
        self._elkind = None
        return raw

    def _emit_el(self, out: list[Report], raw: str) -> None:
        """Hand over one proved-complete element — or drop it, quietly, like a field.

        The index counts positions in the array rather than successful parses, so
        it keeps meaning what the caller thinks it means: element 3 is still
        element 3 after element 2 turned out to hold a NaN and went nowhere. That
        is also why it advances before the parse can bail out.
        """
        index = self._elidx
        self._elidx += 1
        try:
            value = json.loads(raw, strict=False, parse_constant=_reject_constant)
        except ValueError:
            return
        self._reported.add(self._key)
        out.append(Report(self._key, value, index))

    def _forget_el(self) -> None:
        """Stop tracking elements — the array closed, or we never wanted one."""
        self._arr = False
        self._elkind = None
        self._eltok = None
        self._elbuf.clear()
        self._elidx = 0

    def _scan(self, out: list[Report], buf: str) -> None:
        n = len(buf)
        i = 0  # every chunk is new text, so the cursor restarts inside it
        # One character per iteration, resuming the state the last chunk left off
        # in, so the total work over a stream is linear in the document rather
        # than quadratic in the number of chunks.
        while i < n:
            ch = buf[i]
            state = self._state

            if state == _SEEK:
                # Ignore anything before the object: a fence, a stray newline, prose.
                i += 1
                if ch == "{":
                    self._state = _KEY_OR_END
                    self._after_comma = False

            elif state == _KEY_OR_END:
                if ch == '"':
                    self._open(i)
                    self._esc = False
                    i += 1
                    self._state = _KEY
                elif ch == "}":
                    if self._after_comma:
                        # `{"a": 1,}`. The caller's end-of-stream `json.loads` on
                        # the same text raises, so calling this done would hand the
                        # UI a result the authoritative parse then contradicts.
                        self._state = _BROKEN
                        return
                    i += 1
                    self._state = _DONE
                    return
                elif ch.isspace():
                    i += 1
                else:
                    # Prose where a key should be: the seek latched onto a '{' in
                    # the preamble — `Here is the JSON {country, region, city}:`.
                    # Go back to seeking rather than lose the document over it.
                    # Deliberately no advance: _SEEK re-reads this character, so a
                    # '{' here latches straight onto the object it opens.
                    self._state = _SEEK

            elif state == _KEY:
                i += 1
                if self._esc:
                    self._esc = False
                elif ch == "\\":
                    self._esc = True  # may be the last character of this chunk
                elif ch == '"':
                    self._key = json.loads(self._take(buf, i), strict=False)
                    self._state = _COLON

            elif state == _COLON:
                if ch == ":":
                    i += 1
                    self._state = _VALUE
                elif ch.isspace():
                    i += 1
                else:
                    self._state = _BROKEN
                    return

            elif state == _VALUE:
                if ch.isspace():
                    i += 1
                    continue
                self._open(i)
                if ch == '"':
                    self._esc = False
                    i += 1
                    self._state = _STRING
                elif ch in "{[":
                    self._depth = 1
                    self._instr = False
                    self._esc = False
                    # The one place element reporting can be switched on, and by
                    # construction the top level: _NESTED never returns here, so
                    # an "evidence" key inside another value cannot reach this.
                    self._forget_el()
                    self._arr = ch == "[" and self._key in self._arrays
                    if self._arr and self._key in self._reported:
                        # A repeated key, and the caller is holding elements of
                        # the array this one replaces. The element path can only
                        # overwrite the positions THIS array reaches, so without
                        # a reset the tail of the old one survives into a state
                        # `json.loads` never had. Emitted at the '[', before any
                        # element of the new array, so even a stream that stops
                        # part-way through it leaves the caller short, not wrong.
                        out.append(Report(self._key, [], None, True))
                    i += 1
                    self._state = _NESTED
                else:
                    # Deliberately no advance: _BARE re-reads this character, so a
                    # one-character value like `0` is handled by the same code path.
                    self._state = _BARE

            elif state == _STRING:
                # Braces, brackets, colons and commas in here are just text.
                i += 1
                if self._esc:
                    self._esc = False
                elif ch == "\\":
                    self._esc = True
                elif ch == '"':
                    self._emit(out, self._take(buf, i))
                    self._state = _NEXT

            elif state == _BARE:
                if _continues_bare(ch):
                    i += 1
                    continue
                if i == self._tok and not self._tokbuf:  # a value starting ',' or ']'
                    self._state = _BROKEN
                    return
                # The delimiter proves the token ended; leave it for _NEXT to read.
                self._emit(out, self._take(buf, i))
                self._state = _NEXT

            elif state == _NESTED:
                # True only at the array's own level: not inside one of its
                # strings, not inside one of its elements. Element boundaries
                # exist nowhere else, which is what stops an array inside an
                # evidence entry from reporting entries of its own.
                at_top = self._arr and not self._instr and self._depth == 1
                if at_top and self._elkind == _EL_BARE and not _continues_bare(ch):
                    # Same discipline as _BARE at the top level: a number ends at
                    # the first character that cannot continue it — the ',' or the
                    # array's ']' — never at the end of the buffer, where 5 may
                    # still become 55. That character still has its own job below.
                    self._emit_el(out, self._take_el(buf, i))
                i += 1
                if self._instr:
                    if self._esc:
                        self._esc = False
                    elif ch == "\\":
                        self._esc = True
                    elif ch == '"':
                        self._instr = False
                        if self._arr and self._depth == 1 and self._elkind == _EL_STRING:
                            self._emit_el(out, self._take_el(buf, i))
                elif ch == '"':
                    self._instr = True
                    self._esc = False
                    if at_top and self._elkind is None:
                        self._open_el(i - 1, _EL_STRING)
                elif ch in "{[":
                    if at_top and self._elkind is None:
                        self._open_el(i - 1, _EL_CONTAINER)
                    self._depth += 1
                elif ch in "}]":
                    self._depth -= 1
                    if self._depth == 0:  # only the outermost close finishes the field
                        self._emit(out, self._take(buf, i))
                        self._state = _NEXT
                        self._forget_el()
                    elif self._arr and self._depth == 1 and self._elkind == _EL_CONTAINER:
                        # Back down to the array's own level: this element closed.
                        self._emit_el(out, self._take_el(buf, i))
                elif at_top and self._elkind is None and not (ch.isspace() or ch == ","):
                    # Anything else here starts a bare element — including junk,
                    # which costs that one element when it fails to parse.
                    self._open_el(i - 1, _EL_BARE)

            elif state == _NEXT:
                if ch == ",":
                    i += 1
                    self._state = _KEY_OR_END
                    self._after_comma = True
                elif ch == "}":
                    i += 1
                    self._state = _DONE
                    return
                elif ch.isspace():
                    i += 1
                else:
                    self._state = _BROKEN
                    return

            else:  # _DONE / _BROKEN — nothing after the object interests us
                return

        # Running out of chunk is the normal case: whatever state we are in is
        # resumed verbatim by the next chunk. A token still open spans into that
        # chunk, so keep what has been scanned of it and restart its index at 0.
        if self._tok is not None:
            self._tokbuf.append(buf[self._tok :])
            self._tok = 0
        if self._eltok is not None:  # an element token spans chunks the same way
            self._elbuf.append(buf[self._eltok :])
            self._eltok = 0


def iter_fields(chunks: Iterable[str], arrays: Iterable[str] = ()) -> Iterator[Report]:
    """Yield a `Report` for each thing `chunks` completes, as it completes it.

    `arrays` names the top-level arrays whose elements are reported one by one,
    exactly as for `PartialJSON`; with none named this yields whole fields only.
    """
    parser = PartialJSON(arrays)
    for chunk in chunks:
        yield from parser.feed(chunk)


# --------------------------------------------------------------------- self-check

if __name__ == "__main__":
    import random
    import sys
    import time
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.prompt import RESULT_SCHEMA

    checks = 0

    def ok(label: str, detail: str = "") -> None:
        global checks
        checks += 1
        print(f"  ok  {label}{'  — ' + detail if detail else ''}")

    def collect(*chunks: str) -> list[tuple[str, Any]]:
        return list(iter_fields(chunks))

    # A realistic answer in RESULT_SCHEMA's own property order, loaded with the
    # things that break naive depth counting: braces, brackets, commas and colons
    # inside strings, an escaped quote, and a value ending in a backslash.
    ANSWER = {
        "country": {"name_zh": "日本", "name_en": "Japan"},
        "region": {"name_zh": "京都府", "name_en": "Kyoto Prefecture"},
        "city": {"name_zh": "京都市", "name_en": "Kyoto"},
        "locality": "祇园 花见小路",
        "precision": "locality",
        "coordinates": {"lat": 35.0037, "lon": 135.7752, "radius_km": 2},
        "confidence": 88,
        "confidence_band": "high",
        "summary": '路牌 {花见小路通} 与灯笼上的 [祇园] 二字: 同行者说 "就是这里", 因此定到街区。',
        "evidence": [
            {
                "category": "文字与标识",
                "observation": "木牌写着「花見小路通」, 下方有 [南行き] 箭头",
                "implication": "日语汉字加假名, 且是京都特有的街道名",
                "weight": "high",
            },
            {
                "category": "建筑风格",
                "observation": "两侧町屋: 格子窗、虫笼窗、深色木格栅",
                "implication": "京都祇园保存区的典型町屋形制",
                "weight": "high",
            },
            {
                "category": "道路与交通",
                "observation": "石板路面, 无路缘石, 车辆靠左",
                "implication": "日本靠左行驶, 且是限速的历史街区",
                "weight": "medium",
            },
            {
                "category": "人文与服饰",
                "observation": "游客着租赁和服, 店招标价含 ¥ 符号",
                "implication": "日元区, 观光型历史街区",
                "weight": "low",
            },
        ],
        "alternatives": [
            {
                "country": "日本",
                "region": "石川县",
                "city": "金泽市",
                "likelihood": 8,
                "reason": "东茶屋街的町屋极为相似, 但石板与坡度对不上",
            },
            {
                "country": "日本",
                "region": "岐阜县",
                "city": "高山市",
                "likelihood": 4,
                "reason": "老街同样保留格子窗, 但街道更宽且无花街灯笼",
            },
        ],
        "notes": '原图路径 D:\\相册\\ 未附 EXIF; 判断全部来自画面。',
    }
    DOC = json.dumps(ANSWER, ensure_ascii=False)
    ORDER = list(RESULT_SCHEMA["required"])

    print(f"self-check: {len(DOC)} chars, {len(ORDER)} top-level fields\n")

    # 1 ── the real schema shape, fed three different ways
    whole = collect(DOC)
    assert [k for k, _ in whole] == ORDER, [k for k, _ in whole]
    assert dict(whole) == ANSWER
    ok("whole document", " → ".join(k for k, _ in whole))

    single = collect(*DOC)
    assert single == whole, "one character at a time diverged"
    ok("one character at a time", f"{len(DOC)} feeds, identical sequence")

    rng = random.Random(20260807)
    widest = 0
    for _ in range(300):
        ragged, pos = [], 0
        while pos < len(DOC):
            step = rng.choice([1, 1, 1, 2, 3, 4, 5, 8, 13, 40, 200])
            ragged.append(DOC[pos : pos + step])
            pos += step
        assert collect(*ragged) == whole, f"ragged chunking diverged: {ragged[:3]}"
        widest = max(widest, len(ragged))
    ok("ragged chunks", f"300 random chunkings (up to {widest} chunks), all identical")

    # Values are real Python types, not text.
    got = dict(whole)
    assert isinstance(got["coordinates"], dict) and got["coordinates"]["lat"] == 35.0037
    assert isinstance(got["confidence"], int) and got["confidence"] == 88
    assert isinstance(got["evidence"], list) and len(got["evidence"]) == 4
    ok("parsed types", "coordinates=dict, confidence=int, evidence=list[4]")

    # 2 ── structural characters inside strings
    s = collect('{"summary": "他在 {城市} 里, 见到 [路牌]: 「A:B」", "notes": ""}')
    assert s == [("summary", "他在 {城市} 里, 见到 [路牌]: 「A:B」"), ("notes", "")], s
    ok("braces/brackets/commas inside a string", repr(s[0][1]))

    # 3 ── escapes
    e = collect(r'{"a": "x\\", "b": "y\"z", "c": "\u4eac\u90fd", "d": "line\nbreak"}')
    assert e == [("a", "x\\"), ("b", 'y"z'), ("c", "京都"), ("d", "line\nbreak")], e
    ok("escapes", "trailing backslash, escaped quote, \\u, \\n")

    p = PartialJSON()
    assert p.feed('{"a": "x\\') == []  # chunk boundary between \ and the char it escapes
    assert p.feed('"') == []  # this quote is escaped, so the string is NOT closed
    assert p.feed('y"') == [("a", 'x"y')], "escape did not survive the chunk boundary"
    ok("escape split across a chunk boundary", 'x\\ + " + y" → x"y')

    p = PartialJSON()  # a surrogate pair split down the middle
    assert p.feed('{"a": "\\ud83d') == []
    assert p.feed('\\ude00"}') == [("a", "\U0001f600")]
    ok("surrogate pair split across chunks", r"\ud83d + \ude00 → 😀")

    # 4 ── a number has no closing token
    p = PartialJSON()
    assert p.feed('{"confidence": 95') == [], "reported a number that could still grow"
    assert p.feed("1") == []
    assert p.feed("}") == [("confidence", 951)]
    assert p.done
    ok("number at end of buffer", "95 → 951 only reported at the delimiter")

    p = PartialJSON()
    assert p.feed('{"confidence": 88 ') == [("confidence", 88)]  # whitespace delimits too
    assert not p.done
    ok("number closed by whitespace", "reported before the comma arrives")

    n = collect('{"a": 1,"b": -2.5e3,"c": true,"d": false,"e": null}')
    assert n == [("a", 1), ("b", -2500.0), ("c", True), ("d", False), ("e", None)], n
    ok("bare values", "int, float, true, false, null")

    # 5 ── nested containers report only when the outermost close arrives
    p = PartialJSON()
    assert p.feed('{"coordinates": {"lat": 35.0, "lon": 135.7,') == []
    assert p.feed(' "radius_km": 2}') == [("coordinates", {"lat": 35.0, "lon": 135.7, "radius_km": 2})]
    ok("nested object", "silent until its own closing brace")

    p = PartialJSON()
    assert p.feed('{"evidence": [{"a": [1, {"b": 2}]}, {"c": "}]"') == []
    assert p.feed("}]}") == [("evidence", [{"a": [1, {"b": 2}]}, {"c": "}]"}])]
    ok("nested array", "depth ignores the '}]' inside a string")

    p = PartialJSON()  # an escaped quote inside a nested string must not close it
    assert p.feed(r'{"evidence": [{"o": "他说 \"{这里}\"') == []
    assert p.feed(r', 路径 D:\\"}]}') == [("evidence", [{"o": '他说 "{这里}", 路径 D:\\'}])]
    ok("escapes inside a nested value", "escaped quote and trailing backslash at depth 2")

    # 6 ── keys inside a nested value are not fields
    keys = [k for k, _ in collect(DOC)]
    assert "lat" not in keys and "observation" not in keys and "likelihood" not in keys
    ok("top level only", "lat / observation / likelihood never reported")

    # 7 ── leading noise, including a '{' that turns out to be prose
    f = collect("```json\n" + DOC + "\n```")
    assert [k for k, _ in f] == ORDER
    ok("```json fence prefix", "and trailing fence ignored after close")

    assert collect('\n\n   好的，结果如下：\n{"country": {"name_zh": "日本", "name_en": "Japan"}}') == [
        ("country", {"name_zh": "日本", "name_en": "Japan"})
    ]
    ok("prose preamble", "everything before the first '{' skipped")

    preamble = 'Sure! Here is the JSON {country, region, city}:\n' + DOC
    p = PartialJSON()
    r = [k for k, _ in p.feed(preamble)]
    assert r == ORDER, r  # the first '{' was prose; the seek must resume, not latch
    assert p.done and not p.broken
    ok("brace in the preamble", "seek resumed past `{country, region, city}` and found the object")

    p = PartialJSON()  # the same, split so the bogus brace and the real one differ by chunk
    assert p.feed("Here is the JSON {country") == []
    assert p.feed(', region}:\n{"country": "日本"') == [("country", "日本")]
    assert p.feed("}") == [] and p.done
    ok("brace in the preamble, across chunks", "recovery survives the chunk boundary")

    # 8 ── truncation and malformed input degrade, never raise
    cut = DOC.index('"evidence"') + 60  # mid-way through the first evidence item
    p = PartialJSON()
    fields = [k for k, _ in p.feed(DOC[:cut])]
    assert fields == ORDER[: ORDER.index("evidence")], fields
    assert not p.done and not p.broken and p.text == DOC[:cut]
    assert p.feed("") == [] and p.feed(" ") == []
    ok("truncated stream", f"reported {len(fields)} fields then stopped, done=False, broken=False")

    p = PartialJSON()
    assert p.feed('{"country": "日本", "region" "missing colon"') == [("country", "日本")]
    assert p.broken and not p.done
    assert p.feed(', "city": "京都"}') == [], "kept reporting after malformed input"
    assert not p.done and p.text.endswith('"京都"}')
    ok("malformed input", "degrades to an empty list, broken=True, text still available")

    for junk in ('{"a": @}', "{,}", '{"a"', '{"a":', "{", "", "not json at all", '{"a": [1,'):
        p = PartialJSON()
        p.feed(junk)
        p.feed(junk)
    ok("never raises", "8 malformed documents fed twice each")

    p = PartialJSON()  # a chunk that is not a str at all must not reach the caller
    assert p.feed(b'{"country": "\xe6\x97\xa5"}') == [], "a bytes chunk was not ignored"
    assert p.feed(None) == [] and p.feed(123) == [] and p.feed(["{"]) == []
    assert not p.broken, "a bad chunk killed the reader"
    assert p.feed('{"country": "日本"}') == [("country", "日本")] and p.done
    ok("non-str chunk", "bytes/None/int/list ignored, str stream unaffected")

    # 9 ── every completed value reported once; a duplicate key is a correction
    p = PartialJSON()
    seen = [k for c in DOC for k, _ in p.feed(c)]
    assert len(seen) == len(set(seen)) == len(ORDER)
    assert p.feed("") == [] and p.feed('{"country": "again"}') == []
    ok("reported once per completion", "no repeats across 1-char feeds or trailing text")

    dup = '{"country": "日本", "country": "法国", "notes": ""}'
    d = collect(dup)
    assert d == [("country", "日本"), ("country", "法国"), ("notes", "")], d
    assert dict(d) == json.loads(dup), "last-value-wins disagrees with json.loads"
    assert collect(*dup) == d, "duplicate correction lost when fed one character at a time"
    ok("duplicate key", "second value re-reported as a correction, agreeing with json.loads")

    # 10 ── iter_fields yields as it goes; it must not drain the source first
    pulled: list[str] = []

    def source() -> Iterator[str]:
        for c in DOC:
            pulled.append(c)
            yield c

    stream = iter_fields(source())
    assert next(stream) == ("country", ANSWER["country"])
    assert len(pulled) < len(DOC), "iter_fields drained the whole stream first"
    ok("iter_fields is lazy", f"country delivered after {len(pulled)}/{len(DOC)} chars")

    # 11 ── one bad value costs one field, not the rest of the document
    raw_nl = '{"a": "line\nbreak", "b": "\ttab", "c": 7}'  # literal control characters
    c = collect(raw_nl)
    assert c == [("a", "line\nbreak"), ("b", "\ttab"), ("c", 7)], c
    assert collect(*raw_nl) == c
    ok("raw control character in a string", "value kept, later fields not discarded")

    for bad in ('{"lat": NaN, "c": 7}', '{"lat": Infinity, "c": 7}', '{"lat": -Infinity, "c": 7}'):
        b = collect(bad)
        assert b == [("c", 7)], b
        assert collect(*bad) == b
    ok("NaN / Infinity", "dropped rather than streamed into a frame JSON.parse would reject")

    p = PartialJSON()
    assert p.feed('{"coordinates": {"lat": NaN, "lon": 1.0}, "c": 7}') == [("c", 7)]
    ok("NaN inside a nested value", "coordinates dropped whole, the stream continues")

    p = PartialJSON()  # a trailing comma: json.loads raises on it, so neither do we call it done
    assert p.feed('{"a": 1,}') == [("a", 1)]
    assert p.broken and not p.done, "trailing comma reported as a clean close"
    ok("trailing comma", "broken, matching what the caller's end-of-stream json.loads does")

    p = PartialJSON()
    assert p.feed("{}") == [] and p.done and not p.broken
    ok("empty object", "still a clean close, not mistaken for a trailing comma")

    # 12 ── buffering stays linear: the document must not be re-copied per chunk
    def stream_cost(size: int) -> float:
        doc = '{"summary": "' + "x" * size + '", "confidence": 88}'
        best = float("inf")
        for _ in range(3):
            q = PartialJSON()
            start = time.perf_counter()
            for ch in doc:
                q.feed(ch)
            best = min(best, time.perf_counter() - start)
            assert q.done and q.text == doc
        return best

    small = stream_cost(25_000)
    large = stream_cost(100_000)
    ratio = large / small if small else float("inf")
    assert ratio < 8.0, f"4x the input cost {ratio:.1f}x the time — buffering is quadratic"
    ok("linear buffering", f"4x input → {ratio:.1f}x time ({small * 1e3:.0f}ms → {large * 1e3:.0f}ms)")

    # 13 ── element reporting: the arrays named up front arrive one element at a
    #        time. Everything above ran with none named, and is what that must
    #        still look like.
    ARRAYS = ("evidence", "alternatives")

    def read(document: str, arrays: Iterable[str] = ARRAYS, size: int | None = None) -> list[Report]:
        """Feed `document` whole, or in `size`-character chunks; keep every report."""
        reader = PartialJSON(arrays=arrays)
        got: list[Report] = []
        if size is None:
            got.extend(reader.feed(document))
        else:
            for at in range(0, len(document), size):
                got.extend(reader.feed(document[at : at + size]))
        return got

    def sig(reports: list[Report]) -> list[tuple[str, Any, Any]]:
        """Identity INCLUDING the index, which tuple equality deliberately leaves out."""
        return [(r.field, r.index, r.value) for r in reports]

    assert read(DOC, ()) == whole, "naming no arrays changed the reports"
    assert sig(read(DOC, ())) == sig(whole), "naming no arrays invented an index"
    ok("arrays= defaults to off", f"{len(whole)} reports, byte for byte the old ones, every index None")

    ev = read(DOC)
    want: list[tuple[str, Any, Any]] = []
    for k in ORDER:
        if k in ARRAYS:  # elements first, each as it closes, then the array itself
            want += [(k, at, v) for at, v in enumerate(ANSWER[k])]
        want.append((k, None, ANSWER[k]))
    assert sig(ev) == want, sig(ev)
    ok("element by element", "evidence 0-3 and alternatives 0-1, each ahead of its own array")

    assert dict(ev) == ANSWER, "the whole-array report no longer lands last"
    assert [r.index for r in ev if r.field == "evidence"] == [0, 1, 2, 3, None]
    ok("the whole array is still reported", "last, so dict(reports) is unchanged — the caller drops it, not us")

    p = PartialJSON(arrays=("evidence",))
    first = closed = 0
    for at, c in enumerate(DOC, 1):
        for r in p.feed(c):
            if r.field == "evidence":
                first = first or at
                closed = at
    assert 0 < first < closed, (first, closed)
    ok(
        "the first entry beats the array",
        f"element 0 at char {first}, whole array at {closed} — {100 * (closed - first) // len(DOC)}% of the document sooner",
    )

    assert sig(read(DOC, ARRAYS, 1)) == sig(ev), "one character at a time diverged"
    ok("one character at a time, with elements", f"{len(DOC)} feeds, identical field/index/value sequence")

    rng = random.Random(20260807)
    widest = 0
    for _ in range(300):
        ragged, pos = [], 0
        while pos < len(DOC):
            step = rng.choice([1, 1, 1, 2, 3, 4, 5, 8, 13, 40, 200])
            ragged.append(DOC[pos : pos + step])
            pos += step
        assert sig(list(iter_fields(ragged, ARRAYS))) == want, f"ragged chunking diverged: {ragged[:3]}"
        widest = max(widest, len(ragged))
    ok("ragged chunks, with elements", f"300 random chunkings (up to {widest} chunks), identical down to every index")

    # 14 ── the boundary hazards, at the element level this time
    doc = '{"evidence": [{"o": "他说 }] , 「[A]」"}, {"o": "]"}, ","], "notes": ""}'
    h = read(doc, ("evidence",))
    assert sig(h) == [
        ("evidence", 0, {"o": "他说 }] , 「[A]」"}),
        ("evidence", 1, {"o": "]"}),
        ("evidence", 2, ","),
        ("evidence", None, [{"o": "他说 }] , 「[A]」"}, {"o": "]"}, ","]),
        ("notes", None, ""),
    ], sig(h)
    assert sig(read(doc, ("evidence",), 1)) == sig(h)
    ok("'}' ']' ',' inside a string inside an element", "3 elements, no boundary moved")

    doc = r'{"evidence": ["a\"", "\\", "b"], "notes": ""}'
    q = read(doc, ("evidence",))
    assert sig(q) == [
        ("evidence", 0, 'a"'),
        ("evidence", 1, "\\"),
        ("evidence", 2, "b"),
        ("evidence", None, ['a"', "\\", "b"]),
        ("notes", None, ""),
    ], sig(q)
    assert sig(read(doc, ("evidence",), 1)) == sig(q)
    ok("escaped quote at an element boundary", r'"a\"" and "\\" close on their own quote, not the escaped one')

    p = PartialJSON(arrays=("evidence",))
    assert p.feed('{"evidence": [{"o": "x\\') == []
    assert p.feed('"') == [], "an escaped quote closed the element"
    assert sig(p.feed('y"}')) == [("evidence", 0, {"o": 'x"y'})]
    assert sig(p.feed("]}")) == [("evidence", None, [{"o": 'x"y'}])] and p.done
    ok("escape split across a chunk boundary inside an element", 'x\\ + " + y"} → element 0 = {"o": \'x"y\'}')

    e = read('{"evidence": [], "alternatives": [\n  ], "notes": ""}')
    assert sig(e) == [("evidence", None, []), ("alternatives", None, []), ("notes", None, "")], sig(e)
    ok("empty array", "the whole-field report and nothing else")

    doc = '{"evidence": [1, -2.5e3, true, false, null, "s"]}'
    s = read(doc, ("evidence",))
    assert sig(s) == [
        ("evidence", 0, 1),
        ("evidence", 1, -2500.0),
        ("evidence", 2, True),
        ("evidence", 3, False),
        ("evidence", 4, None),
        ("evidence", 5, "s"),
        ("evidence", None, [1, -2500.0, True, False, None, "s"]),
    ], sig(s)
    assert sig(read(doc, ("evidence",), 1)) == sig(s)
    ok("array of scalars", "int, float, true, false, null, string — a null element is element 4, not a gap")

    doc = '{"evidence": [[1, 2], [], [[3], {"a": [4], "evidence": [5]}]]}'
    a = read(doc, ("evidence",))
    assert sig(a) == [
        ("evidence", 0, [1, 2]),
        ("evidence", 1, []),
        ("evidence", 2, [[3], {"a": [4], "evidence": [5]}]),
        ("evidence", None, [[1, 2], [], [[3], {"a": [4], "evidence": [5]}]]),
    ], sig(a)
    assert sig(read(doc, ("evidence",), 1)) == sig(a)
    ok("array of arrays", "3 elements; the arrays inside them, and an 'evidence' key inside them, report nothing")

    n = read('{"country": {"evidence": [1, 2]}, "evidence": [3]}', ("evidence",))
    assert sig(n) == [("country", None, {"evidence": [1, 2]}), ("evidence", 0, 3), ("evidence", None, [3])], sig(n)
    ok("top-level names only", "'evidence' nested in country reported nothing; the real one still did")

    o = read('{"evidence": "none", "alternatives": {"0": "x"}}')
    assert sig(o) == [("evidence", None, "none"), ("alternatives", None, {"0": "x"})], sig(o)
    ok("a named key holding a non-array", "reported whole, no elements invented out of a string or an object")

    t = read('{"evidence": [1, 2, ], "notes": ""}', ("evidence",))
    assert sig(t) == [("evidence", 0, 1), ("evidence", 1, 2), ("notes", None, "")], sig(t)
    ok("trailing comma inside the array", "both elements stand; the array itself is dropped, as json.loads would")

    p = PartialJSON(arrays=("evidence",))
    assert p.feed('{"evidence": [9') == [], "reported an element that could still grow"
    assert p.feed("5") == []
    assert sig(p.feed(", ")) == [("evidence", 0, 95)]
    ok("number element at end of buffer", "9 → 95 only reported once the comma proves it ended")

    b = read('{"evidence": [{"lat": NaN}, {"a": 2}, 3], "notes": ""}', ("evidence",))
    assert sig(b) == [("evidence", 1, {"a": 2}), ("evidence", 2, 3), ("notes", None, "")], sig(b)
    ok("a bad element costs that element", "the NaN entry dropped, 1 and 2 keep the positions they hold in the array")

    for junk in (
        '{"evidence": [,]}',
        '{"evidence": [}',
        '{"evidence": [1,',
        '{"evidence": ["',
        '{"evidence": [[[',
        '{"evidence": [@]}',
        '{"evidence": [1,,2]}',
        '{"evidence": ]',
    ):
        p = PartialJSON(arrays=ARRAYS)
        p.feed(junk)
        p.feed(junk)
    p = PartialJSON(arrays=ARRAYS)
    assert p.feed(b'{"evidence": [1]}') == [] and p.feed(None) == [] and not p.broken
    assert sig(p.feed('{"evidence": [1]}')) == [("evidence", 0, 1), ("evidence", None, [1])]
    ok("never raises with elements on", "8 malformed arrays fed twice each; bytes/None still ignored")

    p = PartialJSON(arrays=ARRAYS)
    g = p.feed('{"evidence": [1, 2], "region" "missing colon", "city": "x"}')
    assert sig(g) == [("evidence", 0, 1), ("evidence", 1, 2), ("evidence", None, [1, 2])], sig(g)
    assert p.broken and not p.done
    ok("malformed input after an array", "the elements already reported stand, nothing after them")

    assert sig(read('{"evidence": [1]}', "evidence")) == [("evidence", 0, 1), ("evidence", None, [1])]
    ok("arrays= given a bare string", "'evidence' is one key, not eight one-letter ones")

    # 15 ── element buffering is linear too: an element must not be re-copied per chunk
    def element_cost(count: int) -> float:
        entry = '{"o": "' + "x" * 60 + '"}'
        doc = '{"evidence": [' + ", ".join([entry] * count) + "]}"
        best = float("inf")
        for _ in range(3):
            q = PartialJSON(arrays=("evidence",))
            start = time.perf_counter()
            for ch in doc:
                q.feed(ch)
            best = min(best, time.perf_counter() - start)
            assert q.done and q.text == doc
        return best

    thin = element_cost(200)
    fat = element_cost(800)
    el_ratio = fat / thin if thin else float("inf")
    assert el_ratio < 8.0, f"4x the elements cost {el_ratio:.1f}x the time — element buffering is quadratic"
    ok("linear element buffering", f"4x input → {el_ratio:.1f}x time ({thin * 1e3:.0f}ms → {fat * 1e3:.0f}ms)")

    # 16 ── a Report is a drop-in for the two-tuple it replaced, copiers included.
    #        The plain pair copied and pickled; inheriting tuple.__getnewargs__
    #        turned every one of those into a TypeError.
    import copy as copymod
    import pickle

    one = Report("evidence", {"o": ["x"]}, 3)
    clones = [("copy.copy", copymod.copy(one)), ("copy.deepcopy", copymod.deepcopy(one))]
    clones += [
        (f"pickle p{proto}", pickle.loads(pickle.dumps(one, proto)))
        for proto in range(pickle.HIGHEST_PROTOCOL + 1)
    ]
    for label, clone in clones:
        assert type(clone) is Report, (label, type(clone))
        assert clone == one == ("evidence", {"o": ["x"]}), (label, clone)
        assert len(clone) == 2 and tuple(clone) == ("evidence", {"o": ["x"]}), label
        assert clone.field == "evidence" and clone.value == {"o": ["x"]}, label
        assert clone.index == 3, f"{label} lost .index"
        assert clone.restart is False, f"{label} lost .restart"
        assert dict([clone, Report("notes", "")]) == {"evidence": {"o": ["x"]}, "notes": ""}, label
    ok(
        "Report copies and pickles",
        f"copy, deepcopy and pickle protocols 0-{pickle.HIGHEST_PROTOCOL}, .index and .restart intact",
    )

    batch = [
        Report("evidence", [], None, True),
        Report("evidence", {"o": ["x"]}, 0),
        Report("country", {"name_zh": "日本"}),
    ]
    deep = copymod.deepcopy(batch)
    assert sig(deep) == sig(batch), sig(deep)
    assert [r.restart for r in deep] == [True, False, False]
    deep[1].value["o"].append("y")
    assert batch[1].value["o"] == ["x"], "deepcopy handed back a shared value"
    assert copymod.copy(batch[1]).value is batch[1].value, "copy.copy went deep"
    assert copymod.deepcopy(Report("a", 1)).index is None, "index=None did not survive"
    ok("a list of Reports deep-copies", "3 reports, index/restart kept, values genuinely detached")

    # 17 ── a repeated array key must not leave the rows of the array it replaced.
    #        The whole-field path replaces outright; the element path can only
    #        overwrite the positions the second array reaches, so the reader
    #        clears the field at the '[' and starts counting again.
    def replay(reports: Iterable[Report]) -> dict[str, Any]:
        """The client, exactly as "Applying the reports" spells it out."""
        state: dict[str, Any] = {}
        for r in reports:
            if r.index is None:
                state[r.field] = r.value
            else:
                rows = state.setdefault(r.field, [])
                assert isinstance(rows, list), f"element report onto a non-list {r.field!r}"
                while len(rows) <= r.index:
                    rows.append(None)  # a dropped element leaves a hole, not a shift
                rows[r.index] = r.value
        return state

    assert replay(whole) == ANSWER and replay(ev) == ANSWER
    assert not any(r.restart for r in ev), "a document with no repeated key got a reset"
    ok("replay reproduces the document", "both with elements streamed and without, no reset invented")

    REPEATS = [
        # the shape the reset exists for: the second array is shorter than the first
        '{"evidence": [{"o": "a"}, {"o": "b"}, {"o": "c"}], "evidence": [{"o": "x"}], "notes": ""}',
        '{"evidence": [1, 2, 3], "evidence": [7]}',
        '{"evidence": [1, 2, 3], "evidence": []}',
        '{"evidence": [], "evidence": [1, 2]}',
        '{"evidence": [1, 2, 3], "evidence": [4, 5, 6, 7]}',
        '{"evidence": "none", "evidence": [1], "notes": ""}',
        '{"evidence": [1, 2], "evidence": "none", "notes": ""}',
        '{"evidence": [1, 2, 3], "alternatives": [9, 8], "evidence": [7], "alternatives": [], "notes": ""}',
        '{"evidence": [1], "evidence": [2], "evidence": [3, 4], "evidence": [5]}',
        DOC,
    ]
    rng = random.Random(20260807)
    for document in REPEATS:
        truth = json.loads(document)
        base = read(document, ARRAYS)
        marks = [r.restart for r in base]
        for arrays in (ARRAYS, ()):
            for size in (None, 1, 3, 7):
                landed = replay(read(document, arrays, size))
                assert landed == truth, (document[:48], arrays, size, landed, truth)
        for _ in range(60):  # and the boundaries no fixed chunk size lands on
            ragged, pos = [], 0
            while pos < len(document):
                step = rng.choice([1, 1, 1, 2, 3, 4, 5, 8, 13, 40, 200])
                ragged.append(document[pos : pos + step])
                pos += step
            torn = list(iter_fields(ragged, ARRAYS))
            assert sig(torn) == sig(base), (document[:48], ragged[:3])
            assert [r.restart for r in torn] == marks, (document[:48], ragged[:3])
            assert replay(torn) == truth, (document[:48], ragged[:3])
    ok(
        "a repeated array key replays to json.loads",
        f"{len(REPEATS)} documents x elements on/off x 4 chunkings + 60 random ones each, every sequence identical",
    )

    stale = '{"evidence": [{"o": "a"}, {"o": "b"}, {"o": "c"}], "evidence": [{"o": "x"}'
    p = PartialJSON(arrays=("evidence",))
    g = p.feed(stale)  # cut off before the second array closes: no whole-field rescue
    assert [r.restart for r in g] == [False, False, False, False, True, False], sig(g)
    assert replay(g) == {"evidence": [{"o": "x"}]}, replay(g)
    assert replay(r for r in g if not r.restart) == {
        "evidence": [{"o": "x"}, {"o": "b"}, {"o": "c"}]
    }, "the reset is not what removes the stale rows"
    assert replay(read(stale + "]}", ("evidence",))) == json.loads(stale + "]}")
    ok(
        "the reset lands at the '[', not at the close",
        "b and c gone before element 0 of the replacement, so a truncated stream is short, not wrong",
    )

    print(f"\n{checks} checks passed")
