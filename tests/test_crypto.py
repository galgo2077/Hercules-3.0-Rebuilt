"""AES-GCM roundtrip and tamper-detection tests."""

import base64
import os

import pytest
from cryptography.exceptions import InvalidTag

os.environ.setdefault("HERCULES_MASTER_KEY", base64.b64encode(os.urandom(32)).decode())

from Live.Crypto import decrypt, encrypt, generate_key


def test_roundtrip():
    for plaintext in ("api_key_abc123", "s3cr3t!", "x" * 200):
        blob = encrypt(plaintext)
        assert decrypt(blob["ciphertext"], blob["nonce"], blob["tag"]) == plaintext


def test_generate_key_length():
    key = generate_key()
    assert len(base64.b64decode(key)) == 32


def test_tampered_ciphertext_rejected():
    blob = encrypt("hello")
    bad = base64.b64encode(b"\x00" * 16).decode()
    with pytest.raises(InvalidTag):
        decrypt(bad, blob["nonce"], blob["tag"])


def test_tampered_tag_rejected():
    blob = encrypt("hello")
    bad_tag = base64.b64encode(b"\xff" * 16).decode()
    with pytest.raises(InvalidTag):
        decrypt(blob["ciphertext"], blob["nonce"], bad_tag)


def test_different_encryptions_differ():
    a = encrypt("same")
    b = encrypt("same")
    assert a["nonce"] != b["nonce"]
    assert a["ciphertext"] != b["ciphertext"]
