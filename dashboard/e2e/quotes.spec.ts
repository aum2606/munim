import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

test("owner approves a quote and the embedded customer downloads its PDF", async ({
  page,
  request,
  context,
}, testInfo) => {
  const email = `quote-${crypto.randomUUID()}@example.com`;
  const registered = await request.post(
    "http://localhost:18000/api/v1/auth/register",
    {
      data: {
        business_name: "Demo Printing",
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
  const uploaded = await request.post(
    "http://localhost:18000/api/v1/catalog/import",
    {
      headers,
      multipart: {
        file: {
          name: "cards.csv",
          mimeType: "text/csv",
          buffer: Buffer.from(
            "sku,name,price,unit\nCARD-100,Visiting cards,450,pack of 100\n",
          ),
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
  const catalog = (
    await (
      await request.get("http://localhost:18000/api/v1/catalog/items", {
        headers,
      })
    ).json()
  )[0];
  const { id, display_price, ...fields } = catalog;
  void display_price;
  expect(
    (
      await request.put(`http://localhost:18000/api/v1/catalog/items/${id}`, {
        headers,
        data: {
          ...fields,
          attributes: {
            pack_size: "100",
            default_size: "standard",
            default_material: "standard",
            default_sides: "single-sided",
            default_colour: "colour",
            default_finishing: "none",
          },
        },
      })
    ).status(),
  ).toBe(200);
  expect(
    (
      await request.post(
        "http://localhost:18000/api/v1/catalog/pricing-rules",
        {
          headers,
          data: {
            catalog_item_id: id,
            rule: {
              rule_type: "addon",
              option: "sides",
              value: "double-sided",
              amount_paise: 10000,
              per_unit: true,
            },
          },
        },
      )
    ).status(),
  ).toBe(201);
  const tenant = await (
    await request.get("http://localhost:18000/api/v1/tenant", { headers })
  ).json();
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("synthetic-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("link", { name: "Quotes", exact: true }).click();
  await page.getByLabel("GSTIN", { exact: true }).fill("24AAAAA0000A1Z5");
  await page.getByLabel("Supplier state code", { exact: true }).fill("24");
  await page
    .getByLabel("Business address", { exact: true })
    .fill("Demo market, Ahmedabad");
  await page.getByRole("button", { name: "Save business details" }).click();
  await expect(page.getByRole("status")).toContainText("Saved");
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
        script.onerror = () => reject(new Error("Widget bundle did not load"));
        document.body.appendChild(script);
      }),
    {
      key: tenant.widget_public_key,
      scriptUrl: tenant.widget_script_url,
      api: tenant.public_api_url,
    },
  );
  await customer.getByRole("button", { name: "Chat with us" }).click();
  await expect(customer.getByLabel("Message", { exact: true })).toBeEnabled();
  await customer
    .getByLabel("Message", { exact: true })
    .fill("quote; item=visiting cards; quantity=500; sides=double-sided");
  await customer.getByRole("button", { name: "Send", exact: true }).click();
  await expect(customer.getByRole("log")).toContainText(
    "What size do you need?",
    { timeout: 30000 },
  );
  await customer
    .getByLabel("Message", { exact: true })
    .fill(
      "size=unknown; material=unknown; colour=unknown; finishing=unknown; deadline=2026-12-20",
    );
  await customer.getByRole("button", { name: "Send", exact: true }).click();
  await expect(customer.getByRole("log")).toContainText("team to review", {
    timeout: 30000,
  });
  const quote = await (
    await request.get("http://localhost:18000/api/v1/quotes", { headers })
  ).json();
  expect(quote).toHaveLength(1);
  expect(quote[0].totals.total_paise).toBe(324500);
  await page.getByText(quote[0].quote_number, { exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Approve & send" }),
  ).toBeEnabled();
  await expect(page.locator("body")).toHaveJSProperty(
    "scrollWidth",
    await page.evaluate(() => window.innerWidth),
  );
  await page.screenshot({
    path: `.cache/quotes-${testInfo.project.name}.png`,
    fullPage: true,
  });
  await page.getByRole("button", { name: "Approve & send" }).click();
  await expect(customer.getByRole("log")).toContainText("₹3,245.00", {
    timeout: 15000,
  });
  const downloaded = customer.waitForEvent("download");
  await customer.getByRole("button", { name: "Download quote PDF" }).click();
  const download = await downloaded;
  expect(download.suggestedFilename()).toBe("quotation.pdf");
  const path = await download.path();
  expect(path).toBeTruthy();
  expect(readFileSync(path!).subarray(0, 5).toString()).toBe("%PDF-");
  await customer.close();
});
