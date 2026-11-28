# 回答

## 攒批

1. 队列里攒够 64 条就发一批（`relay/config.py` 的 `MAX_BATCH`，判断在 `relay/sender.py` 的 `Sender.due`）。
2. 不满一批时，最早的一条等了 2.0 秒也发（`FLUSH_INTERVAL = 2.0`，同在 `Sender.due`）。

## 队列满

1. 队列至多留 1000 条（`relay/config.py` 的 `QUEUE_SIZE = 1000`）。
2. 满了就丢最早的一条给新来的让位，生产的一方不会被挡住（`relay/queue.py` 的 `BoundedQueue.put`）。

## 重试与退避

1. 题面假定有重试与退避，实际上没有：发送失败后这一批直接丢弃，不放回队列，也不再试（`relay/sender.py` 的 `Sender.tick` 里 `except OSError` 一支）。
2. 失败时只做两件事：把丢掉的条数加到 `failed` 上，并记一条警告日志（同一支）。
3. 仓库里没有任何退避间隔或重试次数的配置（`relay/config.py` 只有批大小、发送间隔、队列长度、发送超时四个值）。
