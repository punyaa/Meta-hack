from signalforge.services.auth import (
    SESSION_MAX_AGE,
    create_session_token,
    hash_password,
    read_session_token,
    valid_email,
    valid_password,
    verify_password,
)


def test_password_roundtrip() -> None:
    encoded = hash_password("correct horse battery")
    assert verify_password("correct horse battery", encoded) is True
    assert verify_password("wrong password here!", encoded) is False
    assert verify_password("correct horse battery", "not-a-hash") is False
    assert verify_password("correct horse battery", "scrypt$1$2") is False


def test_password_hashes_differ_per_salt() -> None:
    assert hash_password("same password") != hash_password("same password")


def test_email_and_password_validation() -> None:
    assert valid_email("ada@example.com") is True
    assert valid_email("  ADA@Example.COM ") is True
    assert valid_email("not-an-email") is False
    assert valid_email("a@b") is False
    assert valid_email("") is False
    assert valid_password("12345678") is True
    assert valid_password("short") is False
    assert valid_password("x" * 129) is False


def test_session_roundtrip_and_tamper() -> None:
    token = create_session_token("user1", "secret", now=1_000_000.0)
    assert read_session_token(token, "secret", now=1_000_100.0) == "user1"
    assert read_session_token(token, "other-secret", now=1_000_100.0) is None
    assert read_session_token(token + "x", "secret", now=1_000_100.0) is None
    assert read_session_token("garbage", "secret", now=1_000_100.0) is None
    assert (
        read_session_token(token, "secret", now=1_000_000.0 + SESSION_MAX_AGE + 1)
        is None
    )
