import { expect, test } from "@playwright/test";

test("typing a citation jumps straight to the section", async ({ page }) => {
  await page.goto("/laws");
  const box = page.getByRole("combobox", { name: /Search laws/ });
  // "/" works once the page has hydrated; retry the keypress rather than racing a cold dev server.
  await expect(async () => {
    await page.keyboard.press("/");
    await expect(box).toBeFocused({ timeout: 500 });
  }).toPass();
  await box.fill("Limitations Act s. 4");
  const option = page.getByRole("option").first();
  await expect(option).toContainText("s. 4");
  await box.press("Enter");
  await expect(page).toHaveURL(/\/laws\/limitations-act-2002\/s-4$/);
  await expect(page.getByRole("heading", { level: 1, name: "Basic limitation period" })).toBeVisible();
});

test("search shows the fused results at once, then reorders them when the rerank arrives", async ({ page, request }) => {
  // The fake model's rerank reverses the fused order, so the reorder is visible (#41).
  const q = "How long do I have to sue after an injury?";
  const groups = async (rerank: boolean) => {
    const res = await request.get(`http://localhost:8001/search?q=${encodeURIComponent(q)}&rerank=${rerank}`);
    return (await res.json()).data as { slug: string; title: string }[];
  };
  const [fusedGroups, rerankedGroups] = [await groups(false), await groups(true)];
  const [fused, reranked] = [fusedGroups.map((g) => g.title), rerankedGroups.map((g) => g.title)];
  expect(fused.length).toBeGreaterThan(1);
  expect(reranked).not.toEqual(fused);
  expect([...reranked].sort()).toEqual([...fused].sort());

  const html = await (await request.get(`/search?q=${encodeURIComponent(q)}`)).text();
  const at = (slug: string) => html.indexOf(`id="g-${slug}"`);
  expect(at(fusedGroups[1].slug)).toBeGreaterThan(at(fusedGroups[0].slug)); // server render: fused order
  expect(at(fusedGroups[0].slug)).toBeGreaterThan(-1);

  await page.goto(`/search?q=${encodeURIComponent(q)}`);
  await expect(page.getByRole("status").filter({ hasText: "Results re-ranked" })).toHaveText("Results re-ranked by relevance.");
  await expect(page.getByRole("heading", { level: 2 })).toHaveText(reranked);
  const cls = await page.evaluate(() => new Promise<number>((resolve) => {
    type Shift = PerformanceEntry & { value: number; hadRecentInput: boolean };
    new PerformanceObserver((list) => resolve((list.getEntries() as Shift[]).filter((e) => !e.hadRecentInput)
      .reduce((sum, e) => sum + e.value, 0))).observe({ type: "layout-shift", buffered: true });
    setTimeout(() => resolve(0), 1000); // no entries: no shift
  }));
  expect(cls).toBeLessThan(0.05); // the Lighthouse budget; moving the nodes in place measured 0.19
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
