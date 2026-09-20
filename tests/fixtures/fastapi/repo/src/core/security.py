import bcrypt
import jwt


def hash_password(raw: bytes) -> bytes:
    return bcrypt.hashpw(raw, bcrypt.gensalt())


def get_current_user(token: str):
    return jwt.decode(token, options={"verify_signature": False})


def is_admin(role: str) -> bool:
    return role == "admin"
