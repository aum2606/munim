import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "./App";
import { setTokens } from "./api/client";
vi.mock("./components/Notifications", () => ({ Notifications: () => null }));
function mount(path = "/") {
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
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
beforeEach(() => setTokens(null));
afterEach(() => vi.unstubAllGlobals());
it("protects the workspace", () => {
  mount();
  expect(screen.getByRole("heading", { name: "Sign in" })).toBeTruthy();
});
it("logs in and renders the owner shell", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            access_token: "access",
            refresh_token: "refresh",
            token_type: "bearer",
          }),
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            name: "Demo Owner",
            id: "u",
            tenant_id: "t",
            email: "owner@example.test",
            role: "owner",
          }),
        ),
      ),
  );
  mount("/login");
  fireEvent.change(screen.getByLabelText("Email"), {
    target: { value: "owner@example.test" },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: "demo-password-long" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  expect(
    await screen.findByRole("heading", { name: "Welcome to Munim" }),
  ).toBeTruthy();
});
it("shows a useful login error", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response("{}", { status: 401 })),
  );
  mount("/login");
  fireEvent.submit(
    screen.getByRole("button", { name: "Sign in" }).closest("form")!,
  );
  expect(await screen.findByRole("alert")).toBeTruthy();
});
it("shows business registration fields", () => {
  mount("/register");
  expect(screen.getByLabelText("Business name")).toBeTruthy();
  expect(screen.getByLabelText("Password").getAttribute("minlength")).toBe(
    "12",
  );
});
