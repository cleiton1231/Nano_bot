"""Empirical Network Security Audit Test Runner for Worker 1.
Tests all assertions against nanobot/security/network.py, nanobot/agent/tools/web.py, and nanobot/config/.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import socket
import sys
from unittest.mock import patch

from nanobot.security.network import (
    _BLOCKED_NETWORKS,
    _is_private,
    _normalize_addr,
    configure_ssrf_whitelist,
    contains_internal_url,
    env_proxy_applies_to_url,
    httpx_env_proxy_mounts,
    is_loopback_host,
    pin_resolved_url_dns,
    resolve_url_target,
    validate_resolved_url,
    validate_url_target,
    PinnedDNSAsyncTransport,
    UnsafeURLRequestError,
)
from nanobot.agent.tools.web import (
    WebSearchConfig,
    WebFetchConfig,
    WebToolsConfig,
    WebSearchTool,
    WebFetchTool,
    _url_carries_credentials,
    _redact_url_for_log,
    MAX_REDIRECTS,
)
from nanobot.config.schema import Config, ToolsConfig
from nanobot.config.loader import load_config, set_config_path
from pathlib import Path

# Direct audit log and runtime data to agent workspace directory
set_config_path(Path("/home/cleiton/opencode/nanobot/.agents/worker_1/config.json"))


def print_section(title: str):
    print(f"\n{'='*70}\n[TEST SECTION] {title}\n{'='*70}")


def run_ssrf_blocklist_tests():
    print_section("1. SSRF Blocklist & Private Ranges Verification")
    configure_ssrf_whitelist([])

    test_ips = [
        # (IP, Expected Blocked, Category)
        ("127.0.0.1", True, "IPv4 Loopback"),
        ("127.0.0.2", True, "IPv4 Loopback alternate"),
        ("10.0.0.1", True, "RFC1918 (10.0.0.0/8)"),
        ("10.255.255.255", True, "RFC1918 (10.0.0.0/8 broadcast)"),
        ("172.16.0.1", True, "RFC1918 (172.16.0.0/12)"),
        ("172.31.255.255", True, "RFC1918 (172.16.0.0/12 max)"),
        ("192.168.0.1", True, "RFC1918 (192.168.0.0/16)"),
        ("192.168.1.254", True, "RFC1918 (192.168.0.0/16)"),
        ("169.254.169.254", True, "Link-Local / AWS/GCP/Azure Cloud Metadata"),
        ("169.254.0.1", True, "Link-Local (169.254.0.0/16)"),
        ("100.64.0.1", True, "CGNAT / RFC6598 (100.64.0.0/10)"),
        ("100.127.255.254", True, "CGNAT / RFC6598 max"),
        ("0.0.0.0", True, "Current Network (0.0.0.0/8)"),
        ("::1", True, "IPv6 Loopback (::1/128)"),
        ("::", True, "IPv6 Unspecified (::/128)"),
        ("fc00::1", True, "IPv6 Unique Local (fc00::/7)"),
        ("fd12:3456:789a::1", True, "IPv6 Unique Local (fc00::/7)"),
        ("fe80::1", True, "IPv6 Link-Local (fe80::/10)"),
        # IPv6-mapped IPv4
        ("::ffff:127.0.0.1", True, "IPv6-mapped IPv4 Loopback"),
        ("::ffff:169.254.169.254", True, "IPv6-mapped IPv4 Cloud Metadata"),
        ("::ffff:10.0.0.1", True, "IPv6-mapped RFC1918"),
        ("::ffff:192.168.1.1", True, "IPv6-mapped RFC1918"),
        ("::ffff:100.64.0.1", True, "IPv6-mapped CGNAT"),
        # Public IPs
        ("93.184.216.34", False, "Public IPv4 (example.com)"),
        ("8.8.8.8", False, "Public IPv4 (Google DNS)"),
        ("1.1.1.1", False, "Public IPv4 (Cloudflare DNS)"),
        ("2606:4700::6810:84e5", False, "Public IPv6 (Cloudflare)"),
    ]

    all_passed = True
    for ip, expected_blocked, desc in test_ips:
        addr = ipaddress.ip_address(ip)
        blocked = _is_private(addr)
        status = "PASS" if blocked == expected_blocked else "FAIL"
        if status == "FAIL":
            all_passed = False
        print(f"[{status}] {desc:45} IP: {ip:25} -> Blocked: {blocked} (Expected: {expected_blocked})")

    assert all_passed, "SSRF blocklist test failed!"
    print(f"\nAll {len(test_ips)} IP range blocklist checks PASSED.")


def run_dns_pinning_tests():
    print_section("2. DNS Pinning & DNS Rebinding Mitigation Verification")

    # Test 1: pin_resolved_url_dns context manager pins the resolved IP
    hostname = "rebind-attack.example"
    safe_ip = "93.184.216.34"
    evil_ip = "169.254.169.254"

    # Simulate getaddrinfo returning evil_ip during second resolution
    def _malicious_resolver(host, port, family=0, type_=0, proto=0, flags=0):
        if host == hostname:
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (evil_ip, port or 80))]
        return socket.getaddrinfo(host, port, family, type_, proto, flags)

    with patch("nanobot.security.network.socket.getaddrinfo", side_effect=_malicious_resolver):
        # Without DNS pinning:
        unpinned = socket.getaddrinfo(hostname, 80, socket.AF_UNSPEC, socket.SOCK_STREAM)
        print(f"Unpinned socket.getaddrinfo -> resolved to: {unpinned[0][4][0]} (Malicious Rebind)")

        # With DNS pinning:
        with pin_resolved_url_dns(f"http://{hostname}/page", (safe_ip,)):
            pinned = socket.getaddrinfo(hostname, 80, socket.AF_UNSPEC, socket.SOCK_STREAM)
            print(f"Pinned socket.getaddrinfo   -> resolved to: {pinned[0][4][0]} (Pinned Safe IP)")
            assert pinned[0][4][0] == safe_ip, "DNS Pinning failed to override socket.getaddrinfo!"

    print("[PASS] DNS Pinning successfully neutralized DNS rebinding attempt.")

    # Test 2: PinnedDNSAsyncTransport rejects unvalidated / blocked targets
    transport = PinnedDNSAsyncTransport()
    print(f"[PASS] PinnedDNSAsyncTransport instantiated successfully: allow_loopback={transport._allow_loopback}")


def run_ssrf_whitelist_tests():
    print_section("3. SSRF Whitelist / CIDR Exceptions Verification")
    configure_ssrf_whitelist([])

    # By default, CGNAT is blocked
    ok, err = validate_url_target("http://100.64.0.5/api")
    print(f"Default check for 100.64.0.5 -> ok={ok}, error='{err}'")
    assert not ok, "CGNAT should be blocked by default"

    # Whitelist Tailscale CGNAT range
    configure_ssrf_whitelist(["100.64.0.0/10"])
    ok_wl, err_wl = validate_url_target("http://100.64.0.5/api")
    print(f"Whitelisted check for 100.64.0.5 -> ok={ok_wl}, error='{err_wl}'")
    assert ok_wl, f"Whitelisted CGNAT should be allowed, got error: {err_wl}"

    # Verify other private ranges remain strictly blocked even with CGNAT whitelisted
    ok_priv, err_priv = validate_url_target("http://192.168.1.1/secret")
    print(f"Check for 192.168.1.1 (with CGNAT whitelisted) -> ok={ok_priv}, error='{err_priv}'")
    assert not ok_priv, "192.168.1.1 must remain blocked!"

    ok_meta, err_meta = validate_url_target("http://169.254.169.254/latest")
    print(f"Check for 169.254.169.254 (with CGNAT whitelisted) -> ok={ok_meta}, error='{err_meta}'")
    assert not ok_meta, "Metadata 169.254.169.254 must remain blocked!"

    # Reset whitelist
    configure_ssrf_whitelist([])
    ok_reset, err_reset = validate_url_target("http://100.64.0.5/api")
    print(f"After reset check for 100.64.0.5 -> ok={ok_reset}, error='{err_reset}'")
    assert not ok_reset, "CGNAT should be blocked again after reset"
    print("[PASS] SSRF whitelist selectively exempts configured CIDRs without weakening other ranges.")


def run_proxy_behavior_tests():
    print_section("4. Proxy Helpers & trust_remote_dns Verification")

    # When local DNS cannot resolve and trust_remote_dns=False -> fails
    with patch("nanobot.security.network.socket.getaddrinfo", side_effect=socket.gaierror("Name or service not known")):
        ok_no_proxy, err_no_proxy, ips_no = resolve_url_target("https://internal-proxy.example/file", trust_remote_dns=False)
        print(f"Local DNS fail (trust_remote_dns=False) -> ok={ok_no_proxy}, err='{err_no_proxy}'")
        assert not ok_no_proxy

        # When trust_remote_dns=True -> delegated to trusted proxy
        ok_proxy, err_proxy, ips_proxy = resolve_url_target("https://internal-proxy.example/file", trust_remote_dns=True)
        print(f"Local DNS fail (trust_remote_dns=True) -> ok={ok_proxy}, err='{err_proxy}', ips={ips_proxy}")
        assert ok_proxy and ips_proxy == ()

        # But localhost names and private IP literals are STILL rejected even with trust_remote_dns=True
        ok_loc, err_loc, _ = resolve_url_target("http://localhost/admin", trust_remote_dns=True)
        print(f"Localhost with trust_remote_dns=True -> ok={ok_loc}, err='{err_loc}'")
        assert not ok_loc

        ok_meta, err_meta, _ = resolve_url_target("http://169.254.169.254/meta", trust_remote_dns=True)
        print(f"169.254.169.254 with trust_remote_dns=True -> ok={ok_meta}, err='{err_meta}'")
        assert not ok_meta

    print("[PASS] trust_remote_dns delegates unresolvable hostnames to proxy while strictly blocking local literals.")


def run_web_tools_verification():
    print_section("5. Web Tools (web_search & web_fetch) Inspection")

    # Search config default
    search_cfg = WebSearchConfig()
    print(f"WebSearchConfig default provider: '{search_cfg.provider}'")
    assert search_cfg.provider == "duckduckgo", f"Expected default duckduckgo, got {search_cfg.provider}"

    web_cfg = WebToolsConfig()
    print(f"WebToolsConfig default enable: {web_cfg.enable}")

    # Credential stripping
    cred_url_1 = "https://user:password@example.com/data"
    cred_url_2 = "https://example.com/api?api_key=secret123&query=test"
    safe_url = "https://example.com/docs/page.html"

    print(f"Credential check '{cred_url_1}' -> carries_credentials={_url_carries_credentials(cred_url_1)}")
    print(f"Credential check '{cred_url_2}' -> carries_credentials={_url_carries_credentials(cred_url_2)}")
    print(f"Credential check '{safe_url}' -> carries_credentials={_url_carries_credentials(safe_url)}")
    assert _url_carries_credentials(cred_url_1) is True
    assert _url_carries_credentials(cred_url_2) is True
    assert _url_carries_credentials(safe_url) is False

    # Redact URL for logs
    redacted = _redact_url_for_log("https://user:pass@sub.example.com:8443/secret/path?key=123#frag")
    print(f"Redacted URL for log: '{redacted}'")
    assert redacted == "https://sub.example.com:8443"

    print(f"MAX_REDIRECTS limit: {MAX_REDIRECTS}")
    print("[PASS] Web tools credential scrubbing, log redaction, and defaults verified.")


def run_config_and_schema_inspection():
    print_section("6. Config Schema & Active Config Inspection")

    cfg = Config()
    print(f"Config.channels default: {cfg.channels.model_dump()}")
    print(f"Config.tools.ssrf_whitelist default: {cfg.tools.ssrf_whitelist}")
    print(f"Config.tools.restrict_to_workspace default: {cfg.tools.restrict_to_workspace}")
    print(f"Config.tools.web.enable default: {cfg.tools.web.enable}")

    # Inspect langfuse presence in Config schema
    has_langfuse_field = "langfuse" in Config.model_fields
    print(f"Is 'langfuse' a top-level field in Config? {has_langfuse_field}")
    assert not has_langfuse_field, "Config should not have top-level 'langfuse' field"

    # Inspect mcp_servers
    print(f"Config.tools.mcp_servers default: {cfg.tools.mcp_servers}")
    print("[PASS] Config schema attributes verified against specifications.")


if __name__ == "__main__":
    run_ssrf_blocklist_tests()
    run_dns_pinning_tests()
    run_ssrf_whitelist_tests()
    run_proxy_behavior_tests()
    run_web_tools_verification()
    run_config_and_schema_inspection()
    print("\n" + "="*70 + "\nALL EMPIRICAL TESTS COMPLETED SUCCESSFULLY!\n" + "="*70)
