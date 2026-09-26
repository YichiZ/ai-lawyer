import { expect, test } from "@playwright/test";

test("section → cited-by decision → case page with its cited laws", async ({ page }) => {
  await page.goto("/laws/limitations-act-2002/s-4");
  const citedBy = page.getByRole("region", { name: /Cited by/ });
  await expect(citedBy).toBeVisible();
  await citedBy.getByRole("link", { name: /Galota/ }).click();

  await expect(page).toHaveURL(/\/cases\/2016-onca-585$/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Galota");
  await expect(page.getByText("2016 ONCA 585").first()).toBeVisible();
  await expect(page.locator("#para-1")).toBeVisible();
  await expect(page.getByText(/trial \(Superior Court\) decisions are not included/)).toBeVisible();
  await page.getByRole("region", { name: "Laws cited" }).getByRole("link").first().click();
  await expect(page).toHaveURL(/\/laws\/limitations-act-2002\/s-/);
});

test("typing a neutral citation jumps to the case", async ({ page }) => {
  await page.goto("/laws");
  const box = page.getByRole("combobox", { name: /Search laws/ });
  await box.fill("2016 ONCA 585");
  await expect(page.getByRole("option").first()).toContainText("2016 ONCA 585");
  await box.press("Enter");
  await expect(page).toHaveURL(/\/cases\/2016-onca-585$/);
});
