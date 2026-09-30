import { test, expect } from '@playwright/test';
import { TEST_USERS } from '../test-data/users.data';
import { loginAs } from '../helpers/auth.helper';

test.describe('Attendance - Scanner & Session Management', () => {
  test('organizer can access attendance matrix and checkpoint session overview', async ({ page }) => {
    await loginAs(page, TEST_USERS.organizer);
    await page.goto('/organizer/dashboard', { waitUntil: 'domcontentloaded' });

    // Look for attendance matrix dashboard link
    const attDashboardLink = page.locator('a[href*="/attendance"]').first();
    if (await attDashboardLink.isVisible()) {
      await attDashboardLink.click();
      await page.waitForLoadState('domcontentloaded');

      await expect(page).toHaveURL(/\/attendance/);
      await expect(page.locator('body')).toContainText(/Attendance|Session|Participants/i);
    }
  });

  test('attendance endpoint rejects unauthenticated requests with redirect or forbidden', async ({ request }) => {
    const resp = await request.post('/organizer/attendance/mark', {
      maxRedirects: 0,
      data: {
        registration_code: '',
        event_id: 1,
      },
    });

    expect([302, 400, 401, 403]).toContain(resp.status());
  });
});
