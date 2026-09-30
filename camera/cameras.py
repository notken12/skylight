from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote, urlencode

from weather_source import parse_utc_time

ALERTWEST_CAMERAS_URL = "https://api.cdn.prod.alertwest.com/api/firecams/v0/cameras"
USGS_CAMERAS_URL = "https://api.waterdata.usgs.gov/nims/v0/cameras"
FAA_CAMERAS_URL = "https://weathercams.faa.gov/api/sites"
WASHINGTON_QUERY_URL = "https://data.wsdot.wa.gov/arcgis/rest/services/TravelInformation/TravelInfoCamerasWeather/FeatureServer/0/query"
NEBRASKA_QUERY_URL = (
    "https://giscat.ne.gov/dot/rest/services/HighwayCamerasDOT/FeatureServer/0/query"
)
MARYLAND_QUERY_URL = "https://opendata.maryland.gov/resource/4z3c-43ce.json"
IOWA_QUERY_URL = "https://mesonet.agron.iastate.edu/geojson/webcam.geojson"
UCALGARY_STREAMS_URL = "https://api.phys.ucalgary.ca/api/v1/rt?network=trex_rgb"
UCALGARY_OBSERVATORIES_URL = (
    "https://api.phys.ucalgary.ca/api/v1/data_distribution/observatories"
    "?instrument_array=trex_rgb"
)
UCALGARY_LATEST_URL = "https://api.phys.ucalgary.ca/api/v1/rt/{id}/latest"
AURORAMAX_IMAGE_URL = "https://auroramax.phys.ucalgary.ca/recent/recent_480p.jpg"
AURORAMAX_FEED_URL = "https://auroramax.com/live"

type FetchJson = Callable[[str], Any]
type FetchHeaders = Callable[[str], dict[str, str]]


@dataclass(frozen=True)
class Camera:
    network: str
    name: str
    latitude: float
    longitude: float
    url: str
    direction: str | None = None
    view_time: str | None = None
    azimuth_degrees: float | None = None
    bearing_tolerance_degrees: float | None = None
    camera_id: int | None = None
    snapshot_url: str | None = None
    operated_by: str | None = None
    sky_facing: bool = False
    night_sky_capable: bool = False
    link_only: bool = False
    feed_verified: bool = True
    provider_id: str | None = None


def arcgis_url(base_url: str, parameters: dict[str, str]) -> str:
    return f"{base_url}?{urlencode(parameters)}"


