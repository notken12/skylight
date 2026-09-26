from dataclasses import dataclass
from datetime import datetime

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class CloudVolume:
    cloud_fraction: NDArray[np.float32]
    latitudes: NDArray[np.float64]
    longitudes: NDArray[np.float64]
    altitudes_km: NDArray[np.float64]
    valid_time: datetime
    source_url: str
