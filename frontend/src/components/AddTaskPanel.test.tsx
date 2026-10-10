import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AddTaskPanel } from "./AddTaskPanel";
import type { ParseResult } from "../types";
import type * as ApiModule from "../api";

const mocks = vi.hoisted(() => ({ parseInput: vi.fn(), batchCreateTasks: vi.fn() }));
vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof ApiModule>("../api");
  return { ...actual, parseInput: mocks.parseInput, batchCreateTasks: mocks.batchCreateTasks };
});

const result = (id: string): ParseResult => ({
  items: [{ raw: id, manga_id: id, valid: true, status: "ready", title: `Title ${id}`, cover_url: "", page_count: 1, pic_count: 1, source: "wnacg" }],
  summary: { total: 1, valid: 1, duplicate: 0, invalid: 0 },
});

function renderPanel() {
  return render(<AddTaskPanel open onClose={vi.fn()} onCreated={vi.fn(async () => undefined)} />);
}

describe("AddTaskPanel source workflow", () => {
  beforeEach(() => {
    mocks.parseInput.mockReset();
    mocks.batchCreateTasks.mockReset();
  });

  it("invalidates an existing preview when source or input changes", async () => {
    mocks.parseInput.mockResolvedValue(result("123"));
    renderPanel();
    const input = screen.getByLabelText("输入 ID 或链接（支持批量，每行一个）");
    await userEvent.type(input, "123");
    await userEvent.click(screen.getByRole("button", { name: "解析预检" }));
    expect(await screen.findByText("Title 123")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "JMComic" }));
    expect(screen.queryByText("Title 123")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "加入队列" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "解析预检" }));
    expect(mocks.parseInput).toHaveBeenLastCalledWith("123", "jmcomic");
    fireEvent.change(input, { target: { value: "456" } });
    expect(screen.queryByText("Title 123")).not.toBeInTheDocument();
  });

  it("ignores a stale parse response after the source changes", async () => {
    let resolveOld!: (value: ParseResult) => void;
    mocks.parseInput.mockReturnValueOnce(new Promise<ParseResult>((resolve) => { resolveOld = resolve; }));
    renderPanel();
    const input = screen.getByLabelText("输入 ID 或链接（支持批量，每行一个）");
    await userEvent.type(input, "123");
    const parseButton = screen.getByRole("button", { name: "解析预检" });
    void userEvent.click(parseButton);
    await userEvent.click(screen.getByRole("button", { name: "JMComic" }));
    resolveOld(result("stale"));
    await waitFor(() => expect(screen.queryByText("Title stale")).not.toBeInTheDocument());
  });

  it("shows API error details and keeps actions safe while parsing", async () => {
    mocks.parseInput.mockRejectedValue(new Error("API request failed: /api/inputs/parse — source unavailable"));
    renderPanel();
    const input = screen.getByLabelText("输入 ID 或链接（支持批量，每行一个）");
    await userEvent.type(input, "123");
    await userEvent.click(screen.getByRole("button", { name: "解析预检" }));
    expect(await screen.findByText("API request failed: /api/inputs/parse — source unavailable")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "加入队列" })).not.toBeInTheDocument();
  });
});
