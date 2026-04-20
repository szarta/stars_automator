"""
x1.py — Write Stars! .x1 player order files.

The x1 file format (same cipher as .m1/.hst):
  - Type-8 file header (16 bytes, plaintext) — seeds the L'Ecuyer LCG cipher
  - Type-9 FileInfo (17 bytes, encrypted) — LengthOfFollowingBlocks + machine hash
  - Order records (encrypted)
  - Type-0 end marker (2 bytes, plaintext)

Only WaypointAdd (Type-4) is implemented; other order types can be added when
needed.

Cipher notes:
  Same L'Ecuyer combined LCG as all other Stars! file types.  The Type-8
  header payload determines the seeds and pre-advance count; subsequent record
  payloads are XOR-encrypted with the keystream.

  Bytes 0-11 of the Type-8 header are game-specific (same across all files in
  a game: hst, m1, x1, etc.).  Bytes 12-15 are chosen freely and control the
  cipher seeds and pre_advance.  Stars! validates bytes 0-11 against the game
  record — wrong bytes cause silent order rejection.

  We derive seeds and pre_advance from the actual header using the same
  algorithm as the Rust parser (derive_seeds / derive_pre_advance).
"""

import struct
from dataclasses import dataclass
from pathlib import Path

# ── L'Ecuyer LCG ──────────────────────────────────────────────────────────────

_M1, _A1, _Q1, _R1 = 2_147_483_563, 40_014, 53_668, 12_211
_M2, _A2, _Q2, _R2 = 2_147_483_399, 40_692, 52_774, 3_791

_SEED_TABLE: tuple[int, ...] = (
    3,
    5,
    7,
    11,
    13,
    17,
    19,
    23,
    29,
    31,
    37,
    41,
    43,
    47,
    53,
    59,
    61,
    67,
    71,
    73,
    79,
    83,
    89,
    97,
    101,
    103,
    107,
    109,
    113,
    127,
    131,
    137,
    139,
    149,
    151,
    157,
    163,
    167,
    173,
    179,
    181,
    191,
    193,
    197,
    199,
    211,
    223,
    227,
    229,
    233,
    239,
    241,
    251,
    257,
    263,
    279,
    271,
    277,
    281,
    283,
    293,
    307,
    311,
    313,
)


def _derive_seeds(seed_word: int) -> tuple[int, int]:
    """Derive LCG seeds from the 16-bit value at bytes 12-13 of the Type-8 header."""
    param3 = seed_word >> 5
    idx1 = param3 & 0x1F
    idx2 = (param3 >> 5) & 0x1F
    if (param3 & 0x400) == 0:
        idx2 += 32
    else:
        idx1 += 32
    return _SEED_TABLE[idx1], _SEED_TABLE[idx2]


def _derive_pre_advance(hdr: bytes) -> int:
    """Compute LCG pre-advance count from the 16-byte Type-8 header payload."""
    p1 = struct.unpack_from("<h", hdr, 4)[0]
    p4 = struct.unpack_from("<h", hdr, 10)[0]
    sw = struct.unpack_from("<H", hdr, 12)[0]
    p5 = sw & 0x1F
    p6 = (struct.unpack_from("<H", hdr, 14)[0] >> 12) & 1
    return ((p1 & 3) + 1) * ((p4 & 3) + 1) * ((p5 & 3) + 1) + p6


class _LCG:
    __slots__ = ("_x", "_y")

    def __init__(self, x: int, y: int) -> None:
        self._x = x
        self._y = y

    def _step(self) -> int:
        k = self._x // _Q1
        self._x = _A1 * (self._x - k * _Q1) - k * _R1
        if self._x < 0:
            self._x += _M1
        k = self._y // _Q2
        self._y = _A2 * (self._y - k * _Q2) - k * _R2
        if self._y < 0:
            self._y += _M2
        return (self._x - self._y) & 0xFFFFFFFF

    def advance(self, n: int) -> None:
        for _ in range(n):
            self._step()

    def encrypt_inplace(self, buf: bytearray, length: int) -> None:
        pos = 0
        for _ in range(length >> 2):
            key = self._step()
            for j in range(4):
                buf[pos + j] ^= (key >> (j * 8)) & 0xFF
            pos += 4
        rem = length & 3
        if rem:
            key = self._step()
            for j in range(rem):
                buf[pos + j] ^= (key >> (j * 8)) & 0xFF


# ── Header constants ──────────────────────────────────────────────────────────

# Bytes 12-15 of the Type-8 payload we choose for x1 files.
# These control the cipher seeds (bytes 12-13) and part of pre_advance (bytes 14-15).
# Chosen so seeds s1=223, s2=97 and p5=0, p6=0 (pre_advance depends on the game's
# bytes 4-5 and 10-11 as well).
_TYPE8_SEED_BYTES = bytes.fromhex("c0dd0100")

# Type-9 machine hash (bytes 2-16 of the decrypted payload, 15 bytes).
# Constant for this Stars! installation; derived from reference x1 files.
_TYPE9_HASH = bytes.fromhex("a91006fea5dca6597ac5a5dca67aa0")

assert len(_TYPE8_SEED_BYTES) == 4
assert len(_TYPE9_HASH) == 15


