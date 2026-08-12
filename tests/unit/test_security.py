"""
[P0] Unit tests for verify_github_signature (api/src/security.py)

These tests verify the pure HMAC-SHA256 signature validation logic
in isolation — no HTTP, no database, no FastAPI.

Coverage:
  - Valid signature  → True
  - Invalid signature value → False
  - Missing header (None) → False
  - Empty header string → False
  - Missing sha256= prefix → False
  - Correct prefix but wrong digest → False
  - Different secrets → False
  - Body mismatch (tampered payload) → False
"""
import sys
import hmac
import hashlib
from pathlib import Path

import pytest

# Ensure api/src is resolvable
root_dir = Path(__file__).parent.parent.parent
api_dir = root_dir / "api"
if str(api_dir) not in sys.path:
    sys.path.insert(0, str(api_dir))

from src.security import verify_github_signature  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SECRET = "test-webhook-secret-for-unit-tests"


def _make_signature(body: bytes, secret: str = SECRET) -> str:
    """Compute the expected sha256= signature for a body."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


# ---------------------------------------------------------------------------
# [P0] Happy path
# ---------------------------------------------------------------------------


def test_valid_signature_returns_true():
    """[P0] A correctly signed body must be accepted."""
    body = b'{"action": "opened", "issue": {"number": 1}}'
    signature = _make_signature(body)
    assert verify_github_signature(SECRET, body, signature) is True


def test_valid_signature_empty_body():
    """[P0] Empty body with correct signature is accepted (edge: legitimate ping)."""
    body = b""
    signature = _make_signature(body)
    assert verify_github_signature(SECRET, body, signature) is True


# ---------------------------------------------------------------------------
# [P0] Invalid / missing signature header
# ---------------------------------------------------------------------------


def test_none_signature_header_returns_false():
    """[P0] None header must be rejected immediately."""
    body = b'{"action": "test"}'
    assert verify_github_signature(SECRET, body, None) is False


def test_empty_string_signature_returns_false():
    """[P0] Empty string header must be rejected."""
    body = b'{"action": "test"}'
    assert verify_github_signature(SECRET, body, "") is False


def test_missing_sha256_prefix_returns_false():
    """[P0] Header without 'sha256=' prefix must be rejected (AC-2)."""
    body = b'{"action": "test"}'
    digest = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert verify_github_signature(SECRET, body, digest) is False


def test_wrong_prefix_sha1_style_returns_false():
    """[P0] Header using 'sha1=' prefix instead of 'sha256=' must be rejected."""
    body = b'{"action": "test"}'
    digest = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert verify_github_signature(SECRET, body, f"sha1={digest}") is False


def test_malformed_signature_random_string_returns_false():
    """[P0] Completely malformed header must be rejected."""
    body = b'{"action": "test"}'
    assert verify_github_signature(SECRET, body, "not-a-valid-signature") is False


# ---------------------------------------------------------------------------
# [P0] Wrong secret / tampered body
# ---------------------------------------------------------------------------


def test_wrong_secret_returns_false():
    """[P0] Signature computed with a different secret must be rejected."""
    body = b'{"action": "push"}'
    wrong_signature = _make_signature(body, secret="wrong-secret")
    assert verify_github_signature(SECRET, body, wrong_signature) is False


def test_tampered_body_returns_false():
    """[P0] Changing the body after signing must invalidate the signature."""
    original_body = b'{"action": "push"}'
    tampered_body = b'{"action": "push", "injected": true}'
    signature = _make_signature(original_body)
    assert verify_github_signature(SECRET, tampered_body, signature) is False


def test_correct_prefix_but_wrong_digest_returns_false():
    """[P0] sha256= prefix with an incorrect hex value must be rejected."""
    body = b'{"action": "test"}'
    assert verify_github_signature(SECRET, body, "sha256=deadbeefdeadbeef") is False


# ---------------------------------------------------------------------------
# [P1] Additional edge cases
# ---------------------------------------------------------------------------


def test_different_secrets_produce_different_signatures():
    """[P1] Two different secrets produce non-equivalent signatures for the same body."""
    body = b'{"action": "review"}'
    sig_a = _make_signature(body, secret="secret-a")
    sig_b = _make_signature(body, secret="secret-b")
    assert sig_a != sig_b
    assert verify_github_signature("secret-a", body, sig_a) is True
    assert verify_github_signature("secret-a", body, sig_b) is False


def test_unicode_in_body_is_handled_correctly():
    """[P1] Body containing multi-byte unicode must be signed and verified correctly."""
    body = '{"action": "comentario com acentuacao"}'.encode("utf-8")
    signature = _make_signature(body)
    assert verify_github_signature(SECRET, body, signature) is True


def test_large_payload_signature():
    """[P1] Large payload (>64KB) is signed and verified without truncation."""
    body = b'{"data": "' + b"x" * 100_000 + b'"}'
    signature = _make_signature(body)
    assert verify_github_signature(SECRET, body, signature) is True


def test_signature_with_leading_whitespace_is_rejected():
    """[P2] Signature with leading whitespace must be rejected (no implicit strip)."""
    body = b'{"action": "test"}'
    clean_sig = _make_signature(body)
    padded_sig = f" {clean_sig}"
    assert verify_github_signature(SECRET, body, padded_sig) is False
