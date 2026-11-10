"""Calcolo e verifica dell'hash dei PIN, usando la libreria standard Python."""

import hashlib
import hmac
import secrets

# Vlaore raccomandato secondo:
# https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html#pbkdf2
ITERATIONS = 600000


def hash_pin(pin: str) -> tuple[bytes, bytes]:
    """
    Restituisce salt casuale e hash PBKDF2 di un PIN.
    
    Input:
        pin: PIN
    Output:
        Tuple contenente salt e hash
    """

    # https://docs.python.org/3/library/hashlib.html#hashlib.pbkdf2_hmac
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode("ascii"), salt, ITERATIONS)
    return salt, digest


def verify_pin(pin: str, salt: bytes, digest: bytes) -> bool:
    """
    Verifica un PIN.
    
    Input:
        pin: PIN da verificare
        salt: salt utilizzato per l'hash
        digest: hash da confrontare
    Output:
        Risultato della verifica
    """
    candidate = hashlib.pbkdf2_hmac("sha256", pin.encode("ascii"), salt, ITERATIONS)
    return hmac.compare_digest(digest, candidate)