def read_game_type8_prefix(game_file: str | Path) -> bytes:
    """Read bytes 0-11 of the Type-8 header from any Stars! game file (m1, hst, etc.).

    These bytes are game-specific and must appear verbatim in the x1 Type-8
    header.  Stars! validates them on x1 import and silently rejects mismatches.
    """
    data = Path(game_file).read_bytes()
    hdr_word = struct.unpack_from("<H", data, 0)[0]
    rtype = hdr_word >> 10
    rlen = hdr_word & 0x3FF
    if rtype != 8 or rlen < 12:
        raise ValueError(f"{game_file}: expected type-8 header, got type={rtype} len={rlen}")
    return data[2:14]  # bytes 0-11 of the payload


# ── ResearchChange record ─────────────────────────────────────────────────────


@dataclass
class ResearchChange:
    """A type-34 ResearchChange order.

    Fields: 0=Energy 1=Weapons 2=Propulsion 3=Construction 4=Electronics 5=Biology 6=SameField
    """

    current_field: int  # field to research now
    next_field: int  # field to switch to after current is done
    research_percent: int = 15  # percent of resources allocated to research

    def payload(self) -> bytes:
        return bytes([self.research_percent, (self.next_field << 4) | self.current_field])


# ── WaypointAdd record ────────────────────────────────────────────────────────


@dataclass
class WaypointAdd:
    """A single Type-4 WaypointAdd order directing one fleet to one planet."""

    fleet_num: int  # 0-based fleet index (9-bit, max 511)
    wp_nr: int  # waypoint sequence number (1 = first new waypoint)
    dest_x: int  # destination X coordinate (LE uint16)
    dest_y: int  # destination Y coordinate (LE uint16)
    target_idx: int  # 0-based planet index (LE uint16, = map_number - 1)
    warp: int = 4  # warp speed (default 4 = zero fuel with Fuel Mizer/IFE)

    def payload(self) -> bytes:
        """Return the 12-byte plaintext payload for this record."""
        return struct.pack(
            "<HBBHHHBB",
            self.fleet_num,
            self.wp_nr,
            0,  # padding
            self.dest_x & 0xFFFF,
            self.dest_y & 0xFFFF,
            self.target_idx & 0xFFFF,
            (self.warp << 4) | 0,  # task = None
            0x91,  # flags=9, targetType=1 (planet); from confirmed oracle
        )


# ── File writer ───────────────────────────────────────────────────────────────


def _make_lcg_from_header(hdr16: bytes) -> _LCG:
    """Create an LCG seeded and pre-advanced per the given 16-byte Type-8 header."""
    seed_word = struct.unpack_from("<H", hdr16, 12)[0]
    s1, s2 = _derive_seeds(seed_word)
    lcg = _LCG(s1, s2)
    lcg.advance(_derive_pre_advance(hdr16))
    return lcg


def _record_header(rtype: int, rlen: int) -> bytes:
    return struct.pack("<H", (rtype << 10) | (rlen & 0x3FF))


def build_x1(
    waypoints: list[WaypointAdd],
    game_file: str | Path,
    research: list[ResearchChange] | None = None,
) -> bytes:
    """Assemble a Stars! .x1 file containing the given orders.

    game_file must be any Stars! file from the same game (e.g. the .m1 or .hst
    file) so that the game-specific bytes 0-11 of the Type-8 header can be read.
    Stars! validates these bytes on x1 import; a mismatch causes silent rejection.

    Each WaypointAdd emits a type-4 (WaypointAdd) AND type-5 (WaypointChangeTask)
    pair, as Stars! always writes both. For task=None movement both records are
    identical. Type-5 is authoritative for the task.

    Returns the complete file content as bytes.
    """
    game_prefix = read_game_type8_prefix(game_file)  # bytes 0-11 (game-specific)
    type8_payload = game_prefix + _TYPE8_SEED_BYTES  # bytes 12-15 (cipher choice)
    assert len(type8_payload) == 16

    lcg = _make_lcg_from_header(type8_payload)
    out = bytearray()

    # Type-8 header (plaintext)
    out += _record_header(8, 16)
    out += type8_payload

    # Type-9 FileInfo: compute LengthOfFollowingBlocks
    # Each WaypointAdd = type-4 + type-5 = 2*(2+12) = 28 bytes.
    # Each ResearchChange = 2+2 = 4 bytes.
    research = research or []
    following_bytes = len(research) * 4 + len(waypoints) * 28
    type9_plain = struct.pack("<H", following_bytes) + _TYPE9_HASH
    assert len(type9_plain) == 17
    type9_enc = bytearray(type9_plain)
    lcg.encrypt_inplace(type9_enc, 17)
    out += _record_header(9, 17)
    out += bytes(type9_enc)

    # Type-34 ResearchChange records
    for rc in research:
        pl = bytearray(rc.payload())
        lcg.encrypt_inplace(pl, 2)
        out += _record_header(34, 2)
        out += bytes(pl)

    # Type-4 (WaypointAdd) + Type-5 (WaypointChangeTask) pairs
    for wp in waypoints:
        payload = wp.payload()
        for rtype in (4, 5):
            pl = bytearray(payload)
            lcg.encrypt_inplace(pl, 12)
            out += _record_header(rtype, 12)
            out += bytes(pl)

    # Type-0 end marker
    out += _record_header(0, 0)

    return bytes(out)


def write_x1(
    path: str | Path,
    waypoints: list[WaypointAdd],
    game_file: str | Path,
    research: list[ResearchChange] | None = None,
) -> None:
    """Write an x1 file containing the given orders.

    game_file is any Stars! file from the same game (e.g. the .m1 or .hst).
    """
    Path(path).write_bytes(build_x1(waypoints, game_file, research))
