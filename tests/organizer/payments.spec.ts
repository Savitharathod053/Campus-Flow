import { test, expect } from '@playwright/test';
import { TEST_USERS } from '../test-data/users.data';
import { loginAs } from '../helpers/auth.helper';

test.describe('Organizer - Payment Verification Review', () => {
  test.beforeEach(async ({ page }) => {
    await loginAs(page, TEST_USERS.organizer);
  });

  test('organizer can access payment verification portal and filters', async ({ page }) => {
    await page.goto('/organizer/payments/verification', { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveTitle(/Payment|Verification|Campus Flow/i);

    // Verify filter dropdowns or table presence
    const tableOrCard = page.locator('table, .ff-card, .table-responsive');
    await expect(tableOrCard.first()).toBeVisible();
  });
});
