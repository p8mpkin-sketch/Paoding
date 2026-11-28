"""有界队列：满了丢最早的一条。"""

from collections import deque

from relay.config import QUEUE_SIZE


class BoundedQueue:
    def __init__(self, size: int = QUEUE_SIZE) -> None:
        self._items: deque[tuple[float, bytes]] = deque()
        self._size = size
        self.dropped = 0  # 因为队列满而丢掉的条数

    def put(self, now: float, message: bytes) -> None:
        if len(self._items) >= self._size:
            self._items.popleft()  # 丢最早的一条，给新来的让位；生产的一方从不被挡住
            self.dropped += 1
        self._items.append((now, message))

    def oldest_age(self, now: float) -> float:
        return now - self._items[0][0] if self._items else 0.0

    def take(self, n: int) -> list[bytes]:
        out = []
        while self._items and len(out) < n:
            out.append(self._items.popleft()[1])
        return out

    def __len__(self) -> int:
        return len(self._items)
