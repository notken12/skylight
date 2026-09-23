from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlencode

ALERTWEST_CAMERAS_URL = "https://api.cdn.prod.alertwest.com/api/firecams/v0/cameras"
USGS_CAMERAS_URL = "https://api.waterdata.usgs.gov/nims/v0/cameras"
FAA_CAMERAS_URL = "https://weathercams.faa.gov/api/sites"
WASHINGTON_QUERY_URL = "https://data.wsdot.wa.gov/arcgis/rest/services/TravelInformation/TravelInfoCamerasWeather/FeatureServer/0/query"
NEBRASKA_QUERY_URL = (
    "https://giscat.ne.gov/dot/rest/services/HighwayCamerasDOT/FeatureServer/0/query"
)
MARYLAND_QUERY_URL = "https://opendata.maryland.gov/resource/4z3c-43ce.json"
IOWA_QUERY_URL = "https://mesonet.agron.iastate.edu/geojson/webcam.geojson"

type FetchJson = Callable[[str], Any]


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
                name=record["name"],
                latitude=float(site["latitude"]),
                longitude=float(site["longitude"]),
                url=f"https://alertwest.live/cam-console/{site['id']}",
                direction=f"{pan}°" if pan is not None else None,
                view_time=image["time"],
                azimuth_degrees=float(pan) if pan is not None else None,
                bearing_tolerance_degrees=20.0 if pan is not None else None,
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
                name=record["camName"],
                latitude=float(record["lat"]),
                longitude=float(record["lng"]),
                url=f"https://apps.usgs.gov/hivis/camera/{quote(record['camId'], safe='')}",
                view_time=record["newestImageDT"],
            )
        )
    return cameras


def faa_cameras(fetch_json: FetchJson) -> list[Camera]:
    cutoff = recent_image_cutoff()
    cameras = []
    for site in fetch_json(FAA_CAMERAS_URL)["payload"]:
        if site["country"] != "US" or not site["siteActive"]:
            continue
        if site["siteInMaintenance"] or not site["validated"]:
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
                    name=f"{site['siteName']} · {camera['cameraDirection']}",
                    latitude=camera["latitude"],
                    longitude=camera["longitude"],
                    url=f"https://weathercams.faa.gov/cameras/cameraSite/{site['siteId']}/details/camera/{camera['cameraId']}",
                    direction=f"{camera['cameraDirection']} ({camera['cameraBearing']}°)",
                    view_time=image_time,
                    azimuth_degrees=camera["cameraBearing"],
                    bearing_tolerance_degrees=camera["mapWedgeAngle"] / 2,
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


def load_cameras(fetch_json: FetchJson, fetch_faa_json: FetchJson) -> list[Camera]:
    providers = (
        (alertwest_cameras, fetch_json),
        (usgs_cameras, fetch_json),
        (faa_cameras, fetch_faa_json),
        (iowa_cameras, fetch_json),
    )
    with ThreadPoolExecutor(max_workers=len(providers)) as executor:
        futures = [
            executor.submit(provider, fetcher) for provider, fetcher in providers
        ]
        return [camera for future in futures for camera in future.result()]
