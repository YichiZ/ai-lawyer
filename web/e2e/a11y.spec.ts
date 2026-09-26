import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

// WCAG 2.2 AA checks on every page type. Pages are checked in both colour schemes.
const PAGES = ["/", "/laws", "/laws/limitations-act-2002", "/laws/limitations-act-2002/s-4",
               "/laws/toronto-municipal-code-743/743-44", "/search?q=limitation%20period", "/ask", "/glossary", "/review", "/cases/2016-onca-585"];

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} mode`, () => {
    test.use({ colorScheme: scheme });
    for (const path of PAGES) {
      test(`no axe violations on ${path}`, async ({ page }) => {
        await page.goto(path);
        const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
        const summary = results.violations.map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(", ")}`);
        expect(summary, summary.join("\n")).toEqual([]);
      });
    }
  });
}
