from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.journey_walker import Outcome, format_line, scrub  # noqa: E402

AUTH_HOST = "auth.faviann.com"
ROMM_ME = "https://romm.public.faviann.com/api/users/me"


def romm_outcome(**overrides) -> Outcome:
    fields = {
        "url": "https://romm.public.faviann.com/api/login/openid",
        "status": 200,
        "final_url": "https://romm.public.faviann.com/",
        "hops": (
            "302:https://romm.public.faviann.com/api/login/openid",
            "302:https://auth.faviann.com/application/o/authorize/",
            "307:https://romm.public.faviann.com/api/oauth/openid",
            "200:https://romm.public.faviann.com/",
        ),
        "elapsed": 1.7,
        "location": "-",
        "content_type": "text/html; charset=utf-8",
        "detail": "OK",
        "body": "<!doctype html>\n<html>\n  <head>",
    }
    fields.update(overrides)
    return Outcome(**fields)


def test_a_signed_in_chain_ending_2xx_prints_a_pass_line_with_its_hops() -> None:
    assert format_line(romm_outcome(), AUTH_HOST) == (
        "PASS https://romm.public.faviann.com/api/login/openid status=200 elapsed=1s"
        " location=- content_type=text/html; charset=utf-8 detail=\"OK\""
        " hops=302:https://romm.public.faviann.com/api/login/openid,"
        "302:https://auth.faviann.com/application/o/authorize/,"
        "307:https://romm.public.faviann.com/api/oauth/openid,"
        "200:https://romm.public.faviann.com/"
        " body=<!doctype html> <html> <head>"
    )


def test_a_chain_that_lands_on_the_sign_in_flow_fails_even_on_200() -> None:
    outcome = romm_outcome(
        final_url="https://auth.faviann.com/if/flow/default-authentication-flow/",
        hops=("302:https://romm.public.faviann.com/api/login/openid",),
    )

    assert format_line(outcome, AUTH_HOST).startswith(
        "FAIL https://romm.public.faviann.com/api/login/openid status=200 "
    )


def test_a_line_carries_no_token_or_cookie_value() -> None:
    token = "Zx81" * 15
    session = "s3ss10n-c00k1e-value"
    outcome = romm_outcome(
        url=ROMM_ME,
        final_url=ROMM_ME,
        hops=(f"200:{ROMM_ME}",),
        content_type="application/json",
        detail=f"echoed {session}",
        body=f'{{"username":"verify-agent","note":"{token}"}}',
    )

    assert scrub(format_line(outcome, AUTH_HOST), [token, session, "en"]) == (
        f"PASS {ROMM_ME} status=200 elapsed=1s location=- content_type=application/json"
        f' detail="echoed <redacted>" hops=200:{ROMM_ME}'
        ' body={"username":"verify-agent","note":"<redacted>"}'
    )
