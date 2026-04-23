import os
from pathlib import Path
from cryptography.fernet import Fernet

KEY_PATH = Path(__file__).parent / ".secret.key"


def _load_or_create_key() -> bytes:
    env_key = os.environ.get("DASHBOARD_SECRET_KEY")
    if env_key:
        return env_key.encode()
    if KEY_PATH.exists():
        return KEY_PATH.read_bytes()
    key = Fernet.generate_key()
    KEY_PATH.write_bytes(key)
    try:
        os.chmod(KEY_PATH, 0o600)
    except OSError:
        pass
    return key


_fernet = Fernet(_load_or_create_key())


def encrypt(plaintext: str) -> str:
    if plaintext is None or plaintext == "":
        return ""
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    return _fernet.decrypt(ciphertext.encode()).decode()
