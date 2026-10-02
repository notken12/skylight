from typing import List
import httpx


class RateLimiterClient:
    path: str

    def __init__(self, path: str):
        self.path = path

    def request(self, buckets: List[str]) -> bool:
        res = httpx.post(self.path, params={"buckets": buckets})
        return res.status_code == 200
