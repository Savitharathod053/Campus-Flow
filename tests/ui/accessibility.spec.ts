import { test } from '@playwright/test';
import { assertAccessibility } from '../utils/ui.utils';

test.describe('Accessibility - Automated WCAG 2.1 A/AA Audits', () => {
  test('homepage passes core accessibility audit', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await assertAccessibility(page);
  });

  test('events exploration catalog passes core accessibility audit', async ({ page }) => {
    await page.goto('/events', { waitUntil: 'domcontentloaded' });
    await assertAccessibility(page);
  });

  test('auth login form passes core accessibility audit', async ({ page }) => {
    await page.goto('/auth/login', { waitUntil: 'domcontentloaded' });
    await assertAccessibility(page);
  });
});
