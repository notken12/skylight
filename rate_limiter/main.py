import time
from threading import Lock
from collections import deque
from typing import List, Deque, Dict, Callable, Annotated
from fastapi import FastAPI, Response, status, Query


class RateLimitBucket:
    window_len: int
    max_reqs: int
    reqs: Deque[int]

    def __init__(self, max_reqs: int, window_len: int):
        self.reqs = deque()
        self.window_len = window_len
        self.max_reqs = max_reqs

    def check_request_validity(self, ts: int) -> bool:
        window_start = ts - self.window_len
        while len(self.reqs) > 0 and self.reqs[0] < window_start:
            self.reqs.popleft()
        if len(self.reqs) + 1 > self.max_reqs:
            return False
        return True

    def handle_request(self, ts: int) -> bool:
        if not self.check_request_validity(ts):
            return False
        self.reqs.append(ts)
        return True


class RateLimiter:
    buckets: Dict[str, RateLimitBucket]
    lock: Lock
    clock: Callable[[], int]

    def __init__(self, clock):
        self.buckets = {"archive:global": RateLimitBucket(100, int(6e10))}
        self.lock = Lock()
        self.clock = clock

    def configure_bucket(self, bucket: str) -> RateLimitBucket | None:
        if bucket.startswith("archive:ip:"):
            return RateLimitBucket(10, int(6e10))

    def handle_request(self, buckets: List[str]) -> bool:
        with self.lock:
            now = self.clock()
            valid = True
            for b in buckets:
                if b not in self.buckets:
                    new_bucket = self.configure_bucket(b)
                    if new_bucket:
                        self.buckets[b] = new_bucket
                    else:
                        # invalid bucket
                        return False
                if not self.buckets[b].check_request_validity(now):
                    valid = False
                    break
            if not valid:
                return False
            for b in buckets:
                if not self.buckets[b].handle_request(now):
                    return False
            return True


rate_limiter = RateLimiter(time.monotonic_ns)

app = FastAPI()


@app.post("/request")
def post_request(buckets: Annotated[List[str], Query()]):
    success = rate_limiter.handle_request(buckets)
    if not success:
        return Response(status_code=status.HTTP_429_TOO_MANY_REQUESTS)
    return Response(status_code=status.HTTP_200_OK)


@app.get(
    "/health",
    tags=["healthcheck"],
    summary="Perform a Health Check",
    response_description="Return HTTP Status Code 200 (OK)",
    status_code=status.HTTP_200_OK,
)
def get_health():
    """
    Liveness probe to verify the server is running.
    """
    return Response(status_code=status.HTTP_200_OK)
