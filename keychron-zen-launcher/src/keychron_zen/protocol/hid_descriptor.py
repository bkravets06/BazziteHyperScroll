"""Minimal HID report descriptor parser.

A QMK keyboard exposes several ``/dev/hidraw`` nodes -- the keyboard itself,
a consumer-control interface, sometimes a mouse -- and exactly one of them is
the "raw HID" interface that VIA speaks over. That interface is identified by
its top-level application collection: usage page ``0xFF60``, usage ``0x61``.

Parsing the descriptor is the only reliable way to tell the nodes apart, so
this module implements just enough of the HID specification to walk the item
stream and describe each application collection it finds.
"""

from __future__ import annotations

from dataclasses import dataclass

RAW_USAGE_PAGE = 0xFF60
RAW_USAGE_ID = 0x61

# Item prefix layout, HID 1.11 section 6.2.2.2.
_TYPE_MAIN = 0
_TYPE_GLOBAL = 1
_TYPE_LOCAL = 2

_TAG_COLLECTION = 0x0A
_TAG_END_COLLECTION = 0x0C

_TAG_USAGE_PAGE = 0x00
_TAG_REPORT_SIZE = 0x07
_TAG_REPORT_COUNT = 0x09

_TAG_USAGE = 0x00

_COLLECTION_APPLICATION = 0x01

# A size code of 3 means four bytes, not three.
_SIZES = (0, 1, 2, 4)


@dataclass(frozen=True)
class Collection:
    """A top-level application collection found in a report descriptor."""

    usage_page: int
    usage: int
    report_bytes: int

    @property
    def is_raw_hid(self) -> bool:
        return self.usage_page == RAW_USAGE_PAGE and self.usage == RAW_USAGE_ID


def _items(data: bytes):
    """Yield ``(type, tag, value)`` for every short item in the descriptor."""
    offset = 0
    end = len(data)
    while offset < end:
        prefix = data[offset]
        offset += 1
        if prefix == 0xFE:  # long item: skip its payload, nothing we need is one
            if offset + 2 > end:
                return
            length = data[offset]
            offset += 2 + length
            continue
        size = _SIZES[prefix & 0x03]
        if offset + size > end:
            return
        value = int.from_bytes(data[offset : offset + size], "little")
        offset += size
        yield (prefix >> 2) & 0x03, (prefix >> 4) & 0x0F, value


def parse_collections(descriptor: bytes) -> list[Collection]:
    """Return the application collections described by ``descriptor``."""
    collections: list[Collection] = []
    usage_page = 0
    usages: list[int] = []
    report_size = 0
    report_count = 0
    depth = 0
    pending: tuple[int, int] | None = None

    for item_type, tag, value in _items(descriptor):
        if item_type == _TYPE_GLOBAL:
            if tag == _TAG_USAGE_PAGE:
                usage_page = value
            elif tag == _TAG_REPORT_SIZE:
                report_size = value
            elif tag == _TAG_REPORT_COUNT:
                report_count = value
        elif item_type == _TYPE_LOCAL:
            if tag == _TAG_USAGE:
                usages.append(value)
        elif item_type == _TYPE_MAIN:
            if tag == _TAG_COLLECTION:
                if depth == 0 and value == _COLLECTION_APPLICATION:
                    pending = (usage_page, usages[0] if usages else 0)
                depth += 1
            elif tag == _TAG_END_COLLECTION:
                depth = max(0, depth - 1)
                if depth == 0 and pending is not None:
                    page, usage = pending
                    size = report_count if report_size == 8 else 0
                    collections.append(Collection(page, usage, size))
                    pending = None
                    report_size = report_count = 0
            usages.clear()

    return collections


def find_raw_hid(descriptor: bytes) -> Collection | None:
    """Return the VIA/QMK raw HID collection, or ``None`` if there isn't one."""
    for collection in parse_collections(descriptor):
        if collection.is_raw_hid:
            return collection
    return None
