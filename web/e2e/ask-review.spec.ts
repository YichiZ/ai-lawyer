import { expect, test, type Page } from "@playwright/test";

async function switchRole(page: Page, role: "researcher" | "reviewer") {
  const button = page.getByRole("group", { name: /Demo role/ }).getByRole("button", { name: role });
  await button.click();
  await expect(button).toHaveAttribute("aria-pressed", "true");
}

test("ask → reviewer approves → researcher sees the reviewed answer and opens a citation", async ({ page }) => {
  const question = `[e2e ${Date.now()}] How long after a dog bite can the owner be sued under the Dog Owners' Liability Act?`;

  await askAsResearcher(page, question);
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

async function askAsResearcher(page: Page, question: string) {
  await page.goto("/ask");
  await switchRole(page, "researcher");
  await page.getByLabel("Your research question").fill(question);
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page).toHaveURL(/\/answers\/\d+$/, { timeout: 30_000 });
}

test("reviewer queue is hidden from researchers; edit needs a note", async ({ page }) => {
  // Self-contained: creates its own pending answer (CI starts from an empty answers table).
  const question = `[e2e ${Date.now()}] What is the basic limitation period under the Limitations Act, 2002?`;
  await askAsResearcher(page, question);
  await page.goto("/review");
  await expect(page.getByText("Only reviewers can see the queue")).toBeVisible();

  await switchRole(page, "reviewer");
  await page.goto("/review");
  const item = page.getByRole("article").filter({ hasText: question });
  await item.getByLabel("edit").check();
  await item.getByLabel("Note (required)").fill("   ");
  await item.getByRole("button", { name: "edit answer" }).click();
  await expect(item.getByRole("alert")).toContainText("needs the revised answer and a note");
});

test("reviewer rejects for legal advice → researcher sees the reason, not the draft", async ({ page }) => {
  const question = `[e2e ${Date.now()}] Do I have a case against the city for tripping on a broken sidewalk?`;
  await askAsResearcher(page, question);
  const answerUrl = page.url();

  await switchRole(page, "reviewer");
  await page.goto("/review");
  const item = page.getByRole("article").filter({ hasText: question });
  await item.getByLabel("reject").check();
  await item.getByLabel("Reason").selectOption({ label: "Gives legal advice" });
  await item.getByRole("button", { name: "reject answer" }).click();
  await expect(page.getByRole("article").filter({ hasText: question })).toHaveCount(0);

  await switchRole(page, "researcher");
  await page.goto(answerUrl);
  await expect(page.getByText("A reviewer did not release this answer (Gives legal advice)")).toBeVisible();
  await expect(page.getByText("[Test answer]")).toHaveCount(0);
});
