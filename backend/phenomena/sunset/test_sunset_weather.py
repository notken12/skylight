import unittest
from datetime import UTC, datetime
from email.message import Message
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

from backend.phenomena.sunset.sunset_weather import load_total_cloud_cover


class SunsetWeatherTests(unittest.TestCase):
    def test_missing_gfs_cycle_uses_previous_cycle_for_same_forecast_time(self) -> None:
        urls: list[str] = []

        def fetch(url: str) -> bytes:
            urls.append(url)
            if len(urls) == 1:
                raise HTTPError(url, 404, "Not Found", Message(), None)
            return b"forecast"

        with patch(
            "backend.phenomena.sunset.sunset_weather.read_total_cloud_cover"
        ) as read:
            load_total_cloud_cover(
                datetime(2026, 9, 29, 10, 32, tzinfo=UTC),
                datetime(2026, 9, 29, 10, 1, tzinfo=UTC),
                fetch,
            )

        self.assertEqual(len(urls), 2)
        first = parse_qs(urlparse(urls[0]).query)
        second = parse_qs(urlparse(urls[1]).query)
        self.assertEqual(first["file"], ["gfs.t06z.pgrb2.0p25.f005"])
        self.assertEqual(second["file"], ["gfs.t00z.pgrb2.0p25.f011"])
        self.assertEqual(first["dir"], ["/gfs.20260929/06/atmos"])
        self.assertEqual(second["dir"], ["/gfs.20260929/00/atmos"])
        read.assert_called_once_with(b"forecast", urls[1])

    def test_non_404_http_error_propagates(self) -> None:
        def fetch(url: str) -> bytes:
            raise HTTPError(url, 503, "Unavailable", Message(), None)

        with self.assertRaises(HTTPError) as raised:
            load_total_cloud_cover(
                datetime(2026, 9, 29, 10, tzinfo=UTC),
                datetime(2026, 9, 29, 10, tzinfo=UTC),
                fetch,
            )

        self.assertEqual(raised.exception.code, 503)

    def test_missing_three_cycles_propagates_last_error(self) -> None:
        urls: list[str] = []

        def fetch(url: str) -> bytes:
            urls.append(url)
            raise HTTPError(url, 404, "Not Found", Message(), None)

        with self.assertRaises(HTTPError) as raised:
            load_total_cloud_cover(
                datetime(2026, 9, 29, 10, tzinfo=UTC),
                datetime(2026, 9, 29, 10, tzinfo=UTC),
                fetch,
            )

        self.assertEqual(len(urls), 3)
        self.assertEqual(raised.exception.url, urls[-1])


if __name__ == "__main__":
    unittest.main()
