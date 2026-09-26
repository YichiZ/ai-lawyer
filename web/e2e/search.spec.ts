import { expect, test } from "@playwright/test";

test("typing a citation jumps straight to the section", async ({ page }) => {
  await page.goto("/laws");
  await page.keyboard.press("/");
  const box = page.getByRole("combobox", { name: /Search laws/ });
  await expect(box).toBeFocused();
  await box.fill("Limitations Act s. 4");
  const option = page.getByRole("option").first();
  await expect(option).toContainText("s. 4");
  await box.press("Enter");
  await expect(page).toHaveURL(/\/laws\/limitations-act-2002\/s-4$/);
  await expect(page.getByRole("heading", { level: 1, name: "Basic limitation period" })).toBeVisible();
});

test("heading typeahead and full search with Ask this", async ({ page }) => {
  await page.goto("/");
  const box = page.getByRole("combobox", { name: /Search laws/ });
  await box.fill("ultimate limitation");
  await expect(page.getByRole("option").filter({ hasText: "Ultimate limitation periods" })).toBeVisible();

  await box.fill("How long do I have to sue after an injury?");
  await box.press("Escape");
  await box.press("Enter");
  await expect(page).toHaveURL(/\/search\?q=/);
  await expect(page.getByRole("heading", { level: 2, name: "Limitations Act, 2002" })).toBeVisible();
  await page.getByRole("link", { name: "Ask this" }).click();
  await expect(page).toHaveURL(/\/ask\?q=/);
  await expect(page.getByLabel("Your research question")).toHaveValue("How long do I have to sue after an injury?");
});
