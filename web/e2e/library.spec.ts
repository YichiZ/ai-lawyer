import { execFileSync } from "node:child_process";
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

function sql(statement: string, ...params: string[]) {
  const script = "import json, os, sys, psycopg\n" +
    "url = os.environ.get('DATABASE_URL', 'postgresql://postgres:dev@localhost:5432/ai_lawyer')\n" +
    "with psycopg.connect(url, autocommit=True) as c: c.execute(sys.argv[1], json.loads(sys.argv[2]))";
  execFileSync("uv", ["run", "python", "-c", script, statement, JSON.stringify(params)], { cwd: "..", stdio: "inherit" });
}

test("an added web page shows its title, domain, fetched date and a singular section count (#8)", async ({ page }) => {
  const slug = `web-e2e-${Date.now()}`;
  sql("WITH d AS (INSERT INTO documents (sha256, kind, slug, title, citation, url, source, date, reproduction)" +
      " VALUES (%s, 'web', %s, 'E2E slip and fall page', 'online: ontario.ca <https://www.ontario.ca/page/e2e>'," +
      " 'https://www.ontario.ca/page/e2e', 'web:ontario.ca', '2026-09-26', 'full') RETURNING id)" +
      " INSERT INTO sections (document_id, pinpoint, kind, heading, text, sort_order)" +
      " SELECT id, 'sec-1', 'section', 'Introduction', 'Give notice.', 1 FROM d", slug, slug);
  try {
    await page.goto("/laws");
    const item = page.getByRole("listitem").filter({ has: page.getByRole("link", { name: "E2E slip and fall page" }) });
    await expect(item).toContainText("ontario.ca");
    await expect(item).not.toContainText("<https://");
    await expect(item).toContainText("1 section · fetched September 26, 2026");
  } finally {
    sql("DELETE FROM documents WHERE slug = %s", slug);
  }
});

test("unknown section shows the not-found page", async ({ page }) => {
  const res = await page.goto("/laws/limitations-act-2002/s-999");
  expect(res?.status()).toBe(404);
  await expect(page.getByRole("heading", { name: "Not found" })).toBeVisible();
});
