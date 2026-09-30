import { test, expect } from '@playwright/test';
import { TEST_USERS } from '../test-data/users.data';
import { loginAs } from '../helpers/auth.helper';

test.describe('Student - Certificate Vault', () => {
  test.beforeEach(async ({ page }) => {
    await loginAs(page, TEST_USERS.student);
  });

  test('student can access certificate vault page', async ({ page }) => {
    await page.goto('/student/certificates', { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveTitle(/Certificate|Vault|Campus Flow/i);

    // Header or empty state
    await expect(page.locator('h1, h2, h3, .vault-title').first()).toContainText(/Certificate/i);
  });

  test('certificate download button provides valid link when certificates exist', async ({ page }) => {
    await page.goto('/student/certificates', { waitUntil: 'domcontentloaded' });

    const downloadBtn = page.locator('a[href*="/certificates/"][href*="/download"]').first();
    if (await downloadBtn.isVisible()) {
      const href = await downloadBtn.getAttribute('href');
      expect(href).toBeTruthy();
      expect(href).toMatch(/\/certificates\/\d+\/download/);
    }
  });
});
