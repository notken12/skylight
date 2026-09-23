import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin
from urllib.request import Request, urlopen

NOAA_DIRECTORY = "https://mrms.ncep.noaa.gov/ProbSevere/PROBSEVERE/"
IOWA_ARCHIVE = "https://mtarchive.geol.iastate.edu/"
PROBSEVERE_FILENAME = re.compile(r"MRMS_PROBSEVERE_(\d{8}_\d{6})\.json")
USER_AGENT = "Skylight storm-map prototype (public-data research)"
FAA_WEATHERCAMS_REFERER = "https://weathercams.faa.gov/"


def fetch_bytes(url: str, referer: str | None = None) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    if referer is not None:
        headers["Referer"] = referer
    request = Request(url, headers=headers)
    with urlopen(request, timeout=30) as response:
        return response.read()


def fetch_text(url: str, referer: str | None = None) -> str:
    return fetch_bytes(url, referer).decode("utf-8")


def fetch_json(url: str) -> Any:
    return json.loads(fetch_text(url))


def fetch_faa_json(url: str) -> Any:
    return json.loads(fetch_text(url, referer=FAA_WEATHERCAMS_REFERER))


def parse_utc_time(value: str) -> datetime:
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError(
            "--at must include a UTC timezone, such as 2026-09-21T20:00:00Z"
        )
    return instant.astimezone(UTC)


def probsevere_source(at: datetime | None, fetch_index: Callable[[str], str]) -> str:
    if at is None:
        directory = NOAA_DIRECTORY
        cutoff = None
    else:
        directory = urljoin(IOWA_ARCHIVE, f"{at:%Y/%m/%d}/mrms/ncep/ProbSevere/")
        cutoff = at.strftime("%Y%m%d_%H%M%S")

    timestamps = set(PROBSEVERE_FILENAME.findall(fetch_index(directory)))
    if cutoff is not None:
        timestamps = {timestamp for timestamp in timestamps if timestamp <= cutoff}
    if not timestamps:
        raise ValueError(
            f"No ProbSevere snapshot found in {directory} at or before {at}"
        )

    return urljoin(directory, f"MRMS_PROBSEVERE_{max(timestamps)}.json")
