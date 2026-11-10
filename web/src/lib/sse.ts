export interface SseMessage {
  event: string;
  data: string;
}

export class SseParser {
  private buffer = "";

  feed(chunk: string): SseMessage[] {
    this.buffer += chunk;
    this.buffer = this.buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    const messages: SseMessage[] = [];
    let boundary = this.buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const block = this.buffer.slice(0, boundary);
      this.buffer = this.buffer.slice(boundary + 2);
      const message = this.parseBlock(block);
      if (message) {
        messages.push(message);
      }
      boundary = this.buffer.indexOf("\n\n");
    }
    return messages;
  }

  private parseBlock(block: string): SseMessage | null {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of block.split("\n")) {
      if (!line || line.startsWith(":")) {
        continue;
      }
      const colon = line.indexOf(":");
      const field = colon >= 0 ? line.slice(0, colon) : line;
      let value = colon >= 0 ? line.slice(colon + 1) : "";
      if (value.startsWith(" ")) {
        value = value.slice(1);
      }
      if (field === "event") {
        event = value;
      } else if (field === "data") {
        dataLines.push(value);
      }
    }
    if (dataLines.length === 0) {
      return null;
    }
    return { event, data: dataLines.join("\n") };
  }
}

export async function* parseSseStream(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<SseMessage> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  try {
    while (true) {
      const result = await reader.read();
      if (result.done) {
        break;
      }
      for (const message of parser.feed(decoder.decode(result.value, { stream: true }))) {
        yield message;
      }
    }
    const tail = decoder.decode();
    if (tail) {
      for (const message of parser.feed(tail)) {
        yield message;
      }
    }
  } finally {
    reader.releaseLock();
  }
}
