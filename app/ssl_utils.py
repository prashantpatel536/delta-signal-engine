"""TLS / CA bundle helpers for reliable HTTPS on VPS and local dev."""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_LINUX_CA_BUNDLES = (
    "/etc/ssl/certs/ca-certificates.crt",  # Debian/Ubuntu
    "/etc/pki/tls/certs/ca-bundle.crt",    # RHEL/CentOS
    "/etc/ssl/cert.pem",                   # Alpine/macOS
)


def resolve_ca_bundle() -> str | bool:
    """
    Return a CA bundle path for requests ``verify=`` parameter.

    Prefers certifi, then common system paths, then True (requests default).
    """
    env_path = os.getenv("SSL_CERT_FILE") or os.getenv("REQUESTS_CA_BUNDLE")
    if env_path and Path(env_path).is_file():
        return env_path

    try:
        import certifi

        certifi_path = certifi.where()
        if Path(certifi_path).is_file():
            return certifi_path
        logger.warning("certifi bundle missing at %s", certifi_path)
    except ImportError:
        logger.warning("certifi not installed — falling back to system CA bundle")

    for candidate in _LINUX_CA_BUNDLES:
        if Path(candidate).is_file():
            logger.info("Using system CA bundle: %s", candidate)
            return candidate

    logger.warning("No explicit CA bundle found; using requests default verify=True")
    return True


def configure_requests_session(session) -> str | bool:
    """Attach verify path to a requests Session and return the path used."""
    verify = resolve_ca_bundle()
    session.verify = verify
    return verify


def ssl_diagnostics() -> dict[str, str | bool]:
    """Health/debug payload for CA configuration."""
    verify = resolve_ca_bundle()
    certifi_path = ""
    certifi_exists = False
    try:
        import certifi

        certifi_path = certifi.where()
        certifi_exists = Path(certifi_path).is_file()
    except ImportError:
        pass

    return {
        "verify_path": str(verify) if verify is not True else "requests-default",
        "certifi_path": certifi_path,
        "certifi_exists": certifi_exists,
        "ssl_cert_file_env": os.getenv("SSL_CERT_FILE", ""),
        "requests_ca_bundle_env": os.getenv("REQUESTS_CA_BUNDLE", ""),
    }
