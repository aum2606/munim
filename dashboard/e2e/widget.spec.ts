import { expect, test } from "@playwright/test";
test("embedded widget answers a catalogue price across origins", async ({
  page,
  request,
}) => {
  const registration = await request.post(
    "http://localhost:18000/api/v1/auth/register",
    {
      data: {
        business_name: "Demo Printing",
        business_type: "printing",
        name: "Demo Owner",
        email: `widget-${crypto.randomUUID()}@example.com`,
        password: "synthetic-password",
      },
    },
  );
  expect(registration.status()).toBe(201);
  const tokens = await registration.json();
  const headers = { Authorization: `Bearer ${tokens.access_token}` };
  const tenant = await (
    await request.get("http://localhost:18000/api/v1/tenant", { headers })
  ).json();
  const uploaded = await request.post(
    "http://localhost:18000/api/v1/catalog/import",
    {
      headers,
      multipart: {
        file: {
          name: "catalog.csv",
          mimeType: "text/csv",
          buffer: Buffer.from("sku,name,price\nCARD,Visiting cards,450\n"),
        },
      },
    },
  );
  expect(uploaded.status()).toBe(201);
  const preview = await uploaded.json();
  expect(
    (
      await request.post(
        `http://localhost:18000/api/v1/catalog/import/${preview.id}/commit`,
        { headers, data: { mapping: preview.mapping } },
      )
    ).status(),
  ).toBe(200);
  await page.goto("/login");
  await page.evaluate(
    ({ key, scriptUrl, api }) =>
      new Promise<void>((resolve, reject) => {
        const script = document.createElement("script");
        script.src = scriptUrl;
        script.dataset.key = key;
        script.dataset.api = api;
        script.onload = () => resolve();
        script.onerror = () => reject(new Error("Widget bundle did not load"));
        document.body.appendChild(script);
      }),
    {
      key: tenant.widget_public_key,
      scriptUrl: tenant.widget_script_url,
      api: tenant.public_api_url,
    },
  );
  await page.getByRole("button", { name: "Chat with us" }).click();
  await page.getByRole("button", { name: "Agree & start chat" }).click();
  await expect(page.getByLabel("Message", { exact: true })).toBeEnabled();
  await page
    .getByLabel("Message", { exact: true })
    .fill("visiting cards ka rate kya hai");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByRole("log")).toContainText(
    "Visiting cards: \u20b9450.00",
    { timeout: 30000 },
  );
  await expect(page.getByRole("log")).not.toContainText("\u20b91.00");
  await expect(page.locator("body")).toHaveJSProperty(
    "scrollWidth",
    await page.evaluate(() => window.innerWidth),
  );
});
