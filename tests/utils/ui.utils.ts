import { Page, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

/**
 * Listens for uncaught console errors and uncaught page exceptions.
 */
export function monitorConsoleErrors(page: Page): string[] {
  const errors: string[] = [];

  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      const text = msg.text();
      // Filter out harmless 3rd-party favicon or extension warnings
      if (
        !text.includes('favicon.ico') &&
        !text.includes('chrome-extension') &&
        !text.includes('status of 404')
      ) {
        errors.push(text);
      }
    }
  });

  page.on('pageerror', (exception) => {
    errors.push(`Uncaught Page Exception: ${exception.message}`);
  });

  return errors;
}

/**
 * Asserts that the current page does not have unintentional horizontal overflow.
 */
export async function assertNoHorizontalOverflow(page: Page): Promise<void> {
  const isOverflowing = await page.evaluate(() => {
    const docWidth = document.documentElement.clientWidth;
    const bodyWidth = document.body.scrollWidth;
    return bodyWidth > docWidth + 2; // Allow 2px tolerance for fractional subpixel rounding
  });

  expect(isOverflowing, 'Page has horizontal scroll/overflow causing broken layout').toBeFalsy();
}

/**
 * Runs an automated accessibility check using axe-core and asserts no critical violations.
 */
export async function assertAccessibility(page: Page, excludedSelectors: string[] = []): Promise<void> {
  let builder = new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa'])
    .disableRules(['color-contrast', 'select-name']); // select-name: filter dropdowns lack aria-label (tracked accessibility defect)

  for (const selector of excludedSelectors) {
    builder = builder.exclude(selector);
  }

  const results = await builder.analyze();
  const criticalViolations = results.violations.filter(
    (v) => v.impact === 'critical' || v.impact === 'serious'
  );

  expect(
    criticalViolations.length,
    `Found ${criticalViolations.length} critical accessibility violations:\n` +
      criticalViolations.map((v) => `[${v.impact}] ${v.id}: ${v.description}`).join('\n')
  ).toBe(0);
}
