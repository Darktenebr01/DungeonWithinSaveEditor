#!/usr/bin/env python3
"""
dw_es3.py - read/write the game's ES3E save container without launching it.

Container layout (verified against the shipped build):

    "ES3E" | AES-256-CBC(PKCS7(Brotli(plaintext, quality 1))) | HMAC-SHA256(ciphertext)

The AES/HMAC keys are the literal byte arrays compiled into ES3Saver.  They are
recovered constants, not per-user secrets; the editor uses them only to read the
local save that the user already owns.  Writing through the game's own
CompressAndEncrypt (dw_save_encrypt.py) remains the supported write path.
"""

import hashlib
import hmac

import brotli
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b'ES3E'
AES_KEY = b'AnT1gRvy_AES_Key_32bytes_Secret!'
AES_IV = b'AnT1gRvy_AES_IV!'
HMAC_KEY = b'AnT1gRvy_HMAC_SHA256_Key_32bytes'

BLOCK = 16


class ContainerError(Exception):
    pass


def is_container(data):
    return len(data) >= len(MAGIC) + BLOCK + 32 and data[:4] == MAGIC


def _aes_cbc(data, encrypt):
    cipher = Cipher(algorithms.AES(AES_KEY), modes.CBC(AES_IV))
    ctx = cipher.encryptor() if encrypt else cipher.decryptor()
    return ctx.update(data) + ctx.finalize()


def decrypt(data):
    """ES3E bytes -> plaintext JSON bytes."""
    if not is_container(data):
        raise ContainerError('not an ES3E container')
    ciphertext = data[4:-32]
    mac = data[-32:]
    if len(ciphertext) % BLOCK:
        raise ContainerError('ciphertext is not block aligned')
    want = hmac.new(HMAC_KEY, ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(want, mac):
        raise ContainerError('container HMAC mismatch')
    padded = _aes_cbc(ciphertext, encrypt=False)
    pad = padded[-1]
    if pad < 1 or pad > BLOCK or padded[-pad:] != bytes([pad]) * pad:
        raise ContainerError('bad padding')
    return brotli.decompress(padded[:-pad])


def encrypt(plaintext):
    """Plaintext JSON bytes -> ES3E bytes (Brotli quality 1, as the game writes)."""
    compressed = brotli.compress(plaintext, quality=1)
    pad = BLOCK - len(compressed) % BLOCK
    padded = compressed + bytes([pad]) * pad
    ciphertext = _aes_cbc(padded, encrypt=True)
    mac = hmac.new(HMAC_KEY, ciphertext, hashlib.sha256).digest()
    return MAGIC + ciphertext + mac
