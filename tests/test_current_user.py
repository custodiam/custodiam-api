"""Tests para el schema CurrentUser."""

from app.schemas.auth import CurrentUser


def test_has_role():
    user = CurrentUser(sub="1", email="a@b.com", roles=["admin", "voluntario"])
    assert user.has_role("admin") is True
    assert user.has_role("coordinador") is False


def test_has_any_role():
    user = CurrentUser(sub="1", email="a@b.com", roles=["jefe_equipo"])
    assert user.has_any_role(["admin", "jefe_equipo"]) is True
    assert user.has_any_role(["admin", "coordinador"]) is False


def test_full_name():
    user = CurrentUser(sub="1", email="a@b.com", given_name="María", family_name="García")
    assert user.full_name == "María García"


def test_full_name_empty():
    user = CurrentUser(sub="1", email="a@b.com")
    assert user.full_name == ""


def test_default_values():
    user = CurrentUser(sub="1", email="a@b.com")
    assert user.roles == []
    assert user.given_name == ""
    assert user.family_name == ""
    assert user.preferred_username == ""


def test_preferred_username():
    user = CurrentUser(sub="1", email="a@b.com", preferred_username="mgarcia")
    assert user.preferred_username == "mgarcia"
