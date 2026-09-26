import { expect, test, type Page } from "@playwright/test";

async function switchRole(page: Page, role: "researcher" | "reviewer") {
  const button = page.getByRole("group", { name: /Demo role/ }).getByRole("button", { name: role });
  await button.click();
  await expect(button).toHaveAttribute("aria-pressed", "true");
}

test("ask → reviewer approves → researcher sees the reviewed answer and opens a citation", async ({ page }) => {
  const question = `[e2e ${Date.now()}] How long after a dog bite can the owner be sued under the Dog Owners' Liability Act?`;

  await page.goto("/ask");
  await switchRole(page, "researcher");
  await page.getByLabel("Your research question").fill(question);
  await page.getByRole("button", { name: "Ask" }).click();

  await expect(page).toHaveURL(/\/answers\/\d+$/, { timeout: 30_000 });
  const answerUrl = page.url();
  await expect(page.getByRole("status")).toContainText("Awaiting review");
  await expect(page.getByText("[Test answer]")).toHaveCount(0); // draft never shown before review
  await expect(page.getByRole("heading", { name: "Sources found" })).toBeVisible();

  await switchRole(page, "reviewer");
  await page.goto("/review");
  const item = page.getByRole("article").filter({ hasText: question });
  await expect(item).toBeVisible();
  await expect(item.getByRole("table", { name: /Claims and their verified quotes/ })).toBeVisible();
  await item.getByRole("button", { name: "approve answer" }).click();
  await expect(page.getByRole("article").filter({ hasText: question })).toHaveCount(0);

  await switchRole(page, "researcher");
  await page.goto(answerUrl);
  await expect(page.getByText(/Reviewed by Demo Reviewer on/)).toBeVisible();
  await expect(page.getByText("[Test answer]")).toBeVisible();

  await page.getByRole("list", { name: "Citations" }).getByRole("button").first().click();
  const panel = page.getByRole("dialog");
  await expect(panel.locator("mark")).toBeVisible();
  await expect(panel.getByRole("button", { name: "Close" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);
});

test("reviewer queue is hidden from researchers; edit needs a note", async ({ page }) => {
  await page.goto("/review");
  await switchRole(page, "researcher");
  await page.goto("/review");
  await expect(page.getByText("Only reviewers can see the queue")).toBeVisible();

  await switchRole(page, "reviewer");
  await page.goto("/review");
  const first = page.getByRole("article").first();
  await first.getByLabel("edit").check();
  await first.getByLabel("Note (required)").fill("   ");
  await first.getByRole("button", { name: "edit answer" }).click();
  await expect(first.getByRole("alert")).toContainText("needs the revised answer and a note");
});
