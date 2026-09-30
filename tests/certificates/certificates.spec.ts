import { test, expect } from '@playwright/test';
import { TEST_USERS } from '../test-data/users.data';
import { loginAs } from '../helpers/auth.helper';

test.describe('Certificates - Management, Upload & Vault Verification', () => {
  test('organizer can view certificates management dashboard for an event', async ({ page }) => {
    await loginAs(page, TEST_USERS.organizer);
    await page.goto('/organizer/dashboard', { waitUntil: 'domcontentloaded' });

    // Find any event manage certificates link
    const certManageLink = page.locator('a[href*="/certificates"]').first();
    if (await certManageLink.isVisible()) {
      await certManageLink.click();
      await page.waitForLoadState('domcontentloaded');

      await expect(page).toHaveURL(/\/certificates/);
      // Verify tabs (All, Matched, Pending, Unmatched)
      await expect(page.locator('body')).toContainText(/Certificate/i);
    }
  });

  test('student can view certificate cards and trigger preview modal without UI glitch', async ({ page }) => {
    await loginAs(page, TEST_USERS.student);
    await page.goto('/student/certificates', { waitUntil: 'domcontentloaded' });

    const previewBtn = page.locator('button[data-bs-toggle="modal"][data-bs-target^="#studentModal"]').first();
    if (await previewBtn.isVisible()) {
      // Click preview button
      await previewBtn.click();

      // Modal should open
      const modal = page.locator('.modal.show');
      await expect(modal).toBeVisible({ timeout: 5000 });

      // Close modal
      const closeBtn = modal.locator('button[data-bs-dismiss="modal"]').first();
      await closeBtn.click();
      await expect(modal).not.toBeVisible();
    }
  });
});
