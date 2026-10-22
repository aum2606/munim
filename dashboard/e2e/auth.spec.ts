import { expect, test } from "@playwright/test";
test("register, sign out, sign in and protect the workspace", async ({
  page,
}) => {
  const email = `owner-${crypto.randomUUID()}@example.com`;
  await page.goto("/");
  await expect(page).toHaveURL(/login/);
  await page
    .getByRole("link", { name: "New to Munim? Create an account" })
    .click();
  await page.getByLabel("Business name").fill("Demo Workshop");
  await page.getByLabel("Business type").fill("printing");
  await page.getByLabel("Your name").fill("Demo Owner");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("demo-password-long");
  await page.getByRole("button", { name: "Create business account" }).click();
  await expect(
    page.getByRole("heading", { name: "Welcome to Munim" }),
  ).toBeVisible();
  await expect(page.locator("body")).toHaveJSProperty(
    "scrollWidth",
    await page.evaluate(() => window.innerWidth),
  );
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/login/);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("demo-password-long");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(
    page.getByRole("heading", { name: "Welcome to Munim" }),
  ).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL(/login/);
});
