import { test, expect } from '@playwright/test';
import { TEST_USERS } from '../test-data/users.data';
import { loginAs } from '../helpers/auth.helper';

test.describe('UI/UX Regressions - Button Clicks, Modals & Jitter Prevention', () => {
  test('REGRESSION CHECK: Payment Cancel button works smoothly and does not jitter or get stuck', async ({ page }) => {
    await loginAs(page, TEST_USERS.student);
    await page.goto('/student/my-events', { waitUntil: 'domcontentloaded' });

    const checkoutLink = page.locator('a[href*="/payment/checkout/"]').first();
    if (await checkoutLink.isVisible()) {
      await checkoutLink.click();
      await page.waitForLoadState('domcontentloaded');

      const cancelBtn = page.locator('#cancelPaymentBtn, a:has-text("Cancel Payment")').first();
      await expect(cancelBtn).toBeVisible();

      // Check button is not disabled and has valid pointer
      await expect(cancelBtn).toBeEnabled();

      // Click cancel button
      await cancelBtn.click();
      await page.waitForLoadState('domcontentloaded');

      // Successfully returned to registrations
      await expect(page).toHaveURL(/\/student\/my-events/);
    }
  });

  test('REGRESSION CHECK: Certificate View/Preview modal opens and closes without layout jitter', async ({ page }) => {
    await loginAs(page, TEST_USERS.student);
    await page.goto('/student/certificates', { waitUntil: 'domcontentloaded' });

    const previewBtn = page.locator('button[data-bs-toggle="modal"][data-bs-target^="#studentModal"]').first();
    if (await previewBtn.isVisible()) {
      await previewBtn.click();

      const modal = page.locator('.modal.show');
      await expect(modal).toBeVisible({ timeout: 5000 });

      // Ensure modal backdrop is active
      const backdrop = page.locator('.modal-backdrop');
      await expect(backdrop).toBeVisible();

      // Close modal via close button
      const closeBtn = modal.locator('button[data-bs-dismiss="modal"]').first();
      await closeBtn.click();

      // Modal and backdrop should disappear
      await expect(modal).not.toBeVisible();
      await expect(backdrop).not.toBeVisible();
    }
  });

  test('mobile hamburger navigation opens and collapses cleanly without UI freezing', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/', { waitUntil: 'domcontentloaded' });

    const toggler = page.locator('button.navbar-toggler');
    await expect(toggler).toBeVisible();

    // Open menu
    await toggler.click();
    const navMenu = page.locator('#navbarMain');
    await expect(navMenu).toHaveClass(/show/);

    // Close menu
    await toggler.click();
    await expect(navMenu).not.toHaveClass(/show/);
  });
});
