"""Offline tests for bot-challenge detection on the IIIF manifest path.

digicoll.lib.berkeley.edu serves its whole site behind an AWS WAF JS
challenge: every plain HTTP client gets HTTP 202 with an empty body and an
`x-amzn-waf-action: challenge` header. That used to surface as "IIIF manifest
不是有效的 JSON", which reads like a wrong manifest template and sends the
reader hunting for a better URL that does not exist.
"""

from bookget.adapters.iiif.base_iiif import BaseIIIFAdapter
from bookget.exceptions import MetadataExtractionError, SiteChallengeError


class TestChallengeSignal:
    def test_aws_waf_header_is_a_challenge(self):
        signal = BaseIIIFAdapter._challenge_signal(
            202, {"x-amzn-waf-action": "challenge"}, b"")
        assert "x-amzn-waf-action: challenge" in signal

    def test_waf_header_counts_even_on_200(self):
        signal = BaseIIIFAdapter._challenge_signal(
            200, {"x-amzn-waf-action": "captcha"}, b"<html>")
        assert signal

    def test_bare_202_with_empty_body_is_a_challenge(self):
        assert BaseIIIFAdapter._challenge_signal(202, {}, b"   ")

    def test_202_with_a_real_body_is_not_a_challenge(self):
        # Don't hijack a site that legitimately answers 202 with content.
        assert BaseIIIFAdapter._challenge_signal(202, {}, b'{"@id": "x"}') == ""

    def test_ordinary_manifest_is_not_a_challenge(self):
        assert BaseIIIFAdapter._challenge_signal(
            200, {"content-type": "application/json"}, b'{"@id": "x"}') == ""

    def test_404_is_not_a_challenge(self):
        # A missing item must keep failing as a missing item.
        assert BaseIIIFAdapter._challenge_signal(404, {}, b"not found") == ""


class TestSiteChallengeError:
    def test_message_names_site_url_and_signal(self):
        err = SiteChallengeError(
            "berkeley",
            "https://digicoll.lib.berkeley.edu/iiif/12345/manifest.json",
            "HTTP 202, x-amzn-waf-action: challenge",
        )
        text = str(err)
        assert "berkeley" in text
        assert "digicoll.lib.berkeley.edu" in text
        assert "x-amzn-waf-action" in text
        # The point of the message: this is not a URL problem.
        assert "与 URL 是否正确无关" in text

    def test_is_a_metadata_error(self):
        """Existing callers catch MetadataExtractionError; stay catchable."""
        assert issubclass(SiteChallengeError, MetadataExtractionError)
