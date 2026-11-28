"""攒批与发送。"""

import logging
from collections.abc import Callable

from relay.config import FLUSH_INTERVAL, MAX_BATCH, SEND_TIMEOUT
from relay.queue import BoundedQueue

LOG = logging.getLogger("relay")


class Sender:
    def __init__(self, post: Callable[[list[bytes], float], None], queue: BoundedQueue | None = None) -> None:
        self._post = post
        self.queue = queue or BoundedQueue()
        self.failed = 0  # 发送失败而丢掉的条数

    def due(self, now: float) -> bool:
        """该不该发：攒够一批，或者最早的一条已经等够了。"""
        return len(self.queue) >= MAX_BATCH or (len(self.queue) > 0 and self.queue.oldest_age(now) >= FLUSH_INTERVAL)

    def tick(self, now: float) -> int:
        """发一批（如果该发）。回发出去的条数。"""
        if not self.due(now):
            return 0
        batch = self.queue.take(MAX_BATCH)
        try:
            self._post(batch, SEND_TIMEOUT)
        except OSError as e:
            # 发不出去就记一笔、丢掉这一批：不放回队列，也不再试。下游恢复后只会收到之后的消息。
            self.failed += len(batch)
            LOG.warning("这一批 %d 条没有发出去，已丢弃：%s", len(batch), e)
            return 0
        return len(batch)
