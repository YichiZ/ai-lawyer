import AxeBuilder from "@axe-core/playwright";
import { execFileSync } from "node:child_process";
import { expect, test } from "@playwright/test";

// A guide section awaiting review shows its sources, never the draft (#3). Self-contained: asks a question through
// the API (fake model), then points a throwaway guide at that answer; the guide is deleted afterwards.
const slug = `e2e-guide-${Date.now()}`;
const question = `[e2e ${Date.now()}] What is the basic limitation period under the Limitations Act, 2002?`;

function sql(statement: string, ...params: (string | number)[]) {
  const script = "import json, os, sys, psycopg\n" +
    "url = os.environ.get('DATABASE_URL', 'postgresql://postgres:dev@localhost:5432/ai_lawyer')\n" +
    "with psycopg.connect(url, autocommit=True) as c: c.execute(sys.argv[1], json.loads(sys.argv[2]))";
  execFileSync("uv", ["run", "python", "-c", script, statement, JSON.stringify(params)], { cwd: "..", stdio: "inherit" });
}

test.beforeAll(async ({ request }) => {
  const res = await request.post("http://localhost:8001/ask", { data: { question } });
  expect(res.ok()).toBeTruthy();
  const { answer_id, sources } = (await res.json()).data;
  expect(sources.length).toBeGreaterThan(0);
  sql("INSERT INTO guides (slug, title, intro, sort_order) VALUES (%s, 'E2E guide', 'Test guide.', 999)", slug);
  sql("INSERT INTO guide_sections (guide_slug, heading, question, answer_id, sort_order) VALUES (%s, 'Deadlines', %s, %s, 1)",
      slug, question, answer_id);
});

test.afterAll(() => sql("DELETE FROM guides WHERE slug = %s", slug));

test("pending guide section shows its sources, not the draft; reviewer sees the guide tag", async ({ page }) => {
  await page.goto(`/guides/${slug}`);
  const section = page.getByRole("region", { name: "Deadlines" });
  await expect(section.getByText(/Awaiting review/)).toBeVisible();
  await expect(section.getByRole("link", { name: /Limitations Act, 2002/ }).first()).toBeVisible();
  await expect(page.getByText("[Test answer]")).toHaveCount(0);

  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(results.violations.map((v) => v.id)).toEqual([]);

  const button = page.getByRole("group", { name: /Demo role/ }).getByRole("button", { name: "reviewer" });
  await button.click();
  await expect(button).toHaveAttribute("aria-pressed", "true");
  await expect(async () => {
    await page.goto("/review");  // the fake draft is written in the background
    await expect(page.getByRole("article").filter({ hasText: question })).toContainText("Guide: E2E guide → Deadlines");
  }).toPass({ timeout: 20_000 });
});
