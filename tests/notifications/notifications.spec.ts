import { test, expect } from '@playwright/test';
import { TEST_USERS } from '../test-data/users.data';
import { loginAs } from '../helpers/auth.helper';

test.describe('Notifications - Topbar Bell & Alert Lifecycle', () => {
  test('logged in student sees notification dropdown in navigation topbar', async ({ page }) => {
    await loginAs(page, TEST_USERS.student);

    // Notification toggle element should be in navbar
    const notifToggle = page.locator('#notificationDropdownToggle, a[title="Notifications"]').first();
    await expect(notifToggle).toBeVisible();

    // Click toggle to open notification menu
    await notifToggle.click();

    // Dropdown list container should be visible
    const dropdownMenu = page.locator('.notification-dropdown-menu, #notificationDropdownContainer .dropdown-menu');
    await expect(dropdownMenu).toBeVisible();
  });

  test('logged in HOD sees departmental notifications and alerts', async ({ page }) => {
    await loginAs(page, TEST_USERS.hod);

    const notifToggle = page.locator('#notificationDropdownToggle, a[title="Notifications"]').first();
    await expect(notifToggle).toBeVisible();
    await notifToggle.click();

    const dropdownHeader = page.locator('.notification-dropdown-header, .dropdown-menu');
    await expect(dropdownHeader.first()).toBeVisible();
  });
});
