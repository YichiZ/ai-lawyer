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

  // #10: the approved answer is the newest on the home page's recently reviewed list
  await page.goto("/");
  const recent = page.getByRole("region", { name: "Recently reviewed answers" });
  await expect(recent.getByRole("listitem").first()).toContainText(/Reviewed by Demo Reviewer on/);
  await recent.getByRole("link", { name: question }).click();
  await expect(page).toHaveURL(answerUrl);
});

async function askAsResearcher(page: Page, question: string) {
  await page.goto("/ask");
  await switchRole(page, "researcher");
  await page.getByLabel("Your research question").fill(question);
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page).toHaveURL(/\/answers\/\d+$/, { timeout: 30_000 });
}

test("reviewer queue is hidden from researchers; edit needs a note; an edited-out quote loses its chip", async ({ page }) => {
  // Self-contained: creates its own pending answer (CI starts from an empty answers table).
  const question = `[e2e ${Date.now()}] What is the basic limitation period under the Limitations Act, 2002?`;
  await askAsResearcher(page, question);
  const answerUrl = page.url();
  await page.goto("/review");
  await expect(page.getByText("Only reviewers can see the queue")).toBeVisible();

  await switchRole(page, "reviewer");
  await page.goto("/review");
  const item = page.getByRole("article").filter({ hasText: question });
  // #57: the reviewer removes the draft's quote, so the released answer shows no citation chip for it.
  const revised = "[e2e edit] The draft quoted the wrong rule; removed.";
  await item.getByLabel("edit").check();
  await item.getByLabel("Revised answer").fill(revised);
  await item.getByLabel("Note (required)").fill("   ");
  await item.getByRole("button", { name: "edit answer" }).click();
  await expect(item.getByRole("alert")).toContainText("needs the revised answer and a note");
  await expect(item.getByRole("table", { name: /Claims and their verified quotes/ })).toBeVisible(); // the draft has a claim

  // #70: a failed submit keeps the decision and the entered text, so the resubmit sends the edit, never an approval.
  await expect(item.getByLabel("edit")).toBeChecked();
  await expect(item.getByLabel("Revised answer")).toHaveValue(revised);
  await item.getByLabel("Note (required)").fill("removed the wrong citation");
  await item.getByRole("button", { name: "edit answer" }).click();
  await expect(page.getByRole("article").filter({ hasText: question })).toHaveCount(0);

  await switchRole(page, "researcher");
  await page.goto(answerUrl);
  await expect(page.getByText(revised)).toBeVisible();
  await expect(page.getByText(/\(edited by reviewer\)/)).toBeVisible();
  await expect(page.getByRole("list", { name: "Citations" })).toHaveCount(0);
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

test("reject without a reason shows an error; picking one then rejects (#70)", async ({ page }) => {
  const question = `[e2e ${Date.now()}] Can I sue my landlord for a slip on an icy walkway?`;
  await askAsResearcher(page, question);
  const answerUrl = page.url();

  await switchRole(page, "reviewer");
  await page.goto("/review");
  const item = page.getByRole("article").filter({ hasText: question });
  await item.getByLabel("reject").check();
  await item.getByLabel("Reason").evaluate((el) => el.removeAttribute("required")); // reach the server-side check
  await item.getByRole("button", { name: "reject answer" }).click();
  await expect(item.getByRole("alert")).toContainText("Choose a reason");
  await expect(item.getByLabel("reject")).toBeChecked();

  await item.getByLabel("Reason").selectOption({ label: "Gives legal advice" });
  await item.getByRole("button", { name: "reject answer" }).click();
  await expect(page.getByRole("article").filter({ hasText: question })).toHaveCount(0);

  await switchRole(page, "researcher");
  await page.goto(answerUrl);
  await expect(page.getByText("A reviewer did not release this answer (Gives legal advice)")).toBeVisible();
  await expect(page.getByText("[Test answer]")).toHaveCount(0);
});

test("a too-short question shows an error and keeps the typed text (#72)", async ({ page }) => {
  await page.goto("/ask");
  const box = page.getByLabel("Your research question");
  const typed = "   abc   "; // passes the browser's minLength (5); 3 characters once trimmed
  await box.fill(typed);
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toHaveText("Please write a question of at least 5 characters.");
  await expect(box).toHaveValue(typed);
  await expect(page).toHaveURL(/\/ask$/);
});
