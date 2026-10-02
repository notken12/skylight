from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from threading import Lock
from typing import Any, Protocol
from urllib.parse import quote, urlencode

from backend import weather_source
from backend.camera.camera_models import Camera, CameraSnapshot
from backend.camera.faa_snapshots import FAA_REFERER, fetch_latest_image
from backend.weather_source import HttpResponse, parse_utc_time
from backend.weather_source import fetch_response as fetch_http_response

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
type FetchResponse = Callable[[str, str | None], HttpResponse]
type FetchHeaders = Callable[[str], dict[str, str]]


class CameraNetwork(Protocol):
    name: str

    def list_cameras(self) -> list[Camera]: ...

    def get_camera(self, id: str) -> Camera | None: ...

    def fetch_latest_snapshot(self, id: str) -> CameraSnapshot: ...


class CameraCatalog(CameraNetwork):
    def __init__(self, network: str, cameras: Iterable[Camera]) -> None:
        self.name = network
        self._cameras: dict[str, Camera] = {}
        for camera in cameras:
            if camera.network != network:
                raise ValueError(
                    f"Camera belongs to {camera.network}, expected {network}"
                )
            if camera.provider_id is None:
                raise ValueError(f"Camera lacks provider ID: {network} {camera.name}")
            if camera.provider_id in self._cameras:
                raise ValueError(
                    f"Duplicate camera provider ID in {network}: {camera.provider_id}"
                )
            self._cameras[camera.provider_id] = camera

    def list_cameras(self) -> list[Camera]:
        return list(self._cameras.values())

    def get_camera(self, id: str) -> Camera | None:
        return self._cameras.get(id)

    def _require_camera(self, id: str) -> Camera:
        return self._cameras[id]

    def fetch_latest_snapshot(self, id: str) -> CameraSnapshot:
        self._require_camera(id)
        raise NotImplementedError(f"{self.name} does not support still-image snapshots")


class CameraDatabase:
    def __init__(self, networks: Iterable[CameraNetwork]) -> None:
        self._networks: dict[str, CameraNetwork] = {}
        for network in networks:
            if network.name in self._networks:
                raise ValueError(f"Duplicate camera network: {network.name}")
            self._networks[network.name] = network

    def list_cameras(self, network: str | None = None) -> list[Camera]:
        if network is None:
            return [
                camera
                for camera_network in self._networks.values()
                for camera in camera_network.list_cameras()
            ]
        camera_network = self._networks.get(network)
        if camera_network is None:
            return []
        return camera_network.list_cameras()

    def get_camera(self, network: str, id: str) -> Camera | None:
        camera_network = self._networks.get(network)
        if camera_network is None:
            return None
        return camera_network.get_camera(id)

    def fetch_latest_snapshot(self, network: str, id: str) -> CameraSnapshot:
        return self._networks[network].fetch_latest_snapshot(id)


def arcgis_url(base_url: str, parameters: dict[str, str]) -> str:
    return f"{base_url}?{urlencode(parameters)}"


