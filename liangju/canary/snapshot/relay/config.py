"""缺省值。"""

MAX_BATCH = 16  # 一批至多这么多条
FLUSH_INTERVAL = 2.0  # 最早的一条等了这么多秒，不满一批也发
QUEUE_SIZE = 1000  # 队列里至多留这么多条
SEND_TIMEOUT = 30.0  # 一次发送等下游这么多秒
