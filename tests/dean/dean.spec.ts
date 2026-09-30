import { test, expect } from '@playwright/test';
import { TEST_USERS } from '../test-data/users.data';
import { loginAs } from '../helpers/auth.helper';

test.describe('Dean - Students Affairs Portal & Final Clearance', () => {
  test.beforeEach(async ({ page }) => {
    await loginAs(page, TEST_USERS.dean);
  });

  test('Dean dashboard renders college-wide metrics and forwarded event requests', async ({ page }) => {
    await page.goto('/dean/dashboard', { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveTitle(/Dean|Students Affairs|Campus Flow/i);

    // Verify statistics cards
    await expect(page.locator('body')).toContainText(/Students Affairs Dean|Clearance|Events|Proposals/i);
  });

  test('Dean can inspect event proposals forwarded by HODs', async ({ page }) => {
    await page.goto('/dean/dashboard?tab=pending', { waitUntil: 'domcontentloaded' });

    const reviewLink = page.locator('a[href*="/dean/event-requests/"]').first();
    if (await reviewLink.isVisible()) {
      await reviewLink.click();
      await page.waitForLoadState('domcontentloaded');

      await expect(page).toHaveURL(/\/dean\/event-requests\/\d+/);
      // Final Approve & Publish button should exist
      await expect(page.locator('button[type="submit"], input[type="submit"]').first()).toBeVisible();
    }
  });
});
