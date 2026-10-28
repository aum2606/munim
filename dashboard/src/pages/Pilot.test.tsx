import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { pilotApi, type OnboardingState } from "../api/pilot";
import { knowledgeApi } from "../api/knowledge";
import { quotesApi } from "../api/quotes";
import { OnboardingPage } from "./Onboarding";
import { PrivacyPage } from "./Privacy";
import type { ReactNode } from "react";
vi.mock("./Knowledge", () => ({
  KnowledgePage: () => <p>Knowledge editor</p>,
}));
vi.mock("./Playground", () => ({
  PlaygroundPage: () => <p>Grounded chat tester</p>,
}));
let state: OnboardingState;
function mount(content: ReactNode) {
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
      <MemoryRouter>{content}</MemoryRouter>
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  state = {
    profile_ready: true,
    catalog_ready: true,
    knowledge_ready: true,
    tax_profile_ready: true,
    playground_tested: true,
    completed: false,
    preferences: {
      category: "printing",
      tone: "friendly",
      languages: ["en"],
      business_hours: {},
    },
  };
  vi.spyOn(api, "me").mockResolvedValue({
    id: "u",
    tenant_id: "t",
    name: "Owner",
    email: "synthetic@example.com",
    role: "owner",
  });
  vi.spyOn(pilotApi, "state").mockImplementation(async () => state);
  vi.spyOn(quotesApi, "profile").mockResolvedValue({
    name: "Synthetic",
    address: "Demo market",
    phone: "+919000000001",
    state_code: "24",
    gstin: null,
  });
  vi.spyOn(knowledgeApi, "tenant").mockResolvedValue({
    id: "t",
    name: "Synthetic",
    business_type: "printing",
    model_mode: "fake",
    public_api_url: "https://demo.example",
    widget_script_url: "https://demo.example/widget.js",
    widget_public_key: "public-widget-key",
  });
});
afterEach(() => vi.restoreAllMocks());
it("gates incomplete setup and finishes only after the server accepts readiness", async () => {
  const complete = vi
    .spyOn(pilotApi, "complete")
    .mockResolvedValue({ ...state, completed: true });
  state = { ...state, profile_ready: false };
  mount(<OnboardingPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Next step" }));
  expect(await screen.findByRole("alert")).toBeTruthy();
  state = { ...state, profile_ready: true };
  for (let index = 0; index < 4; index++) {
    fireEvent.click(screen.getByRole("button", { name: "Next step" }));
    await waitFor(() =>
      expect(
        screen.getByRole("heading", {
          name: [
            "Catalogue & FAQs",
            "Preferences",
            "Test an answer",
            "Publish",
          ][index],
        }),
      ).toBeTruthy(),
    );
  }
  expect(
    (screen.getByLabelText("Widget installation script") as HTMLTextAreaElement)
      .value,
  ).toContain("public-widget-key");
  fireEvent.click(screen.getByRole("button", { name: "Finish setup" }));
  expect(
    await screen.findByText("Your business setup is complete."),
  ).toBeTruthy();
  expect(complete).toHaveBeenCalledOnce();
});
it("requires an explicit reviewed customer selection before erasure", async () => {
  let customers = [
    { id: "customer", name: "Synthetic customer", phone: null, email: null },
  ];
  vi.spyOn(pilotApi, "customers").mockImplementation(async () => customers);
  const erase = vi.spyOn(pilotApi, "erase").mockImplementation(async () => {
    customers = [];
    return { id: "erasure", status: "complete", files_remaining: 0 };
  });
  mount(<PrivacyPage />);
  await screen.findByRole("option", { name: "Synthetic customer" });
  expect(
    (
      screen.getByRole("button", {
        name: "Erase customer data",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  fireEvent.change(screen.getByLabelText("Customer record"), {
    target: { value: "customer" },
  });
  expect(erase).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Erase customer data" }));
  expect(await screen.findByText("Customer data erased.")).toBeTruthy();
  expect(erase).toHaveBeenCalledWith("customer");
});
it("does not expose owner controls to staff", async () => {
  vi.mocked(api.me).mockResolvedValue({
    id: "u",
    tenant_id: "t",
    name: "Staff",
    email: "synthetic@example.com",
    role: "staff",
  });
  mount(<PrivacyPage />);
  expect(
    await screen.findByText(
      "The business owner manages setup and customer erasure.",
    ),
  ).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Erase customer data" }),
  ).toBeNull();
});
