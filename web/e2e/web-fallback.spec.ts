import AxeBuilder from "@axe-core/playwright";
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
  const webAnswerUrl = page.url(); // a new answer, redirected to from the library one

  await switchRole(page, "reviewer");
  await page.goto("/review");
  const item = page.getByRole("article").filter({ hasText: question }).filter({ hasText: "From the web" });
  await expect(item).toBeVisible();
  await expect(item.getByRole("list", { name: "Risk flags" })).toContainText("web_fallback");

  // Official sources can be added to the library (queued for the ingest worker).
  const source = item.getByRole("region", { name: "Web sources" }).getByRole("listitem").filter({ hasText: "ontario.ca" });
  await source.getByRole("button", { name: "Add to library" }).click();
  await expect(source.getByRole("status")).toBeEmpty(); // nothing queued until the reviewer confirms scope
  await source.getByRole("checkbox", { name: "This page is about Ontario personal-injury law" }).check();
  await source.getByRole("button", { name: "Add to library" }).click();
  await expect(source.getByRole("status")).toContainText(/Queued|Adding|Added/);

  // #62: once approved, researchers get the sources as real links, not raw markdown.
  await expect(item.getByText("[Test page]")).toHaveCount(0);
  await item.getByRole("button", { name: "approve answer" }).click();
  await expect(item).toHaveCount(0); // the library's not-found draft of the same question stays queued
  await switchRole(page, "researcher");
  await page.goto(webAnswerUrl);
  await expect(page.getByText(/Reviewed by Demo Reviewer on/)).toBeVisible();
  const link = page.getByRole("region", { name: "Web sources" }).getByRole("link", { name: "Test page (opens in a new tab)" });
  await expect(link).toHaveAttribute("href", "https://www.ontario.ca/page/test");
  await expect(link).toHaveAttribute("target", "_blank");
  await expect(link).toHaveAttribute("rel", "noopener noreferrer");
  await expect(page.getByRole("main")).not.toContainText("](");
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(results.violations.map((v) => v.id)).toEqual([]);
});
