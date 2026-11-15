import { beforeEach, expect, it, vi } from "vitest";

beforeEach(() => {
  vi.resetModules();
  vi.stubEnv("VITE_DATA_MODE", "api");
  vi.stubEnv("VITE_API_BASE_URL", "http://localhost:8017");
});
it("loads all coverage pages and forwards active filters", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({ items: [{ test_id: "first" }], total: 2 }),
    })
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({ items: [{ test_id: "second" }], total: 2 }),
    });
  vi.stubGlobal("fetch", fetch);
  const { getAllTests } = await import("./client");
  expect(await getAllTests(undefined, { accession: "PSI-69" })).toHaveLength(2);
  expect(fetch.mock.calls[1][0]).toContain("offset=1");
  expect(fetch.mock.calls[1][0]).toContain("accession=PSI-69");
});
it("fails visibly if the API ends pagination before the reported total", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ items: [{ test_id: "first" }], total: 2 }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ items: [], total: 2 }),
      }),
  );
  const { getAllTests } = await import("./client");
  await expect(getAllTests()).rejects.toThrow("Incomplete test response");
});
it("parses a UTF-8 SSE stream across arbitrary byte boundaries and CRLF", async () => {
  const text =
    'event: answer\r\ndata: {"text":"O₂ source","status":"insufficient_evidence","citations":[]}\r\n\r\nevent: done\r\ndata: {"finish_reason":"insufficient_evidence"}\r\n\r\n';
  const bytes = new TextEncoder().encode(text);
  const body = new ReadableStream({
    start(controller) {
      for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
      controller.close();
    },
  });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, body }));
  const { ask } = await import("./client");
  const events = [];
  for await (const event of ask("oxygen", undefined, ["PSI-69"]))
    events.push(event);
  expect(events.map((e) => e.event)).toEqual(["answer", "done"]);
  expect(events[0].data).toMatchObject({ text: "O₂ source" });
  expect(JSON.parse(vi.mocked(fetch).mock.calls[0][1]!.body as string)).toEqual(
    { question: "oxygen", investigation_ids: ["PSI-69"] },
  );
});
it("reports HTTP errors from chat including rate limiting", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 429 }));
  const { ask } = await import("./client");
  await expect(ask("oxygen").next()).rejects.toThrow("Chat failed (429)");
});
it("cancels a pending read immediately when Stop aborts the signal", async () => {
  const cancel = vi.fn();
  const body = new ReadableStream({ cancel });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, body }));
  const { ask } = await import("./client");
  const controller = new AbortController();
  const pending = ask("flame spread", controller.signal).next();
  await Promise.resolve();
  controller.abort();
  await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  expect(cancel).toHaveBeenCalled();
});
it("discards buffered answer events after cancellation", async () => {
  const body = new ReadableStream({
    start(c) {
      c.enqueue(
        new TextEncoder().encode(
          'event: progress\ndata: {"stage":"retrieval","message":"Working"}\n\nevent: answer\ndata: {"text":"stale","citations":[]}\n\n',
        ),
      );
    },
  });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, body }));
  const { ask } = await import("./client");
  const controller = new AbortController();
  const stream = ask("flame spread", controller.signal);
  expect((await stream.next()).value?.event).toBe("progress");
  controller.abort();
  await expect(stream.next()).rejects.toMatchObject({ name: "AbortError" });
});
