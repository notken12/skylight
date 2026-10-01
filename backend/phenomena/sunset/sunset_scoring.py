from datetime import datetime

import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import map_coordinates

from backend.phenomena.cloud_volume import CloudVolume

EARTH_RADIUS_KM = 6371.0088


def solar_geometry(
    at: datetime, latitudes: NDArray[np.float64], longitudes: NDArray[np.float64]
) -> tuple[
    NDArray[np.float64], NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]
]:
    day = at.timetuple().tm_yday
    minute = at.hour * 60 + at.minute + at.second / 60
    year_angle = 2 * np.pi / 365 * (day - 1 + (minute / 60 - 12) / 24)
    equation_of_time = 229.18 * (
        0.000075
        + 0.001868 * np.cos(year_angle)
        - 0.032077 * np.sin(year_angle)
        - 0.014615 * np.cos(2 * year_angle)
        - 0.040849 * np.sin(2 * year_angle)
    )
    declination = (
        0.006918
        - 0.399912 * np.cos(year_angle)
        + 0.070257 * np.sin(year_angle)
        - 0.006758 * np.cos(2 * year_angle)
        + 0.000907 * np.sin(2 * year_angle)
        - 0.002697 * np.cos(3 * year_angle)
        + 0.00148 * np.sin(3 * year_angle)
    )
    hour_angle_degrees = ((minute + equation_of_time + 4 * longitudes) / 4) % 360 - 180
    hour_angle = np.deg2rad(hour_angle_degrees)
    latitude = np.deg2rad(latitudes)
    east = -np.cos(declination) * np.sin(hour_angle)
    north = np.cos(latitude) * np.sin(declination) - np.sin(latitude) * np.cos(
        declination
    ) * np.cos(hour_angle)
    up = np.sin(latitude) * np.sin(declination) + np.cos(latitude) * np.cos(
        declination
    ) * np.cos(hour_angle)
    return np.rad2deg(np.arcsin(np.clip(up, -1, 1))), east, north, hour_angle


def sunset_band(
    at: datetime, latitudes: NDArray[np.float64], longitudes: NDArray[np.float64]
) -> NDArray[np.bool_]:
    elevation, _, _, hour_angle = solar_geometry(at, latitudes, longitudes)
    return (hour_angle > 0) & (elevation >= -6) & (elevation <= 2)


def sample_cloud(
    values: NDArray[np.float32],
    volume: CloudVolume,
    altitudes: NDArray[np.float64],
    latitudes: NDArray[np.float64],
    longitudes: NDArray[np.float64],
) -> NDArray[np.float32]:
    altitude_coordinate = (altitudes - volume.altitudes_km[0]) / 0.5
    latitude_coordinate = (volume.latitudes[0] - latitudes) / 0.25
    longitude_coordinate = (longitudes % 360 - volume.longitudes[0]) / 0.25
    coordinates = np.broadcast_arrays(
        altitude_coordinate, latitude_coordinate, longitude_coordinate
    )
    return map_coordinates(values, coordinates, order=1, mode="constant", cval=0)


def ray_location(
    latitudes: NDArray[np.float64],
    longitudes: NDArray[np.float64],
    east: NDArray[np.float64],
    north: NDArray[np.float64],
    distance_km: float,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    latitude = latitudes + np.rad2deg(distance_km * north / EARTH_RADIUS_KM)
    longitude = longitudes + np.rad2deg(
        distance_km * east / (EARTH_RADIUS_KM * np.cos(np.deg2rad(latitudes)))
    )
    return latitude, longitude


def reflection_potential(volume: CloudVolume, at: datetime) -> NDArray[np.float32]:
    latitude, longitude = np.meshgrid(
        volume.latitudes, volume.longitudes, indexing="ij"
    )
    elevation, sun_east, sun_north, _ = solar_geometry(at, latitude, longitude)
    horizontal_norm = np.hypot(sun_east, sun_north)
    sun_east /= horizontal_norm
    sun_north /= horizontal_norm
    sun_slope = np.tan(np.deg2rad(elevation))
    potential = np.empty_like(volume.cloud_fraction)
    for layer, altitude in enumerate(volume.altitudes_km):
        transmittance = np.ones(latitude.shape, dtype=np.float32)
        for distance in range(25, 626, 25):
            ray_latitude, ray_longitude = ray_location(
                latitude, longitude, sun_east, sun_north, distance
            )
            ray_altitude = (
                altitude + distance * sun_slope + distance**2 / (2 * EARTH_RADIUS_KM)
            )
            cover = sample_cloud(
                volume.cloud_fraction, volume, ray_altitude, ray_latitude, ray_longitude
            )
            transmittance *= np.sqrt(1 - np.clip(cover, 0, 1))
        height_weight = 0.35 + 0.65 * min(altitude / 8, 1)
        potential[layer] = volume.cloud_fraction[layer] * transmittance * height_weight
    return potential


def quality_grid(
    volume: CloudVolume, at: datetime
) -> tuple[NDArray[np.uint8], NDArray[np.float64], NDArray[np.float64]]:
    potential = reflection_potential(volume, at)
    output_latitudes = np.arange(50, 24.9, -0.5)
    output_longitudes = np.arange(-125, -65.9, 0.5)
    latitude, longitude = np.meshgrid(
        output_latitudes, output_longitudes, indexing="ij"
    )
    _, sun_east, sun_north, _ = solar_geometry(at, latitude, longitude)
    bearing = np.arctan2(sun_east, sun_north)
    score = np.zeros(latitude.shape, dtype=np.float32)
    for azimuth_offset in (-20, 0, 20):
        direction = bearing + np.deg2rad(azimuth_offset)
        east = np.sin(direction)
        north = np.cos(direction)
        for altitude_angle in (3, 8, 18, 35):
            transmittance = np.ones(latitude.shape, dtype=np.float32)
            ray_score = np.zeros(latitude.shape, dtype=np.float32)
            for distance in range(5, 166, 10):
                ray_latitude, ray_longitude = ray_location(
                    latitude, longitude, east, north, distance
                )
                ray_altitude = distance * np.tan(
                    np.deg2rad(altitude_angle)
                ) + distance**2 / (2 * EARTH_RADIUS_KM)
                cloud = sample_cloud(
                    volume.cloud_fraction,
                    volume,
                    ray_altitude,
                    ray_latitude,
                    ray_longitude,
                )
                reflection = sample_cloud(
                    potential, volume, ray_altitude, ray_latitude, ray_longitude
                )
                ray_score += reflection * transmittance
                transmittance *= np.power(1 - np.clip(cloud, 0, 1), 0.2)
            score += ray_score
    score = 100 * (1 - np.exp(-score / 18))
    score[~sunset_band(at, latitude, longitude)] = 0
    return (
        np.rint(np.clip(score, 0, 100)).astype(np.uint8),
        output_latitudes,
        output_longitudes,
    )
