from __future__ import annotations

import base64
import hashlib


def generate_id(type_value: str, scope_str: str, key: str) -> str:
    """Generate a deterministic memory item ID.

    Formula: "mem_" + base32(blake2s("v1|{type}|{scope}|{key}", digest_size=16))[:8]
    """
    payload = f"v1|{type_value}|{scope_str}|{key}"
    digest = hashlib.blake2s(payload.encode(), digest_size=16).digest()
    b32 = base64.b32encode(digest).decode().rstrip("=")
    return f"mem_{b32[:8]}"
