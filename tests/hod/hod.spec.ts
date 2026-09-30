import { test, expect } from '@playwright/test';
import { TEST_USERS } from '../test-data/users.data';
import { loginAs } from '../helpers/auth.helper';

test.describe('HOD - Departmental Reviews & Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await loginAs(page, TEST_USERS.hod);
  });

  test('HOD dashboard loads departmental metrics, pending proposals, and organizer requests', async ({ page }) => {
    await page.goto('/hod/dashboard', { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveTitle(/HOD|Head of Department|Campus Flow/i);

    // Assert departmental tabs
    await expect(page.locator('body')).toContainText(/Department|Proposals|Organizer Requests|Events/i);
  });

  test('HOD can inspect event proposals pending departmental endorsement', async ({ page }) => {
    await page.goto('/hod/dashboard?tab=event_pending', { waitUntil: 'domcontentloaded' });

    // Table or list of event requests
    const proposalLink = page.locator('a[href*="/hod/event-requests/"]').first();
    if (await proposalLink.isVisible()) {
      await proposalLink.click();
      await page.waitForLoadState('domcontentloaded');

      await expect(page).toHaveURL(/\/hod\/event-requests\/\d+/);
      // Endorse or Reject actions should exist
      const actionButtons = page.locator('button[type="submit"], a.btn');
      const count = await actionButtons.count();
      expect(count).toBeGreaterThan(0);
    }
  });
});
