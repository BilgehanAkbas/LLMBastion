import os

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-secret-that-is-long-enough-for-tests",
)

from pydantic import ValidationError

from app.routers.auth import CreateUserRequest


def test_registration_payload_does_not_accept_role():
    try:
        CreateUserRequest(
            username="demo",
            email="demo@example.com",
            first_name="Demo",
            last_name="User",
            password="password",
            phone_number="555",
            role="admin",
        )
    except ValidationError:
        return

    raise AssertionError("role should not be accepted from the client")
