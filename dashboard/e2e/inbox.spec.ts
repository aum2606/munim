import { expect, test } from "@playwright/test";

test("complaint handoff, private assist and return to AI reach the embedded customer", async ({
  page,
  request,
  context,
}, testInfo) => {
  test.setTimeout(90000);
  const email = `inbox-${crypto.randomUUID()}@example.com`;
  const registered = await request.post(
    "http://localhost:18000/api/v1/auth/register",
    {
      data: {
        business_name: "Demo Support",
        business_type: "printing",
        name: "Demo Owner",
        email,
        password: "synthetic-password",
      },
    },
  );
  expect(registered.status()).toBe(201);
  const tokens = await registered.json();
  const headers = { Authorization: `Bearer ${tokens.access_token}` };
  const tenant = await (
    await request.get("http://localhost:18000/api/v1/tenant", { headers })
  ).json();
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("synthetic-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("link", { name: "Inbox", exact: true }).click();
  const customer = await context.newPage();
  await customer.goto("/login");
  await customer.evaluate(
    ({ key, scriptUrl, api }) =>
      new Promise<void>((resolve, reject) => {
        const script = document.createElement("script");
        script.src = scriptUrl;
        script.dataset.key = key;
        script.dataset.api = api;
        script.onload = () => resolve();
        script.onerror = () => reject(new Error("Widget did not load"));
        document.body.appendChild(script);
      }),
    {
      key: tenant.widget_public_key,
      scriptUrl: tenant.widget_script_url,
      api: tenant.public_api_url,
    },
  );
  await customer.getByRole("button", { name: "Chat with us" }).click();
  await customer.getByRole("button", { name: "Agree & start chat" }).click();
  const message = customer.getByLabel("Message", { exact: true });
  await expect(message).toBeEnabled();
  await message.fill("Complaint: my order is damaged");
  await customer.getByRole("button", { name: "Send", exact: true }).click();
  await expect(customer.getByRole("log")).toContainText(
    "confirm this with the team",
    { timeout: 30000 },
  );
  await expect(page.getByRole("log")).toContainText("damaged", {
    timeout: 15000,
  });
  await expect(page.getByLabel("Staff reply")).toBeEnabled();
  await page
    .getByLabel("Staff reply")
    .fill("I am reviewing your damaged order.");
  await page.getByRole("button", { name: "Send reply", exact: true }).click();
  await expect(customer.getByRole("log")).toContainText(
    "I am reviewing your damaged order.",
  );
  await page
    .getByRole("button", { name: "Use assist mode", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Use assist mode", exact: true }),
  ).toBeDisabled();
  await message.fill("Hello");
  await customer.getByRole("button", { name: "Send", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Private AI drafts" }),
  ).toBeVisible({ timeout: 30000 });
  await expect(customer.getByRole("log")).not.toContainText(
    "Hello! How can I help you?",
  );
  await page
    .getByRole("button", { name: "Approve & send", exact: true })
    .click();
  await expect(customer.getByRole("log")).toContainText(
    "Hello! How can I help you?",
  );
  await page.getByRole("button", { name: "Return to AI", exact: true }).click();
  await expect(page.getByLabel("Staff reply")).toBeDisabled();
  await message.fill("Namaste bhai");
  await customer.getByRole("button", { name: "Send", exact: true }).click();
  await expect(customer.getByRole("log")).toContainText(
    "Namaste! Main aapki kya madad kar sakta hoon?",
    { timeout: 30000 },
  );
  await page.getByRole("link", { name: "Leads", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Lead details" })).toBeVisible(
    { timeout: 15000 },
  );
  await page.getByLabel("Lead stage").selectOption("won");
  await page.getByRole("button", { name: "Save lead", exact: true }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Lead updated" }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Timeline" })).toBeVisible();
  await expect(page.locator("body")).toHaveJSProperty(
    "scrollWidth",
    await page.evaluate(() => window.innerWidth),
  );
  await page.screenshot({
    path: `.cache/leads-${testInfo.project.name}.png`,
    fullPage: true,
  });
  await customer.close();
});
