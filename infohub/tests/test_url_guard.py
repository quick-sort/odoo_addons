from unittest import mock

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.infohub.url_guard import UrlNotAllowed, assert_url_allowed


@tagged("post_install", "-at_install")
class TestUrlGuard(TransactionCase):
    """SSRF guard. No network: DNS resolution is patched out."""

    def _getaddrinfo(self, *addresses):
        """Patch socket.getaddrinfo to resolve to the given addresses."""
        infos = [(2, 1, 6, "", (addr, 0)) for addr in addresses]
        return mock.patch("socket.getaddrinfo", return_value=infos)

    # -- scheme ---------------------------------------------------------

    def test_rejects_non_http_schemes(self):
        for url in ("file:///etc/passwd", "gopher://x/", "ftp://x/y"):
            with self.subTest(url=url), self.assertRaises(UrlNotAllowed):
                assert_url_allowed(url, resolve=False)

    def test_rejects_empty_and_hostless(self):
        for url in ("", "   ", "http://", "https:///path"):
            with self.subTest(url=url), self.assertRaises(UrlNotAllowed):
                assert_url_allowed(url, resolve=False)

    def test_accepts_public_http(self):
        with self._getaddrinfo("93.184.216.34"):
            self.assertTrue(assert_url_allowed("http://example.com/feed"))

    # -- literal / known-local hostnames ---------------------------------

    def test_rejects_localhost_names_without_dns(self):
        for host in ("localhost", "LOCALHOST", "foo.localhost"):
            with self.subTest(host=host), self.assertRaises(UrlNotAllowed):
                assert_url_allowed(f"http://{host}/", resolve=False)

    def test_rejects_literal_private_ips(self):
        for ip in ("127.0.0.1", "10.0.0.1", "192.168.1.1", "169.254.169.254"):
            with self.subTest(ip=ip), self.assertRaises(UrlNotAllowed):
                assert_url_allowed(f"http://{ip}/", resolve=False)

    def test_rejects_ipv4_mapped_ipv6(self):
        """::ffff:10.0.0.1 must not slip through as a non-private IPv6."""
        with self.assertRaises(UrlNotAllowed):
            assert_url_allowed("http://[::ffff:10.0.0.1]/", resolve=False)

    # -- resolution ------------------------------------------------------

    def test_rejects_hostname_resolving_to_private(self):
        """A public-looking name pointing inward is still blocked."""
        with self._getaddrinfo("10.1.2.3"), self.assertRaises(UrlNotAllowed):
            assert_url_allowed("http://evil.example.com/")

    def test_blocks_when_any_resolved_address_is_private(self):
        """Multi-homed DNS: one bad address is enough to refuse."""
        with self._getaddrinfo("93.184.216.34", "127.0.0.1"), self.assertRaises(
            UrlNotAllowed
        ):
            assert_url_allowed("http://mixed.example.com/")

    def test_unresolvable_hostname_is_rejected(self):
        import socket as _socket

        with mock.patch("socket.getaddrinfo", side_effect=_socket.gaierror("nope")):
            with self.assertRaises(UrlNotAllowed):
                assert_url_allowed("http://nowhere.invalid/")

    def test_resolve_false_skips_dns(self):
        """Save-time checks must not perform DNS lookups at all."""
        with mock.patch("socket.getaddrinfo") as patched:
            assert_url_allowed("http://example.com/feed", resolve=False)
            patched.assert_not_called()

    def test_allow_private_escape_hatch(self):
        with self._getaddrinfo("127.0.0.1"):
            self.assertTrue(
                assert_url_allowed("http://localhost/", allow_private=True)
            )