def recent_image_cutoff() -> str:
    return (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")


def alertwest_cameras(fetch_json: FetchJson) -> list[Camera]:
    cutoff = recent_image_cutoff()
    cameras = []
    for record in fetch_json(ALERTWEST_CAMERAS_URL):
        image = record["image"]
        if image["time"] is None or image["url"] is None:
            continue
        if image["time"][:19] < cutoff:
            continue
        site = record["site"]
        pan = record["position"]["pan"]
        cameras.append(
            Camera(
                network="ALERTWest",
                provider_id=str(site["id"]),
                name=record["name"],
                latitude=float(site["latitude"]),
                longitude=float(site["longitude"]),
                url=f"https://alertwest.live/cam-console/{site['id']}",
                direction=f"{pan}°" if pan is not None else None,
                view_time=image["time"],
                azimuth_degrees=float(pan) if pan is not None else None,
                bearing_tolerance_degrees=20.0 if pan is not None else None,
                snapshot_url=image["url"],
            )
        )
    return cameras


def usgs_cameras(fetch_json: FetchJson) -> list[Camera]:
    cutoff = recent_image_cutoff()
    cameras = []
    for record in fetch_json(USGS_CAMERAS_URL):
        if "hideCam" not in record or record["hideCam"]:
            continue
        if "newestImageDT" not in record or record["newestImageDT"] is None:
            continue
        if record["newestImageDT"][:19] < cutoff:
            continue
        cameras.append(
            Camera(
                network="USGS HIVIS",
                provider_id=record["camId"],
                name=record["camName"],
                latitude=float(record["lat"]),
                longitude=float(record["lng"]),
                url=f"https://apps.usgs.gov/hivis/camera/{quote(record['camId'], safe='')}",
                view_time=record["newestImageDT"],
                snapshot_url=f"{record['smallDir']}{record['camId']}_newest.jpg",
            )
        )
    return cameras


def faa_cameras(fetch_json: FetchJson) -> list[Camera]:
    cutoff = recent_image_cutoff()
    cameras = []
    for site in fetch_json(FAA_CAMERAS_URL)["payload"]:
        if site["country"] not in ("US", "CA") or not site["siteActive"]:
            continue
        if site["siteInMaintenance"]:
            continue
        if not site["validated"] and not (
            site["country"] == "CA"
            and site["thirdParty"]
            and site["operatedBy"] == "NAV CANADA"
        ):
            continue
        for camera in site["cameras"]:
            image_time = camera["cameraLastSuccess"]
            if image_time is None or image_time[:19] < cutoff:
                continue
            if camera["cameraInMaintenance"] or camera["cameraOutOfOrder"]:
                continue
            cameras.append(
                Camera(
                    network="FAA WeatherCams",
                    provider_id=str(camera["cameraId"]),
                    name=f"{site['siteName']} · {camera['cameraDirection']}",
                    latitude=camera["latitude"],
                    longitude=camera["longitude"],
                    url=f"https://weathercams.faa.gov/cameras/cameraSite/{site['siteId']}/details/camera/{camera['cameraId']}",
                    direction=f"{camera['cameraDirection']} ({camera['cameraBearing']}°)",
                    view_time=image_time,
                    azimuth_degrees=camera["cameraBearing"],
                    bearing_tolerance_degrees=camera["mapWedgeAngle"] / 2,
                    camera_id=camera["cameraId"],
                    operated_by=site["operatedBy"],
                )
            )
    return cameras


def washington_cameras(fetch_json: FetchJson) -> list[Camera]:
    url = arcgis_url(
        WASHINGTON_QUERY_URL,
        {
            "where": "1=1",
            "outFields": "OBJECTID,CameraTitle,ImageURL,CompassDirection",
            "outSR": "4326",
            "resultRecordCount": "2000",
            "f": "geojson",
        },
    )
    cameras = []
    for feature in fetch_json(url)["features"]:
        properties = feature["properties"]
        if properties["CameraTitle"] is None or properties["ImageURL"] is None:
            continue
        longitude, latitude = feature["geometry"]["coordinates"]
        cameras.append(
            Camera(
                network="Washington DOT",
                provider_id=str(properties["OBJECTID"]),
                name=properties["CameraTitle"],
                latitude=latitude,
                longitude=longitude,
                url=properties["ImageURL"],
                direction=properties["CompassDirection"],
            )
        )
    return cameras


def nebraska_cameras(fetch_json: FetchJson) -> list[Camera]:
    url = arcgis_url(
        NEBRASKA_QUERY_URL,
        {
            "where": "1=1",
            "outFields": "OBJECTID,name,PhotoURL",
            "outSR": "4326",
            "resultRecordCount": "2000",
            "f": "geojson",
        },
    )
    cameras = []
    for feature in fetch_json(url)["features"]:
        properties = feature["properties"]
        if properties["name"] is None or properties["PhotoURL"] is None:
            continue
        longitude, latitude = feature["geometry"]["coordinates"]
        cameras.append(
            Camera(
                network="Nebraska DOT",
                provider_id=str(properties["OBJECTID"]),
                name=properties["name"],
                latitude=latitude,
                longitude=longitude,
                url=properties["PhotoURL"],
            )
        )
    return cameras


def maryland_cameras(fetch_json: FetchJson) -> list[Camera]:
    url = f"{MARYLAND_QUERY_URL}?{urlencode({'$limit': '5000'})}"
    cameras = []
    for record in fetch_json(url):
        if "url" not in record or "location" not in record:
            continue
        longitude, latitude = record["the_geom"]["coordinates"]
        cameras.append(
            Camera(
                network="Maryland CHART",
                provider_id=record["url"],
                name=record["location"],
                latitude=latitude,
                longitude=longitude,
                url=record["url"],
            )
        )
    return cameras


def iowa_cameras(fetch_json: FetchJson) -> list[Camera]:
    cameras = []
    for feature in fetch_json(IOWA_QUERY_URL)["features"]:
        properties = feature["properties"]
        longitude, latitude = feature["geometry"]["coordinates"]
        angle = properties["angle"]
        cameras.append(
            Camera(
                network="Iowa Mesonet",
                provider_id=properties["cid"],
                name=properties["name"],
                latitude=latitude,
                longitude=longitude,
                url=properties["url"],
                direction=f"{angle}°" if angle is not None else None,
                view_time=properties["valid"],
                azimuth_degrees=angle,
                bearing_tolerance_degrees=20.0 if angle is not None else None,
            )
        )
    return cameras


def ucalgary_aurora_cameras(
    fetch_json: FetchJson, fetch_headers: FetchHeaders
) -> list[Camera]:
    streams = [
        stream
        for stream in fetch_json(UCALGARY_STREAMS_URL)["streams"]
        if stream["mimetype"] == "image/jpeg"
    ]
    observatories = {
        site["uid"]: site for site in fetch_json(UCALGARY_OBSERVATORIES_URL)
    }
    with ThreadPoolExecutor(max_workers=8) as executor:
        headers = list(
            executor.map(
                fetch_headers,
                (UCALGARY_LATEST_URL.format(id=stream["id"]) for stream in streams),
            )
        )

    cameras = []
    cutoff = datetime.now(UTC) - timedelta(hours=1)
    for stream, image_headers in zip(streams, headers, strict=True):
        updated_at = parse_utc_time(image_headers["x-rt-stream-last-updated-utc"])
        if updated_at < cutoff:
            continue
        site = observatories[stream["site_uid"]]
        image_url = UCALGARY_LATEST_URL.format(id=stream["id"])
        cameras.append(
            Camera(
                network="UCalgary TREx RGB",
                provider_id=str(stream["id"]),
                name=f"{site['full_name']} · all sky",
                latitude=site["geodetic_latitude"],
                longitude=site["geodetic_longitude"],
                url=image_url,
                view_time=updated_at.isoformat(),
                snapshot_url=f"{image_url}?at={int(updated_at.timestamp())}",
                operated_by="University of Calgary",
                sky_facing=True,
                night_sky_capable=True,
            )
        )
    return cameras


def auroramax_cameras(fetch_headers: FetchHeaders) -> list[Camera]:
    headers = fetch_headers(AURORAMAX_IMAGE_URL)
    captured_at = parsedate_to_datetime(headers["last-modified"]).astimezone(UTC)
    if captured_at < datetime.now(UTC) - timedelta(hours=1):
        return []
    return [
        Camera(
            network="AuroraMAX",
            provider_id=AURORAMAX_FEED_URL,
            name="Yellowknife, NWT · all sky",
            latitude=62 + 26 / 60,
            longitude=-(114 + 21 / 60),
            url=AURORAMAX_FEED_URL,
            view_time=captured_at.isoformat(),
            snapshot_url=f"{AURORAMAX_IMAGE_URL}?at={int(captured_at.timestamp())}",
            operated_by="University of Calgary",
            sky_facing=True,
            night_sky_capable=True,
        )
    ]


def linked_aurora_cameras() -> list[Camera]:
    return [
        Camera(
            network="Explore.org",
            provider_id="churchill-northern-lights",
            name="Churchill Northern Studies Centre, MB · sky view",
            latitude=58.737778,
            longitude=-93.819167,
            url="https://explore.org/livecams/polar-bears/northern-lights-cam",
            operated_by="Explore.org / Churchill Northern Studies Centre",
            sky_facing=True,
            night_sky_capable=True,
            link_only=True,
        ),
        Camera(
            network="UAF Allsky",
            provider_id="poker-flat",
            name="Poker Flat, AK · all sky",
            latitude=65.13,
            longitude=-147.49,
            url="https://allsky.gi.alaska.edu/poker-flat",
            operated_by="University of Alaska Fairbanks",
            sky_facing=True,
            night_sky_capable=True,
            link_only=True,
        ),
        Camera(
            network="UAF Allsky",
            provider_id="toolik-lake",
            name="Toolik Lake, AK · all sky",
            latitude=68 + 37 / 60,
            longitude=-(149 + 36 / 60),
            url="https://allsky.gi.alaska.edu/toolik-lake",
            operated_by="University of Alaska Fairbanks",
            sky_facing=True,
            night_sky_capable=True,
            link_only=True,
        ),
        Camera(
            network="Athabasca AuroraCam",
            provider_id="athabasca-auroracam",
            name="Athabasca County, AB · all sky",
            latitude=54 + 36 / 60 + 10 / 3600,
            longitude=-(113 + 38 / 60 + 40 / 3600),
            url="https://autumn.athabascau.ca/auroracamhd.htm",
            operated_by="Athabasca University",
            sky_facing=True,
            night_sky_capable=True,
            link_only=True,
            feed_verified=False,
        ),
    ]


def load_cameras(
    fetch_json: FetchJson, fetch_faa_json: FetchJson, fetch_headers: FetchHeaders
) -> list[Camera]:
    with ThreadPoolExecutor(max_workers=7) as executor:
        futures = [
            executor.submit(alertwest_cameras, fetch_json),
            executor.submit(usgs_cameras, fetch_json),
            executor.submit(faa_cameras, fetch_faa_json),
            executor.submit(iowa_cameras, fetch_json),
            executor.submit(ucalgary_aurora_cameras, fetch_json, fetch_headers),
            executor.submit(auroramax_cameras, fetch_headers),
            executor.submit(linked_aurora_cameras),
        ]
        return [camera for future in futures for camera in future.result()]