def recent_image_cutoff() -> str:
    return (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")


class AlertWestNetwork(CameraCatalog):
    def __init__(
        self, fetch_json: FetchJson, fetch_response: FetchResponse = fetch_http_response
    ) -> None:
        self._fetch_json = fetch_json
        self._fetch_response = fetch_response
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
        super().__init__("ALERTWest", cameras)

    def fetch_latest_snapshot(self, id: str) -> CameraSnapshot:
        camera = self._require_camera(id)
        for record in self._fetch_json(ALERTWEST_CAMERAS_URL):
            if str(record["site"]["id"]) != id:
                continue
            image = record["image"]
            if image["url"] is None or image["time"] is None:
                raise ValueError(f"No current image for ALERTWest camera {id}")
            response = self._fetch_response(image["url"], None)
            return CameraSnapshot(camera, response.body, image["time"], image["url"])
        raise ValueError(f"ALERTWest camera {id} is no longer in the provider feed")


class USGSNetwork(CameraCatalog):
    def __init__(
        self, fetch_json: FetchJson, fetch_response: FetchResponse = fetch_http_response
    ) -> None:
        self._fetch_json = fetch_json
        self._fetch_response = fetch_response
        cutoff = recent_image_cutoff()
        cameras = []
        self._image_directories: dict[str, str] = {}
        for record in fetch_json(USGS_CAMERAS_URL):
            if "hideCam" not in record or record["hideCam"]:
                continue
            if "newestImageDT" not in record or record["newestImageDT"] is None:
                continue
            if record["newestImageDT"][:19] < cutoff:
                continue
            self._image_directories[record["camId"]] = record["smallDir"]
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
        super().__init__("USGS HIVIS", cameras)

    def fetch_latest_snapshot(self, id: str) -> CameraSnapshot:
        camera = self._require_camera(id)
        url = "https://api.waterdata.usgs.gov/nims/v0/listFiles?" + urlencode(
            {"camId": id, "limit": "1", "recent": "true", "rawItem": "true"}
        )
        images = self._fetch_json(url)
        if not images:
            raise ValueError(f"No current image for USGS camera {id}")
        image = images[0]
        image_url = self._image_directories[id] + image["filename"]
        captured_at = datetime.strptime(
            image["timestamp"], "%Y-%m-%dT%H-%M-%SZ"
        ).replace(tzinfo=UTC)
        response = self._fetch_response(image_url, None)
        return CameraSnapshot(camera, response.body, captured_at.isoformat(), image_url)


class FAANetwork(CameraCatalog):
    def __init__(
        self, fetch_json: FetchJson, fetch_response: FetchResponse = fetch_http_response
    ) -> None:
        self._fetch_json = fetch_json
        self._fetch_response = fetch_response
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
        super().__init__("FAA WeatherCams", cameras)

    def fetch_latest_snapshot(self, id: str) -> CameraSnapshot:
        camera = self._require_camera(id)
        if camera.camera_id is None:
            raise ValueError("FAA camera ID is required for snapshot retrieval")
        image = fetch_latest_image(
            camera.camera_id, datetime.now(UTC), self._fetch_json
        )
        response = self._fetch_response(image["imageUri"], FAA_REFERER)
        return CameraSnapshot(
            camera, response.body, image["imageDatetime"], image["imageUri"]
        )


class WashingtonDOTNetwork(CameraCatalog):
    def __init__(
        self, fetch_json: FetchJson, fetch_response: FetchResponse = fetch_http_response
    ) -> None:
        self._fetch_response = fetch_response
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
        super().__init__("Washington DOT", cameras)

    def fetch_latest_snapshot(self, id: str) -> CameraSnapshot:
        camera = self._require_camera(id)
        response = self._fetch_response(camera.url, None)
        return CameraSnapshot(camera, response.body, None, camera.url)


class NebraskaDOTNetwork(CameraCatalog):
    def __init__(
        self, fetch_json: FetchJson, fetch_response: FetchResponse = fetch_http_response
    ) -> None:
        self._fetch_response = fetch_response
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
        super().__init__("Nebraska DOT", cameras)

    def fetch_latest_snapshot(self, id: str) -> CameraSnapshot:
        camera = self._require_camera(id)
        response = self._fetch_response(camera.url, None)
        return CameraSnapshot(camera, response.body, None, camera.url)


class MarylandCHARTNetwork(CameraCatalog):
    def __init__(
        self, fetch_json: FetchJson, fetch_response: FetchResponse = fetch_http_response
    ) -> None:
        self._fetch_response = fetch_response
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
        super().__init__("Maryland CHART", cameras)

    def fetch_latest_snapshot(self, id: str) -> CameraSnapshot:
        camera = self._require_camera(id)
        response = self._fetch_response(camera.url, None)
        return CameraSnapshot(camera, response.body, None, camera.url)


class IowaMesonetNetwork(CameraCatalog):
    def __init__(
        self, fetch_json: FetchJson, fetch_response: FetchResponse = fetch_http_response
    ) -> None:
        self._fetch_json = fetch_json
        self._fetch_response = fetch_response
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
        super().__init__("Iowa Mesonet", cameras)

    def fetch_latest_snapshot(self, id: str) -> CameraSnapshot:
        camera = self._require_camera(id)
        for feature in self._fetch_json(IOWA_QUERY_URL)["features"]:
            properties = feature["properties"]
            if properties["cid"] != id:
                continue
            response = self._fetch_response(properties["url"], None)
            return CameraSnapshot(
                camera, response.body, properties["valid"], properties["url"]
            )
        raise ValueError(f"Iowa Mesonet camera {id} is no longer in the provider feed")


class UCalgaryTRExNetwork(CameraCatalog):
    def __init__(
        self,
        fetch_json: FetchJson,
        fetch_headers: FetchHeaders,
        fetch_response: FetchResponse = fetch_http_response,
    ) -> None:
        self._fetch_response = fetch_response
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
        super().__init__("UCalgary TREx RGB", cameras)

    def fetch_latest_snapshot(self, id: str) -> CameraSnapshot:
        camera = self._require_camera(id)
        image_url = UCALGARY_LATEST_URL.format(id=quote(id, safe=""))
        response = self._fetch_response(image_url, None)
        captured_at = parse_utc_time(response.headers["x-rt-stream-last-updated-utc"])
        return CameraSnapshot(camera, response.body, captured_at.isoformat(), image_url)


class AuroraMAXNetwork(CameraCatalog):
    def __init__(
        self,
        fetch_headers: FetchHeaders,
        fetch_response: FetchResponse = fetch_http_response,
    ) -> None:
        self._fetch_response = fetch_response
        headers = fetch_headers(AURORAMAX_IMAGE_URL)
        captured_at = parsedate_to_datetime(headers["last-modified"]).astimezone(UTC)
        if captured_at < datetime.now(UTC) - timedelta(hours=1):
            super().__init__("AuroraMAX", [])
            return
        cameras = [
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
        super().__init__("AuroraMAX", cameras)

    def fetch_latest_snapshot(self, id: str) -> CameraSnapshot:
        camera = self._require_camera(id)
        response = self._fetch_response(AURORAMAX_IMAGE_URL, None)
        captured_at = parsedate_to_datetime(
            response.headers["last-modified"]
        ).astimezone(UTC)
        return CameraSnapshot(
            camera, response.body, captured_at.isoformat(), AURORAMAX_IMAGE_URL
        )


class ExploreNetwork(CameraCatalog):
    def __init__(self) -> None:
        cameras = [
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
            )
        ]
        super().__init__("Explore.org", cameras)


class UAFAllskyNetwork(CameraCatalog):
    def __init__(self) -> None:
        cameras = [
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
        ]
        super().__init__("UAF Allsky", cameras)


class AthabascaAuroraCamNetwork(CameraCatalog):
    def __init__(self) -> None:
        cameras = [
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
            )
        ]
        super().__init__("Athabasca AuroraCam", cameras)


def load_camera_database(
    fetch_json: FetchJson, fetch_faa_json: FetchJson, fetch_headers: FetchHeaders
) -> CameraDatabase:
    with ThreadPoolExecutor(max_workers=7) as executor:
        futures = [
            executor.submit(AlertWestNetwork, fetch_json),
            executor.submit(USGSNetwork, fetch_json),
            executor.submit(FAANetwork, fetch_faa_json),
            executor.submit(IowaMesonetNetwork, fetch_json),
            executor.submit(UCalgaryTRExNetwork, fetch_json, fetch_headers),
            executor.submit(AuroraMAXNetwork, fetch_headers),
            executor.submit(ExploreNetwork),
            executor.submit(UAFAllskyNetwork),
            executor.submit(AthabascaAuroraCamNetwork),
        ]
        networks: list[CameraNetwork] = [future.result() for future in futures]
    return CameraDatabase(networks)


_camera_database: CameraDatabase | None = None
_camera_database_lock = Lock()


def get_camera_database() -> CameraDatabase:
    global _camera_database
    with _camera_database_lock:
        if _camera_database is None:
            _camera_database = load_camera_database(
                weather_source.fetch_json,
                weather_source.fetch_faa_json,
                weather_source.fetch_headers,
            )
        return _camera_database
