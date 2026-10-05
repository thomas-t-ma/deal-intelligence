import pytest

from dealintel.providers.url_tracker import UnsafeUrlError, UrlTrackerProvider


def test_reject_file_scheme():
    with pytest.raises(UnsafeUrlError):
        UrlTrackerProvider._validate_sync("file:///etc/passwd")


def test_reject_localhost():
    with pytest.raises(UnsafeUrlError):
        UrlTrackerProvider._validate_sync("http://localhost:8000/secret")


def test_reject_loopback_ip():
    with pytest.raises(UnsafeUrlError):
        UrlTrackerProvider._validate_sync("http://127.0.0.1:8000/secret")
