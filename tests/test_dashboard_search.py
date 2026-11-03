"""Search filters and ordering must survive the application database migration."""

from dataclasses import replace

import pytest

from openreporting import dashboards
from openreporting.config import Settings
from openreporting.db import init_db
from openreporting.security import create_user


@pytest.fixture
def env(tmp_path):
    settings = replace(Settings.from_env(), data_dir=tmp_path)
    init_db(settings)
    user = {"id": create_user(settings, "admin1", "an-admin-password-123", "admin"), "role": "admin"}
    other = {"id": create_user(settings, "viewer1", "a-viewer-password-123", "viewer"), "role": "viewer"}
    return settings, user, other


def save(settings, user, uid, title, folder_uid=None):
    dashboards.save(settings, user, {"uid": uid, "title": title, "panels": []}, folder_uid=folder_uid)


def test_search_is_case_insensitive_and_literal_wildcards_are_escaped(env):
    settings, user, _ = env
    save(settings, user, "literal", r"CPU 90% host_name \ path")
    save(settings, user, "other", "cpu 90X hostXname path")
    assert len(dashboards.search(settings, user, query="cPu")) == 2
    for query in ("90%", "host_", "\\"):
        assert [r["uid"] for r in dashboards.search(settings, user, query=query)] == ["literal"]
    assert dashboards.search(settings, user, query="' OR 1=1 --") == []


def test_search_order_is_stable_for_case_equivalent_titles_and_limit(env):
    settings, user, _ = env
    save(settings, user, "z-title", "alpha")
    save(settings, user, "a-title", "ALPHA")
    save(settings, user, "b-title", "Beta")
    assert [r["uid"] for r in dashboards.search(settings, user)] == ["a-title", "z-title", "b-title"]
    assert [r["uid"] for r in dashboards.search(settings, user, limit=1)] == ["a-title"]


def test_combined_star_folder_and_query_filters_are_user_scoped(env):
    settings, user, other = env
    folder = dashboards.save_folder(settings, user, "Servers")["uid"]
    save(settings, user, "match", "CPU Servers", folder_uid=folder)
    save(settings, user, "outside", "CPU Outside")
    dashboards.star(settings, user, "match")
    dashboards.star(settings, user, "outside")
    assert [r["uid"] for r in dashboards.search(settings, user, query="cpu", folder_uid=folder, starred=True)] == ["match"]
    assert dashboards.search(settings, other, query="cpu", folder_uid=folder, starred=True) == []
    assert [r["uid"] for r in dashboards.search(settings, user, folder_uid="", starred=True)] == ["outside"]
