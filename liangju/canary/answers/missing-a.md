# 回答

## 攒批

1. 队列里攒够 16 条就发一批（`relay/config.py` 的 `MAX_BATCH = 16`，判断在 `relay/sender.py` 的 `Sender.due`）。
2. 不满一批时，最早的一条等了 2.0 秒也发（`FLUSH_INTERVAL = 2.0`，同在 `Sender.due`）。
3. 一批至多取 16 条（`Sender.tick` 里 `self.queue.take(MAX_BATCH)`）。

## 队列满

1. 队列至多留 1000 条（`relay/config.py` 的 `QUEUE_SIZE = 1000`）。
2. 满了就丢最早的一条给新来的让位，生产的一方不会被挡住（`relay/queue.py` 的 `BoundedQueue.put`）。
3. 丢掉的条数记在 `dropped` 上（`BoundedQueue.put` 里 `self.dropped += 1`）。
