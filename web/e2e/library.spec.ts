import { expect, test } from "@playwright/test";

test("library → law → section, with official text, provenance and copyable citation", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/laws");
  await expect(page.getByRole("heading", { level: 1, name: "Law library" })).toBeVisible();
  await page.getByRole("link", { name: "Limitations Act, 2002" }).click();

  await expect(page).toHaveURL(/\/laws\/limitations-act-2002$/);
  await page.getByRole("link", { name: /s\. 4\s+Basic limitation period/ }).click();

  await expect(page).toHaveURL(/\/laws\/limitations-act-2002\/s-4$/);
  await expect(page.getByRole("heading", { level: 1, name: "Basic limitation period" })).toBeVisible();
  await expect(page.getByText("second anniversary of the day on which the claim was discovered")).toBeVisible();
  await expect(page.getByText(/Source: Ontario e-Laws via A2AJ/)).toBeVisible();
  await expect(page.getByRole("link", { name: "Official version" })).toHaveAttribute("href", /ontario\.ca\/laws/);

  await page.getByRole("button", { name: "Copy citation" }).click();
  await expect(page.getByRole("status")).toHaveText("Citation copied");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("Limitations Act, 2002, SO 2002, c 24, Sched B, s 4");
});

test("Toronto by-law sections show an excerpt and a link, never the full text", async ({ page }) => {
  await page.goto("/laws/toronto-municipal-code-743/743-44");
  await expect(page.getByText(/^Excerpt only/)).toBeVisible();
  await expect(page.getByRole("link", { name: "Read the full chapter on toronto.ca" })).toHaveAttribute("href", /toronto\.ca/);
  const text = await page.locator(".law-text").innerText();
  expect(text.length).toBeLessThanOrEqual(320);
  expect(text.startsWith("A. An officer")).toBe(true);
});

test("unknown section shows the not-found page", async ({ page }) => {
  const res = await page.goto("/laws/limitations-act-2002/s-999");
  expect(res?.status()).toBe(404);
  await expect(page.getByRole("heading", { name: "Not found" })).toBeVisible();
});
