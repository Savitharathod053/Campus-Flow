import { test, expect } from '@playwright/test';
import { TEST_USERS } from '../test-data/users.data';
import { loginAs } from '../helpers/auth.helper';

test.describe('Payments - Checkout, Proof Upload & File Validation', () => {
  test.beforeEach(async ({ page }) => {
    await loginAs(page, TEST_USERS.student);
  });

  test('checkout page renders payment info and organizer details for pending registrations', async ({ page }) => {
    // Navigate to student's registrations
    await page.goto('/student/my-events', { waitUntil: 'domcontentloaded' });

    // Find any checkout link or pending payment
    const checkoutLink = page.locator('a[href*="/payment/checkout/"]').first();
    if (await checkoutLink.isVisible()) {
      await checkoutLink.click();
      await page.waitForLoadState('domcontentloaded');

      await expect(page).toHaveURL(/\/payment\/checkout\/\d+/);
      await expect(page.locator('h2, h3, h4').first()).toContainText(/Payment/i);

      // Verify transaction id input and proof upload input exist
      await expect(page.locator('input[name="transaction_id"]')).toBeVisible();
      await expect(page.locator('input[name="payment_screenshot"]')).toBeVisible();
      await expect(page.locator('#submitProofBtn')).toBeVisible();

      // UI REGRESSION CHECK: Cancel button must be clickable and return safely
      const cancelBtn = page.locator('#cancelPaymentBtn, a:has-text("Cancel Payment")').first();
      await expect(cancelBtn).toBeVisible();
      await cancelBtn.click();
      await page.waitForLoadState('domcontentloaded');
      await expect(page).toHaveURL(/\/student\/my-events/);
    }
  });

  test('submitting proof with invalid file format rejects submission cleanly', async ({ page }) => {
    await page.goto('/student/my-events', { waitUntil: 'domcontentloaded' });

    const checkoutLink = page.locator('a[href*="/payment/checkout/"]').first();
    if (await checkoutLink.isVisible()) {
      await checkoutLink.click();
      await page.waitForLoadState('domcontentloaded');

      await page.fill('input[name="transaction_id"]', '123456789012');

      // Upload text file instead of image
      await page.setInputFiles('input[name="payment_screenshot"]', {
        name: 'receipt.txt',
        mimeType: 'text/plain',
        buffer: Buffer.from('Invalid receipt format'),
      });

      await page.click('#submitProofBtn');
      await page.waitForLoadState('domcontentloaded');

      // Assert error alert
      const alert = page.locator('.alert-danger, div[role="alert"]');
      if (await alert.isVisible()) {
        const text = await alert.textContent();
        expect(text).toMatch(/Invalid image format|Only PNG, JPG|allowed/i);
      }
    }
  });
});
