"""A service account for a copy of the shop that talks to a fake Firebase - a development or test copy,
never a real shop, whose account comes from the Firebase console:

    python -m app.fcm_dev_account barber-test-fcm.json http://127.0.0.1:8110/token

A fresh RSA key and the fake's token address, written to the file FCM_CREDENTIALS names."""

import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

if __name__ == "__main__":
    path, token_uri = sys.argv[1], sys.argv[2]
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    account = {
        "type": "service_account",
        "project_id": "test-copy",
        "client_email": "push@test-copy.iam.gserviceaccount.com",
        "private_key": pem.decode(),
        "token_uri": token_uri,
    }
    Path(path).write_text(json.dumps(account), encoding="utf-8")
