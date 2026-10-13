export interface SseMessage {
  event: string;
  data: string;
  id?: string;
}

/**
 * Parses a text/event-stream body (WHATWG SSE format). Used instead of EventSource
 * because EventSource cannot send an Authorization header.
 * `onActivity` fires for every chunk, including keep-alive comments.
 */
export async function readEventStream(
  body: ReadableStream<Uint8Array>,
  onMessage: (msg: SseMessage) => void,
  onActivity: () => void,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let event = "";
  let id: string | undefined;
  let data: string[] = [];

  const dispatch = () => {
    if (data.length > 0) onMessage({ event: event || "message", data: data.join("\n"), id });
    event = "";
    data = [];
  };

  const handleLine = (line: string) => {
    if (line === "") {
      dispatch();
      return;
    }
    if (line.startsWith(":")) return; // comment / keep-alive
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
    else if (field === "id" && !value.includes("\0")) id = value;
  };

  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    onActivity();
    buffer += decoder.decode(value, { stream: true });
    for (;;) {
      const match = /\r\n|\r|\n/.exec(buffer);
      // A trailing "\r" may be the first half of "\r\n" split across chunks
      if (!match || (match[0] === "\r" && match.index === buffer.length - 1)) break;
      handleLine(buffer.slice(0, match.index));
      buffer = buffer.slice(match.index + match[0].length);
    }
  }
}
