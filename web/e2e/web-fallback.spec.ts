import { expect, test, type Page } from "@playwright/test";

async function switchRole(page: Page, role: "researcher" | "reviewer") {
  const button = page.getByRole("group", { name: /Demo role/ }).getByRole("button", { name: role });
  await button.click();
  await expect(button).toHaveAttribute("aria-pressed", "true");
}

test("no library match → opt-in web search → labelled answer flagged for review", async ({ page }) => {
  const question = `[e2e ${Date.now()}] Zqxv blorfing wibble?`; // no word matches the library, so the fake embedding is far from every chunk
  await page.goto("/ask");
  await switchRole(page, "researcher");
  await page.getByLabel("Your research question").fill(question);
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page).toHaveURL(/\/answers\/\d+$/, { timeout: 30_000 });

  await page.getByRole("button", { name: "Search the web instead" }).click();
  await expect(page.getByText("Web search answer — not from our law library.")).toBeVisible({ timeout: 30_000 });

  await switchRole(page, "reviewer");
  await page.goto("/review");
  const item = page.getByRole("article").filter({ hasText: question }).filter({ hasText: "From the web" });
  await expect(item).toBeVisible();
  await expect(item.getByRole("list", { name: "Risk flags" })).toContainText("web_fallback");
});
