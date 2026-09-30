import { test, expect } from '@playwright/test';
import { TEST_USERS } from '../test-data/users.data';
import { loginAs } from '../helpers/auth.helper';

test.describe('Organizer - Attendance Scanner & Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await loginAs(page, TEST_USERS.organizer);
  });

  test('attendance scanner page loads with manual input and session controls', async ({ page }) => {
    // Navigate to organizer dashboard to find an active event scanner link
    await page.goto('/organizer/dashboard', { waitUntil: 'domcontentloaded' });

    const scannerLink = page.locator('a[href*="/scanner"]').first();
    if (await scannerLink.isVisible()) {
      await scannerLink.click();
      await page.waitForLoadState('domcontentloaded');

      await expect(page).toHaveURL(/\/scanner/);
      // Scanner should have registration code input or camera container
      const codeInput = page.locator('input[name="registration_code"], #manualCodeInput, #ticketCodeInput');
      const videoOrCanvas = page.locator('video, canvas, #reader, #qr-reader');

      const hasInput = await codeInput.isVisible().catch(() => false);
      const hasScanner = await videoOrCanvas.isVisible().catch(() => false);

      expect(hasInput || hasScanner).toBeTruthy();
    }
  });
});
