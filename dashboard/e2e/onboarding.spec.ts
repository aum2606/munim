import { expect, test } from "@playwright/test";

test("fresh business completes the setup wizard and manages customer privacy", async ({
  page,
  request,
}, testInfo) => {
  const started = Date.now();
  const email = `pilot-${crypto.randomUUID()}@example.com`;
  const registration = await request.post(
    "http://localhost:18000/api/v1/auth/register",
    {
      data: {
        business_name: "Pilot Printing",
        business_type: "printing",
        name: "Demo Owner",
        email,
        password: "synthetic-password",
      },
    },
  );
  expect(registration.status()).toBe(201);
  const token = await registration.json();
  const headers = { Authorization: `Bearer ${token.access_token}` };
  await page.goto("/login");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill("synthetic-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("link", { name: "Business setup", exact: true }).click();
  await page
    .getByLabel("Business address", { exact: true })
    .fill("Synthetic Demo market");
  await page
    .getByLabel("Business contact phone", { exact: true })
    .fill("+919000000001");
  await page.getByLabel("Supplier state code", { exact: true }).fill("24");
  await page
    .getByLabel("GSTIN (if registered)", { exact: true })
    .fill("24AAAAA0000A1Z5");
  await page.getByRole("button", { name: "Save details", exact: true }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Saved" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Next step", exact: true }).click();
  await page.getByLabel("Upload catalogue", { exact: true }).setInputFiles({
    name: "pilot.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(
      "sku,name,price,gst_rate\nCARD,Visiting cards,450,18\n",
    ),
  });
  await page
    .getByRole("button", { name: "Confirm & import", exact: true })
    .click();
  await page
    .getByLabel("Question", { exact: true })
    .fill("What artwork do you accept?");
  await page
    .getByLabel("Answer", { exact: true })
    .fill("We accept print-ready PDF artwork.");
  await page.getByRole("button", { name: "Save FAQ", exact: true }).click();
  await expect
    .poll(async () => {
      const response = await request.get(
        "http://localhost:18000/api/v1/onboarding",
        { headers },
      );
      return (await response.json()).knowledge_ready;
    })
    .toBe(true);
  await page.getByRole("button", { name: "Next step", exact: true }).click();
  await page
    .getByRole("button", { name: "Save preferences", exact: true })
    .click();
  await page.getByRole("button", { name: "Next step", exact: true }).click();
  await page
    .getByRole("button", { name: "Start test conversation", exact: true })
    .click();
  await expect(page.getByLabel("Message", { exact: true })).toBeEnabled();
  await page
    .getByLabel("Message", { exact: true })
    .fill("Visiting cards price");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByRole("log")).toContainText("₹450.00");
  await page.getByRole("button", { name: "Next step", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Finish setup", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Finish setup", exact: true }).click();
  await expect(
    page.getByText("Your business setup is complete.", { exact: true }),
  ).toBeVisible();
  expect(Date.now() - started).toBeLessThan(30 * 60 * 1000);
  await page.screenshot({
    path: `.cache/setup-${testInfo.project.name}.png`,
    fullPage: true,
  });
  await page
    .getByRole("link", { name: "Customer privacy", exact: true })
    .click();
  const select = page.getByRole("combobox", {
    name: "Customer record",
    exact: true,
  });
  await expect(select.locator("option")).toHaveCount(2);
  await select.selectOption({ index: 1 });
  await expect(
    page.getByRole("button", { name: "Erase customer data", exact: true }),
  ).toBeDisabled();
  await page.getByRole("checkbox").check();
  await page
    .getByRole("button", { name: "Erase customer data", exact: true })
    .click();
  await expect(
    page.getByText("Customer data erased.", { exact: true }),
  ).toBeVisible();
  await expect(page.locator("body")).toHaveJSProperty(
    "scrollWidth",
    await page.evaluate(() => window.innerWidth),
  );
});
