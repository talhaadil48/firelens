import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import Ask from "./views/Ask";
import { ask } from "./client";
vi.mock("./client", () => ({ ask: vi.fn() }));
vi.mock("./components/ChatChart", () => ({ default: () => null }));
it("stops a request and isolates a new request from late events", async () => {
  let releaseFirst!: () => void, releaseSecond!: () => void;
  const first = new Promise<void>((resolve) => {
    releaseFirst = resolve;
  });
  const second = new Promise<void>((resolve) => {
    releaseSecond = resolve;
  });
  let firstSignal: AbortSignal | undefined;
  vi.mocked(ask)
    .mockImplementationOnce(async function* (_q, signal) {
      firstSignal = signal;
      yield {
        event: "progress",
        data: { stage: "retrieval", message: "First running" },
      };
      await first;
      yield {
        event: "answer",
        data: {
          text: "Stale answer",
          status: "insufficient_evidence",
          citations: [],
          mode: "mock",
        },
      };
    })
    .mockImplementationOnce(async function* () {
      yield {
        event: "progress",
        data: { stage: "retrieval", message: "Second running" },
      };
      await second;
      yield {
        event: "answer",
        data: {
          text: "Current answer",
          status: "insufficient_evidence",
          citations: [],
          mode: "mock",
        },
      };
      yield { event: "done", data: { finish_reason: "insufficient_evidence" } };
    });
  render(<Ask records={[]} />);
  fireEvent.change(
    screen.getByLabelText("What would you like to understand?"),
    { target: { value: "flame spread" } },
  );
  fireEvent.click(screen.getByRole("button", { name: /Search evidence/ }));
  await screen.findByText("First running");
  fireEvent.click(screen.getByRole("button", { name: "Stop request" }));
  expect(firstSignal?.aborted).toBe(true);
  expect(
    screen.queryByText("Retrieving and checking evidence…"),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Search evidence/ }));
  await screen.findByText("Second running");
  releaseFirst();
  await waitFor(() =>
    expect(screen.queryByText("Stale answer")).not.toBeInTheDocument(),
  );
  expect(
    screen.getByRole("button", { name: "Stop request" }),
  ).toBeInTheDocument();
  releaseSecond();
  await screen.findByText("Current answer");
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: "Stop request" }),
    ).not.toBeInTheDocument(),
  );
});
it("sends multiple selected investigation IDs and lets users remove or clear them", async () => {
  const { readFileSync } = await import("node:fs");
  const fixture = JSON.parse(readFileSync("public/fixtures.json", "utf8"));
  vi.mocked(ask).mockReset();
  vi.mocked(ask).mockImplementation(async function* () {
    yield {
      event: "answer",
      data: {
        text: "No matching evidence",
        status: "insufficient_evidence",
        citations: [],
        mode: "mock",
      },
    };
    yield { event: "done", data: { finish_reason: "insufficient_evidence" } };
  });
  render(<Ask records={fixture.investigations.items} />);
  fireEvent.change(screen.getByLabelText("Search scope"), {
    target: { value: "PSI-69" },
  });
  fireEvent.change(screen.getByLabelText("Search scope"), {
    target: { value: "PSI-25" },
  });
  expect(
    screen.getByRole("button", { name: "Remove PSI-69 from selected investigations" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Remove PSI-25 from selected investigations" }),
  ).toBeInTheDocument();
  fireEvent.change(
    screen.getByLabelText("What would you like to understand?"),
    { target: { value: "Compare these studies" } },
  );
  fireEvent.click(screen.getByRole("button", { name: /Search evidence/ }));
  await screen.findByText("No matching evidence");
  expect(ask).toHaveBeenCalledWith(
    "Compare these studies",
    expect.any(AbortSignal),
    ["PSI-69", "PSI-25"],
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Clear scope" })).toBeEnabled(),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Remove PSI-69 from selected investigations" }),
  );
  expect(
    screen.queryByRole("button", { name: "Remove PSI-69 from selected investigations" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Clear scope" }));
  expect(
    screen.queryByRole("button", { name: "Remove PSI-25 from selected investigations" }),
  ).not.toBeInTheDocument();
});
