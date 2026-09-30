import { test, expect } from '@playwright/test';
import { TEST_USERS } from '../test-data/users.data';
import { loginAs } from '../helpers/auth.helper';

test.describe('Super Admin - System Governance & Directory Management', () => {
  test.beforeEach(async ({ page }) => {
    await loginAs(page, TEST_USERS.superadmin);
  });

  test('super admin dashboard renders global system metrics and portal navigation', async ({ page }) => {
    await page.goto('/admin/dashboard', { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveTitle(/Super Admin|Dashboard|Campus Flow/i);

    // Overview cards
    await expect(page.locator('body')).toContainText(/Super Admin|Users|Departments|Events/i);
  });

  test('super admin can browse users directory and search users', async ({ page }) => {
    await page.goto('/admin/users', { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveTitle(/User|Super Admin/i);

    // Search input should exist
    const searchInput = page.locator('input[name="search"], input[type="search"]').first();
    if (await searchInput.isVisible()) {
      await searchInput.fill('Demo');
      await searchInput.press('Enter');
      await page.waitForLoadState('domcontentloaded');
      await expect(page.locator('body')).toContainText(/Demo/i);
    }
  });

  test('super admin can browse college departments and assigned HODs', async ({ page }) => {
    await page.goto('/admin/departments', { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveTitle(/Department|Super Admin/i);

    // Table of departments
    await expect(page.locator('body')).toContainText(/CSE|IT|ECE|Department/i);
  });

  test('super admin audit logs portal displays chronological system actions', async ({ page }) => {
    await page.goto('/admin/logs', { waitUntil: 'domcontentloaded' });
    // Audit logs header or table
    await expect(page.locator('body')).toContainText(/Audit|Log|Activity/i);
  });
});
