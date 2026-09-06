"""ElkRP at-rest encryption: key derivation, RC4 symmetry, string escaping."""

from __future__ import annotations

from elk_programmer.storage.elksafe import BASE_KEY, crypt_columns, crypt_string, derive_key, rc4


def test_derive_key_xors_first_seven_characters() -> None:
    assert derive_key("") == BASE_KEY
    key = derive_key("M1G Defaults")
    assert key[0] == BASE_KEY[0] ^ ord("M")
    assert key[6] == BASE_KEY[6] ^ ord("f")
    assert key[7] == BASE_KEY[7]
    user_key = derive_key("M1G Defaults", "12")
    assert user_key[0] == key[0] ^ ord("1") and user_key[1] == key[1] ^ ord("2")
    assert user_key[2:] == key[2:]


def test_rc4_is_symmetric_and_key_dependent() -> None:
    key = derive_key("Sample Account", "1")
    plain = bytes(range(28))
    cipher = rc4(key, plain)
    assert cipher != plain
    assert rc4(key, cipher) == plain
    assert rc4(derive_key("Sample Account", "2"), cipher) != plain


def test_crypt_columns_and_string() -> None:
    key = derive_key("Acct")
    cols = [3, 4, 5, 6, 0, 0]
    assert crypt_columns(key, crypt_columns(key, cols)) == cols
    text = "00AB12CD"
    assert crypt_string(key, crypt_string(key, text)) == text
    # A NUL in the keystream output is escaped, and the escape decodes back.
    assert crypt_string(key, "[ESC]00") == crypt_string(key, "\x00")
