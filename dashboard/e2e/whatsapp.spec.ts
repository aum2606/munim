import { expect, test } from "@playwright/test";
test("owner sees WhatsApp setup and delivery controls without exposing credentials", async ({
  page,
  request,
}, testInfo) => {
  const email = `whatsapp-${crypto.randomUUID()}@example.com`;
  const registration = await request.post(
    "http://localhost:18000/api/v1/auth/register",
    {
      data: {
        business_name: "Demo WhatsApp",
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
  const setup = await (
    await request.get("http://localhost:18000/api/v1/channels/whatsapp/setup", {
      headers,
    })
  ).json();
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("synthetic-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("link", { name: "WhatsApp", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Server setup", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Webhook callback URL")).toHaveValue(
    setup.callback_url,
  );
  await expect(page.getByLabel("Access token")).toHaveAttribute(
    "type",
    "password",
  );
  await expect(
    page.getByRole("heading", { name: "Delivery history", exact: true }),
  ).toBeVisible();
  if (
    !setup.encryption_ready ||
    !setup.webhook_ready ||
    !setup.api_version_ready
  )
    await expect(
      page.getByRole("button", { name: "Verify & connect", exact: true }),
    ).toBeDisabled();
  await expect(page.locator("body")).toHaveJSProperty(
    "scrollWidth",
    await page.evaluate(() => window.innerWidth),
  );
  await page.screenshot({
    path: `.cache/whatsapp-${testInfo.project.name}.png`,
    fullPage: true,
  });
});
