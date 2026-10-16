#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ابزار رمزگشایی فایل بکاپ CiaNet (پشتیبانی از قالب PBKDF2+Fernet CNB1 و قالب قدیمی)."""
import base64
import getpass
import hashlib
import os
import sys
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def decrypt_backup(input_path: str, output_path: str, password: str) -> None:
    with open(input_path, "rb") as f:
        data = f.read()
    if data.startswith(b"CNB1"):
        salt = data[4:20]
        token = data[20:]
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100_000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))
    else:
        token = data
        key = base64.urlsafe_b64encode(hashlib.sha256(password.encode("utf-8")).digest())
    plain = Fernet(key).decrypt(token)
    with open(output_path, "wb") as out:
        out.write(plain)
    os.chmod(output_path, 0o600)


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python3 tools/decrypt_backup.py <encrypted_backup.zip> [output_decrypted.zip]")
        return 1
    in_path = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else in_path + ".decrypted.zip"
    pw = os.environ.get("CIANET_BACKUP_PASS", "").strip()
    if not pw:
        pw = getpass.getpass("CIANET_BACKUP_PASS: ").strip()
    if not pw:
        print("Error: password required.", file=sys.stderr)
        return 1
    decrypt_backup(in_path, out_path, pw)
    print(f"Decrypted backup written to: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())