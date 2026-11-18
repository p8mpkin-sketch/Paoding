// SSE 文本帧解析（纯函数式的小状态机）。取 id、event、data 三个字段。
export type SseMessage = { id: string | null; event: string | null; data: string };

export class SseParser {
  private buf = "";
  private id: string | null = null;
  private data: string[] = [];
  private event: string | null = null;

  feed(chunk: string): SseMessage[] {
    this.buf += chunk;
    const out: SseMessage[] = [];
    for (;;) {
      const m = this.buf.match(/\r\n|\n|\r/);
      if (!m || m.index === undefined) break;
      // 结尾单独一个 \r 可能是 \r\n 的前半，等下一块
      if (m[0] === "\r" && m.index === this.buf.length - 1) break;
      const line = this.buf.slice(0, m.index);
      this.buf = this.buf.slice(m.index + m[0].length);
      if (line === "") {
        if (this.data.length > 0) out.push({ id: this.id, event: this.event, data: this.data.join("\n") });
        this.data = [];
        this.event = null;
        continue;
      }
      if (line.startsWith(":")) continue;
      const c = line.indexOf(":");
      const field = c < 0 ? line : line.slice(0, c);
      const value = c < 0 ? "" : line.slice(c + 1).replace(/^ /, "");
      if (field === "id") this.id = value;
      else if (field === "event") this.event = value;
      else if (field === "data") this.data.push(value);
    }
    return out;
  }
}
