import { TextDecoder, TextEncoder } from "node:util";

import { authFetch } from "@/lib/api";
import { streamLinkedinPost } from "@/lib/linkedin-api";

jest.mock("@/lib/api", () => ({ authFetch: jest.fn() }));

describe("streamLinkedinPost", () => {
  it("forwards every raw delta even when SSE events cross network chunks", async () => {
    Object.assign(globalThis, { TextDecoder, TextEncoder });
    const encoder = new TextEncoder();
    const rawPost = "  Première ligne\n\nDeuxième ligne 🚀";
    const sse =
      'event: linkedin_start\ndata: {"sources":[]}\n\n' +
      'event: linkedin_delta\ndata: {"content":"  Première ligne\\n\\n"}\n\n' +
      'event: linkedin_delta\ndata: {"content":"Deuxième ligne 🚀"}\n\n' +
      `event: linkedin_done\ndata: ${JSON.stringify({
        post: rawPost,
        character_count: rawPost.length,
        sources: [],
        cost_usd: 0.01,
        duration_ms: 1200,
      })}\n\n`;
    const networkChunks = [
      sse.slice(0, 71),
      sse.slice(71, 143),
      sse.slice(143),
    ];
    let index = 0;
    const releaseLock = jest.fn();
    const reader = {
      read: jest.fn(async () =>
        index < networkChunks.length
          ? { done: false, value: encoder.encode(networkChunks[index++]) }
          : { done: true, value: undefined }
      ),
      releaseLock,
    };
    (authFetch as jest.Mock).mockResolvedValue({
      ok: true,
      body: { getReader: () => reader },
    });

    const received: string[] = [];
    const onDone = jest.fn();
    const onError = jest.fn();
    await streamLinkedinPost("Sujet", "token", {
      onStart: jest.fn(),
      onDelta: (content) => received.push(content),
      onDone,
      onError,
    });

    expect(received).toEqual(["  Première ligne\n\n", "Deuxième ligne 🚀"]);
    expect(received.join("")).toBe(rawPost);
    expect(onDone).toHaveBeenCalledWith(
      expect.objectContaining({ post: rawPost })
    );
    expect(onError).not.toHaveBeenCalled();
    expect(releaseLock).toHaveBeenCalled();
  });
});
