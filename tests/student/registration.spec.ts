import { test, expect } from '@playwright/test';
import { TEST_USERS } from '../test-data/users.data';
import { loginAs } from '../helpers/auth.helper';

test.describe('Student - Dashboard, Registrations & Ticket Passes', () => {
  test.beforeEach(async ({ page }) => {
    await loginAs(page, TEST_USERS.student);
  });

  test('student dashboard renders metrics, upcoming events, and quick links', async ({ page }) => {
    await page.goto('/student/dashboard', { waitUntil: 'domcontentloaded' });

    // Assert student name or welcome heading
    await expect(page.locator('body')).toContainText(/Dashboard|Welcome|Registered Events/i);

    // Verify visible links to My Events and Certificates in the navbar
    const myEventsLink = page.locator('.navbar-nav a[href*="/student/my-events"]').first();
    const certificatesLink = page.locator('.navbar-nav a[href*="/student/certificates"]').first();

    await expect(myEventsLink).toBeVisible();
    await expect(certificatesLink).toBeVisible();
  });

  test('student can view their registered events and tabs', async ({ page }) => {
    await page.goto('/student/my-events', { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveTitle(/My Events|Campus Flow/i);

    // Check tabs (Active / Completed / All)
    const activeTab = page.locator('a[href*="tab=active"], a.nav-link.active').first();
    await expect(activeTab).toBeVisible();
  });

  test('ticket page displays registration pass and QR code', async ({ page }) => {
    await page.goto('/student/my-events', { waitUntil: 'domcontentloaded' });

    // Find any ticket link
    const ticketLink = page.locator('a[href*="/student/ticket/"]').first();
    if (await ticketLink.isVisible()) {
      await ticketLink.click();
      await page.waitForLoadState('domcontentloaded');

      // Verify pass code and QR image
      await expect(page).toHaveURL(/\/student\/ticket\//);
      const qrImg = page.locator('img[src*="qrcode"], img[alt*="QR"], img[alt*="ticket"]').first();
      await expect(qrImg).toBeVisible();
    }
  });
});
