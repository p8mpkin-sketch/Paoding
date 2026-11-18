// 本机墙钟，只给总览的“今天”与分日用（人的时区里的日界）。视图层（model/ui/pages）不直接读时钟，由这里注入。
import { useEffect, useState } from "react";

export function useNow(everyMs = 60_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), everyMs);
    return () => clearInterval(t);
  }, [everyMs]);
  return now;
}
