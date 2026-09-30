import { test, expect } from '@playwright/test';
import { monitorConsoleErrors, assertNoHorizontalOverflow } from '../utils/ui.utils';

test.describe('Smoke - Homepage & Public Navigation', () => {
  test('homepage loads successfully with hero elements and metrics', async ({ page }) => {
    const consoleErrors = monitorConsoleErrors(page);
    const response = await page.goto('/', { waitUntil: 'domcontentloaded' });

    // Assert HTTP status 200
    expect(response?.status()).toBe(200);

    // Verify branding and title
    await expect(page).toHaveTitle(/Campus Flow/i);
    await expect(page.locator('a.navbar-brand-custom').first()).toBeVisible();

    // Verify Explore Events CTA
    const exploreBtn = page.locator('a[href*="/events"]').first();
    await expect(exploreBtn).toBeVisible();

    // Verify no horizontal overflow
    await assertNoHorizontalOverflow(page);

    // Verify no fatal console errors
    expect(consoleErrors).toHaveLength(0);
  });

  test('explore events page loads with search and filters', async ({ page }) => {
    await page.goto('/events', { waitUntil: 'domcontentloaded' });

    await expect(page).toHaveTitle(/Events|Campus Flow/i);
    // Search input should exist
    const searchInput = page.locator('input[name="q"], input[type="search"]').first();
    await expect(searchInput).toBeVisible();

    await assertNoHorizontalOverflow(page);
  });

  test('navigation to login page works smoothly', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.click('a[href*="/auth/login"]');
    await expect(page).toHaveURL(/\/auth\/login/);
    await expect(page.locator('input[name="identifier"]')).toBeVisible();
    await expect(page.locator('input[name="password"]')).toBeVisible();
  });
});
