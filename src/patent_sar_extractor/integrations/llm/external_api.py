"""External HTTPS APIs only; DNS is rechecked at the actual socket boundary.

No local LLM endpoint, redirect, proxy or alternative inference implementation is
accepted. The owned HTTP carrier bounds DNS and connection time as well as I/O.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlsplit, urlunsplit

from urllib3.connection import HTTPSConnection
from urllib3.exceptions import NameResolutionError, NewConnectionError


def _public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


def validate_external_endpoint(endpoint: str) -> str:
    """Syntax checks never perform DNS or an API call during a settings save."""
    if (
        not isinstance(endpoint, str)
        or not 1 <= len(endpoint) <= 2048
        or endpoint != endpoint.strip()
        or any(ord(char) < 33 or ord(char) > 126 for char in endpoint)
        or "\\" in endpoint
    ):
        raise ValueError("An external HTTPS API URL is required")
    parsed = urlsplit(endpoint)
    host = (parsed.hostname or "").lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("Invalid API port") from error
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port not in (None, 443)
        or "%" in parsed.netloc
        or re.search(r"(?:^|/)(?:\.|\.\.)(?:/|$)", parsed.path)
        or "%" in parsed.path
    ):
        raise ValueError("Only a public HTTPS API without URL credentials is supported")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if (
            "." not in host
            or host.endswith((".localhost", ".local", ".internal", ".home", ".lan"))
            or host in {"localhost", "metadata.google.internal"}
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host)
            or any(not part or len(part) > 63 for part in host.split("."))
        ):
            raise ValueError("Local LLM services are not supported")
    else:
        if not _public_address(host):
            raise ValueError("Local or private LLM services are not supported")
    return urlunsplit(("https", parsed.netloc.lower(), parsed.path.rstrip("/"), "", ""))


class PublicHTTPSConnection(HTTPSConnection):
    """Pin the validated DNS addresses to connection attempts, retaining TLS SNI.

    Checking an address and then asking requests to resolve the name again would
    permit DNS rebinding. This socket factory validates every returned address,
    and connects directly to that exact sockaddr; TLS still verifies the hostname.
    """

    def _new_conn(self) -> socket.socket:
        host = self._dns_host
        try:
            addresses = socket.getaddrinfo(host, self.port, 0, socket.SOCK_STREAM)
        except socket.gaierror as error:
            raise NameResolutionError(host, self, error) from error
        if not addresses or any(
            item[0] not in {socket.AF_INET, socket.AF_INET6}
            or not _public_address(str(item[4][0]))
            for item in addresses
        ):
            raise NewConnectionError(self, "API DNS resolved to a non-public address")
        failure: OSError | None = None
        for family, kind, protocol, _, address in addresses:
            connection = socket.socket(family, kind, protocol)
            try:
                connection.settimeout(self.timeout)
                for option in self.socket_options or ():
                    connection.setsockopt(*option)
                if self.source_address:
                    connection.bind(self.source_address)
                connection.connect(address)
                return connection
            except OSError as error:
                failure = error
                connection.close()
        raise NewConnectionError(self, "External API connection failed") from failure
