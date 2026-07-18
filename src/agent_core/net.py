from __future__ import annotations

_TRUST_STORE_READY = False


def use_system_trust_store() -> bool:
    """Route TLS verification through the OS certificate store.

    Corporate networks commonly terminate TLS with an internally-signed
    certificate. That CA lives in the Windows/macOS system trust store but not in
    certifi's bundle, so requests fails with CERTIFICATE_VERIFY_FAILED. Injecting
    truststore fixes this while keeping verification fully enabled - never disable
    certificate verification to work around it.

    Safe to call repeatedly; a no-op when truststore is not installed.
    """
    global _TRUST_STORE_READY
    if _TRUST_STORE_READY:
        return True

    try:
        import truststore
    except ImportError:
        return False

    truststore.inject_into_ssl()
    _TRUST_STORE_READY = True
    return True
