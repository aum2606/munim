import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { QuotesPage } from "./Quotes";
import { quotesApi, type Quote } from "../api/quotes";
import { knowledgeApi } from "../api/knowledge";
let quote: Quote;
beforeEach(() => {
  quote = {
    id: "q1",
    quote_number: "Q/2026-27/0001",
    conversation_id: "c",
    status: "pending_approval",
    version: 1,
    display_total: "₹3,245.00",
    display_amounts: { subtotal_paise: "₹2,750.00" },
    display_lines: [],
    lines: [
      {
        id: "l",
        sku: "CARD-100",
        description: "Visiting cards",
        qty: "5",
        discount_paise: 0,
        unit: "pack",
        options: { sides: "double-sided" },
        needs_owner_pricing: false,
      },
    ],
    customer_state: null,
    valid_until: "2026-12-20",
  };
  vi.spyOn(quotesApi, "list").mockImplementation(async () => [quote]);
  vi.spyOn(quotesApi, "settings").mockResolvedValue({
    auto_send_quotes: false,
    display_auto_send_limit: "₹0.00",
    quote_validity_days: 7,
    quote_terms: "Valid for seven days.",
  });
  vi.spyOn(quotesApi, "profile").mockResolvedValue({
    name: "Demo",
    gstin: null,
    state_code: "24",
    address: null,
    phone: null,
  });
  vi.spyOn(knowledgeApi, "catalog").mockResolvedValue([
    {
      id: "c",
      sku: "CARD-100",
      name: "Visiting cards",
      display_price: "₹450.00",
      gst_rate: 18,
      unit: "pack",
      is_active: true,
    },
  ]);
});
afterEach(() => vi.restoreAllMocks());
function mount() {
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
      <QuotesPage />
    </QueryClientProvider>,
  );
}
it("requires recalculation before approving a changed quote", async () => {
  const edit = vi.spyOn(quotesApi, "edit").mockImplementation(async () => {
    quote = {
      ...quote,
      version: 2,
      display_total: "₹3,894.00",
      lines: [{ ...quote.lines[0], qty: "6" }],
    };
    return quote;
  });
  const approve = vi
    .spyOn(quotesApi, "approve")
    .mockImplementation(async () => {
      quote = { ...quote, status: "sent" };
      return quote;
    });
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: /Q\/2026-27\/0001/ }),
  );
  fireEvent.change(await screen.findByLabelText("Quantity 1"), {
    target: { value: "6" },
  });
  expect(
    (
      screen.getByRole("button", {
        name: "Approve & send",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Save & recalculate" }));
  await waitFor(() => expect(edit).toHaveBeenCalled());
  await screen.findByText("₹3,894.00");
  fireEvent.click(screen.getByRole("button", { name: "Approve & send" }));
  await waitFor(() =>
    expect(approve).toHaveBeenCalledWith(
      expect.objectContaining({ version: 2 }),
    ),
  );
});
it("blocks approval while a line needs owner pricing", async () => {
  quote = {
    ...quote,
    lines: [{ ...quote.lines[0], needs_owner_pricing: true }],
  };
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: /Q\/2026-27\/0001/ }),
  );
  expect((await screen.findByRole("alert")).textContent).toContain(
    "Owner pricing needed",
  );
  expect(
    (
      screen.getByRole("button", {
        name: "Approve & send",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
});
it("sends the owner-entered INR limit as text for server parsing", async () => {
  const save = vi.spyOn(quotesApi, "saveSettings").mockResolvedValue({});
  mount();
  fireEvent.click(
    await screen.findByLabelText("Automatically send fully priced quotes"),
  );
  fireEvent.change(screen.getByLabelText("Auto-send below (INR)"), {
    target: { value: "10,000" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save quote settings" }));
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith(
      expect.objectContaining({
        auto_send_quotes: true,
        auto_send_limit_inr: "10,000",
      }),
    ),
  );
});

it("preserves existing line and quote discounts while editing quantity", async () => {
  quote = {
    ...quote,
    quote_discount_paise: 500,
    lines: [{ ...quote.lines[0], discount_paise: 1000 }],
  };
  const edit = vi.spyOn(quotesApi, "edit").mockResolvedValue(quote);
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: /Q\/2026-27\/0001/ }),
  );
  fireEvent.change(await screen.findByLabelText("Quantity 1"), {
    target: { value: "6" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save & recalculate" }));
  await waitFor(() =>
    expect(edit).toHaveBeenCalledWith(
      expect.objectContaining({ quote_discount_paise: 500 }),
      [expect.objectContaining({ discount_paise: 1000, qty: "6" })],
      null,
    ),
  );
});
