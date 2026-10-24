import { expect, test } from "@playwright/test";
test("owner imports knowledge, tests a guarded answer and reads the inbox", async ({
  page,
}) => {
  await page.goto("/register");
  await page.getByLabel("Business name").fill("Demo Printing");
  await page.getByLabel("Business type").fill("printing");
  await page.getByLabel("Your name").fill("Demo Owner");
  await page
    .getByLabel("Email")
    .fill(`knowledge-${crypto.randomUUID()}@example.com`);
  await page.getByLabel("Password").fill("synthetic-password");
  await page.getByRole("button", { name: "Create business account" }).click();
  await expect(
    page.getByRole("heading", { name: "Welcome to Munim" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Knowledge", exact: true }).click();
  await page.getByLabel("Upload catalogue", { exact: true }).setInputFiles({
    name: "catalog.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("sku,name,price\nCARD,Visiting cards,450\n"),
  });
  await expect(
    page.getByRole("heading", { name: "Import preview" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Confirm & import" }).click();
  await expect(
    page.getByRole("heading", { name: "Catalogue imported" }),
  ).toBeVisible();
  await page
    .getByLabel("Question", { exact: true })
    .fill("What is your warranty policy?");
  await page
    .getByLabel("Answer", { exact: true })
    .fill("One year manufacturer warranty.");
  await page.getByRole("button", { name: "Save FAQ" }).click();
  await expect(
    page
      .getByRole("listitem")
      .filter({ hasText: "What is your warranty policy?" }),
  ).toContainText("ready", { timeout: 30000 });
  await expect(page.locator("body")).toHaveJSProperty(
    "scrollWidth",
    await page.evaluate(() => window.innerWidth),
  );
  await page.getByRole("link", { name: "Playground", exact: true }).click();
  await page.getByRole("button", { name: "Start test conversation" }).click();
  await expect(page.getByLabel("Message", { exact: true })).toBeEnabled();
  await page
    .getByLabel("Message", { exact: true })
    .fill("visiting cards ka rate kya hai");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByRole("log")).toContainText(
    "Visiting cards: \u20b9450.00",
    { timeout: 30000 },
  );
  await expect(
    page.getByRole("complementary").getByText("knowledge", { exact: true }),
  ).toBeVisible({ timeout: 15000 });
  await expect(page.locator("body")).toHaveJSProperty(
    "scrollWidth",
    await page.evaluate(() => window.innerWidth),
  );
  await page.getByRole("link", { name: "Inbox", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Inbox", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("log")).toContainText(
    "visiting cards ka rate kya hai",
  );
  await expect(page.getByRole("log")).toContainText("\u20b9450.00");
  await expect(page.getByLabel("Staff reply")).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Take over", exact: true }),
  ).toBeEnabled();
});
