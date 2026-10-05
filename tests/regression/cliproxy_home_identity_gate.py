"""Native consumer identity/revocation gate for the exact Home/CPA pins.

Explicitly run: ./validate.sh tests tests/regression/cliproxy_home_identity_gate.py
Uses the existing recovery fixture, local internal Docker and synthetic keys.
The default handoff suite does not collect this Docker-dependent filename.
"""
from __future__ import annotations

import pytest

from cliproxy_home_recovery_gate import (  # noqa: F401 - home_cpa_pair is a fixture
    LEGACY_KEY, MANAGEMENT_KEY, MODEL, home_cpa_pair,
)

pytestmark = pytest.mark.serial


def require(condition: bool, stage: str) -> None:
    if not condition:
        pytest.fail(stage, pytrace=False)


def keys(pair):
    status, result = pair.request(pair.home_url + "/access/api-keys", MANAGEMENT_KEY)
    require(status == 200, "native identity listing")
    return result["items"]


def attributed(pair, identities: set[int]) -> bool:
    status, result = pair.request(pair.home_url + "/usage/records?limit=200&status=success", MANAGEMENT_KEY)
    if status != 200:
        return False
    return identities <= {row["client"]["api_key_id"] for row in result["items"] if row["model"] == MODEL}


def test_native_consumer_identities_and_revocation(home_cpa_pair):
    try:
        verify_identities(home_cpa_pair)
    except Exception:
        # Never expose exception text, request objects or response bodies.
        pytest.fail("native consumer identity/revocation gate", pytrace=False)


def verify_identities(pair) -> None:
    state = pair.directory("state")
    pair.native(state, "-import", "-config", "/recovery/source/config.yaml",
        "-auth-dir", "/recovery/source/auth", stage="synthetic identity import")
    pair.start_home(state)

    imported = keys(pair)
    require(len(imported) == 1 and imported[0]["api_key"] == LEGACY_KEY, "literal legacy import")
    legacy = imported[0]
    status, _ = pair.request(pair.home_url + "/access/api-keys", MANAGEMENT_KEY, "PATCH",
        {"id": legacy["id"], "display_name": "legacy-shared"})
    require(status == 200, "individual legacy label update")
    renamed = keys(pair)
    require(len(renamed) == 1 and renamed[0]["id"] == legacy["id"] and renamed[0]["api_key"] == LEGACY_KEY
        and renamed[0]["display_name"] == "legacy-shared", "legacy label keeps its ID and value")

    credentials = [f"synthetic-identity-{index}" for index in range(3)]
    records = []
    for index, credential in enumerate(credentials):
        name = f"synthetic-consumer-{index}"
        status, result = pair.request(pair.home_url + "/access/api-keys", MANAGEMENT_KEY, "POST",
            {"api_key": credential, "display_name": name, "user_id": None, "channels": [], "model_groups": []})
        require(status == 201, "individual named identity creation")
        record = result["api_key"]
        require(record["display_name"] == name and record["user_id"] is None
            and record["channels"] == [] and record["model_groups"] == [], "named unowned unrestricted identity")
        records.append(record)
    ids = {legacy["id"], *(record["id"] for record in records)}
    require(len(ids) == 4 and {record["id"] for record in keys(pair)} == ids, "distinct stable identities without list replacement")

    node = pair.enroll()
    pair.start_cpa(pair.directory("cpa-cache"))
    pair.wait(lambda: pair.connected(node), "identity pair enrollment readiness")
    pair.wait(lambda: pair.chat(LEGACY_KEY), "imported legacy request readiness")
    for credential in credentials:
        require(pair.chat(credential), "each identity serves through the shared provider")
    pair.wait(lambda: attributed(pair, ids), "native usage attribution by stable identity")
    status, aggregates = pair.request(pair.home_url + "/usage/aggregates?group_by=client_key", MANAGEMENT_KEY)
    require(status == 200 and ids <= {item["metadata"]["api_key_id"] for item in aggregates["items"]
        if item["label"] == "api-key-" + str(item["metadata"]["api_key_id"])},
        "native aggregate stable IDs with api-key-ID display labels")

    revoked = records[2]["id"]
    status, _ = pair.request(pair.home_url + "/access/api-keys?id=" + str(revoked), MANAGEMENT_KEY, "DELETE")
    require(status == 200, "individual sacrificial deletion by stable ID")
    status, _ = pair.request(pair.cpa_url + "/chat/completions", credentials[2], "POST",
        {"model": MODEL, "messages": [{"role": "user", "content": "new after deletion"}]})
    require(status == 401, "next independent request rejected after deletion")
    require({record["id"] for record in keys(pair)} == ids - {revoked}, "only sacrificial identity deleted")
    for credential in [LEGACY_KEY, *credentials[:2]]:
        require(pair.chat(credential), "other named and legacy identities remain usable")
