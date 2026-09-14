"""Rewrite Ogg-Opus page headers to join chunked TTS output into one seekable stream.

Pure stdlib, no ffmpeg. Why and how: workflows/pdf_tts/README.md "Opus stitching"; RFC 3533, RFC 7845.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from dataclasses import dataclass

from shared.obs import get_logger

log = get_logger(__name__)

_MAGIC = b"OggS"
_HEADER_LEN = 27
_FLAG_BOS = 0x02
_FLAG_EOS = 0x04
_NO_GRANULE = 0xFFFFFFFFFFFFFFFF  # -1: no packet finishes on this page
_OPUS_SAMPLE_RATE = 48000  # granule positions are always in 48 kHz units


class OggOpusError(ValueError):
    """The bytes are not a well-formed Ogg-Opus stream."""


def _crc_table() -> list[int]:
    """Ogg's CRC32: poly 0x04C11DB7, init 0, no reflection, no final XOR.

    Deliberately not `zlib.crc32`, which reflects input and output and inverts the
    result — it produces a different checksum and every page would fail validation.
    """
    table = []
    for i in range(256):
        crc = i << 24
        for _ in range(8):
            crc = (crc << 1) ^ 0x04C11DB7 if crc & 0x80000000 else crc << 1
            crc &= 0xFFFFFFFF
        table.append(crc)
    return table


_CRC_TABLE = _crc_table()


def _crc32(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ _CRC_TABLE[((crc >> 24) & 0xFF) ^ byte]
    return crc


@dataclass
class _Page:
    header_type: int
    granule: int
    serial: int
    seq: int
    segments: bytes
    payload: bytes

    def to_bytes(self) -> bytes:
        head = bytearray(_MAGIC)
        head.append(0)  # stream structure version
        head.append(self.header_type)
        head += struct.pack("<Q", self.granule)
        head += struct.pack("<I", self.serial)
        head += struct.pack("<I", self.seq)
        head += b"\x00\x00\x00\x00"  # CRC field zeroed while checksumming
        head.append(len(self.segments))
        head += self.segments
        page = bytes(head) + self.payload
        crc = _crc32(page)
        return page[:22] + struct.pack("<I", crc) + page[26:]


def _parse_pages(blob: bytes) -> list[_Page]:
    pages: list[_Page] = []
    pos = 0
    end = len(blob)
    while pos < end:
        if end - pos < _HEADER_LEN or blob[pos : pos + 4] != _MAGIC:
            raise OggOpusError(f"missing OggS capture pattern at byte {pos}")
        if blob[pos + 4] != 0:
            raise OggOpusError(f"unsupported Ogg version {blob[pos + 4]} at byte {pos}")
        seg_count = blob[pos + 26]
        table_end = pos + _HEADER_LEN + seg_count
        if table_end > end:
            raise OggOpusError(f"truncated segment table at byte {pos}")
        segments = blob[pos + _HEADER_LEN : table_end]
        payload_len = sum(segments)
        payload_end = table_end + payload_len
        if payload_end > end:
            raise OggOpusError(f"page at byte {pos} claims {payload_len} bytes past the end")
        pages.append(
            _Page(
                header_type=blob[pos + 5],
                granule=struct.unpack_from("<Q", blob, pos + 6)[0],
                serial=struct.unpack_from("<I", blob, pos + 14)[0],
                seq=struct.unpack_from("<I", blob, pos + 18)[0],
                segments=segments,
                payload=blob[table_end:payload_end],
            )
        )
        pos = payload_end
    if not pages:
        raise OggOpusError("no Ogg pages found")
    return pages


def _pre_skip(head_page: _Page) -> int:
    """Samples the decoder must discard at stream start (RFC 7845 §5.1)."""
    packet = head_page.payload
    if not packet.startswith(b"OpusHead") or len(packet) < 12:
        raise OggOpusError("first page is not an OpusHead packet")
    return int(struct.unpack_from("<H", packet, 10)[0])


def concat(parts: Sequence[bytes]) -> tuple[bytes, float]:
    """Join Ogg-Opus blobs into one logical stream.

    Returns `(ogg_bytes, duration_seconds)`. The duration matters as much as the bytes:
    Telegram only derives a voice message's length from container metadata for short
    clips, so anything longer must be told explicitly or it renders as 0:00.

    Raises `OggOpusError` if any blob is not well-formed Ogg-Opus; callers are expected
    to fall back to a plain byte join rather than fail the job.
    """
    if not parts:
        raise OggOpusError("no audio parts to join")

    emitted: list[_Page] = []
    serial = 0
    seq = 0
    granule_offset = 0
    pre_skip = 0

    for index, blob in enumerate(parts):
        pages = _parse_pages(blob)
        if len(pages) < 3:
            raise OggOpusError(f"part {index + 1} has only {len(pages)} pages, expected >= 3")

        if index == 0:
            # Keep this stream's identity: its serial, its OpusHead and its OpusTags
            # become the header of the joined stream.
            serial = pages[0].serial
            pre_skip = _pre_skip(pages[0])
            for page in pages[:2]:
                page.seq = seq
                seq += 1
                emitted.append(page)

        # Every later stream's OpusHead/OpusTags are dropped — a logical bitstream
        # carries exactly one of each.
        last_granule = 0
        for page in pages[2:]:
            original = page.granule
            if original != _NO_GRANULE:
                last_granule = original
                page.granule = original + granule_offset
            page.serial = serial
            page.seq = seq
            seq += 1
            page.header_type &= ~(_FLAG_BOS | _FLAG_EOS)
            emitted.append(page)
        granule_offset += last_granule

    emitted[0].header_type |= _FLAG_BOS
    emitted[-1].header_type |= _FLAG_EOS

    # Every part after the first keeps its pre-skip padding as real decodable
    # samples: its OpusHead -- which is what tells a decoder to discard them --
    # was dropped. So only the first stream's pre-skip comes off the total.
    duration = max(0.0, (granule_offset - pre_skip) / _OPUS_SAMPLE_RATE)
    log.info(
        "ogg_opus.concat: %d parts -> %d pages, %.1fs",
        len(parts),
        len(emitted),
        duration,
    )
    return b"".join(page.to_bytes() for page in emitted), duration
