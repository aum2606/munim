import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { InsightsPage, AnalyticsOverview } from "./Insights";
import {
  insightsApi,
  type InsightAnswer,
  type Overview,
  type AnalyticsResult,
} from "../api/insights";
import type { ReactNode } from "react";

function mount(node: ReactNode) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })
      }
    >
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}
const result = (
  rows: AnalyticsResult["rows"] = [],
  columns: string[] = [],
): AnalyticsResult => ({ rows, columns, total: rows.length, truncated: false });
const answer: InsightAnswer = {
  text: "2 quotes created in this period are currently accepted.",
  table: [{ quote_number: "Q/2026-27/0001", status: "accepted" }],
  columns: ["quote_number", "status"],
  chart_spec: null,
  tool: "quotes_by_status",
  suggested_actions: ["Review the listed records before taking action."],
  period_start: "2026-10-01T00:00:00Z",
  period_end: "2026-10-28T00:00:00Z",
  total: 2,
  truncated: false,
};
const overview: Overview = {
  period_start: answer.period_start,
  period_end: answer.period_end,
  enquiries: 6,
  inbound_messages: 9,
  closed_conversations: 0,
  ai_resolved_conversations: 0,
  ai_resolution_rate_pct: null,
  first_response: result([
    { replied_conversations: 0, median_seconds: null, average_seconds: null },
  ]),
  trend: result(),
  top_items: result(),
  intent_mix: result(),
  funnel: result(),
  channels: result(),
  open_gaps: 3,
};
beforeEach(() => {
  vi.spyOn(insightsApi, "digest").mockResolvedValue(null);
  vi.spyOn(insightsApi, "overview").mockResolvedValue(overview);
});
afterEach(() => vi.restoreAllMocks());
it("asks a sample question and displays exact results and actions", async () => {
  const ask = vi.spyOn(insightsApi, "ask").mockResolvedValue(answer);
  mount(<InsightsPage />);
  fireEvent.click(
    screen.getByRole("button", { name: "How many quotes were accepted?" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Ask" }));
  expect(await screen.findByText(answer.text)).toBeTruthy();
  expect(ask).toHaveBeenCalledWith(
    "How many quotes were accepted?",
    expect.anything(),
  );
  expect(screen.getByText("Q/2026-27/0001")).toBeTruthy();
  expect(screen.getByText(answer.suggested_actions[0])).toBeTruthy();
  expect(await screen.findByText(/Your first digest/)).toBeTruthy();
});
it("shows stored digest and request failures without inventing answers", async () => {
  vi.spyOn(insightsApi, "digest").mockResolvedValue({
    id: "digest",
    week_start: answer.period_start,
    period_end: answer.period_end,
    answer,
  });
  vi.spyOn(insightsApi, "ask").mockRejectedValue(new Error("Unavailable"));
  mount(<InsightsPage />);
  expect(await screen.findByText(answer.text)).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Your business question"), {
    target: { value: "How many quotes were accepted?" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Ask" }));
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.queryByRole("region", { name: "Answer" })).toBeNull();
});
it("filters the overview and distinguishes absent metrics from zero", async () => {
  const query = vi.mocked(insightsApi.overview);
  mount(<AnalyticsOverview />);
  expect(await screen.findByText("6")).toBeTruthy();
  expect(screen.getAllByText("Not enough data")).toHaveLength(2);
  expect(screen.getByText("3")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Reporting period"), {
    target: { value: "this_week" },
  });
  await waitFor(() => expect(query).toHaveBeenCalledWith("this_week"));
});
it("renders chart values as accessible exact tables", async () => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  vi.mocked(insightsApi.overview).mockResolvedValue({
    ...overview,
    top_items: result(
      [{ item: "Visiting cards", enquiries: 3 }],
      ["item", "enquiries"],
    ),
  });
  mount(<AnalyticsOverview />);
  expect(
    await screen.findByRole("img", { name: "Top enquired items" }),
  ).toBeTruthy();
  expect(screen.getByText("Visiting cards")).toBeTruthy();
  vi.unstubAllGlobals();
});
