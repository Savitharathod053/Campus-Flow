import { test, expect } from '@playwright/test';
import { TEST_USERS } from '../test-data/users.data';
import { loginAs, logout, assertAccessDenied } from '../helpers/auth.helper';

test.describe('Authentication & Role-Based Access Control (RBAC)', () => {
  test('student can log in using roll number, access dashboard, and log out', async ({ page }) => {
    // 1. Login
    await loginAs(page, TEST_USERS.student);
    await expect(page).toHaveURL(new RegExp(TEST_USERS.student.expectedDashboardPath));

    // 2. Session persistence on reload
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page).toHaveURL(new RegExp(TEST_USERS.student.expectedDashboardPath));

    // 3. Logout
    await logout(page);
    await expect(page).toHaveURL(/\/(#.*)?$/);
  });

  test('student can log in using email address', async ({ page }) => {
    await loginAs(page, {
      ...TEST_USERS.student,
      identifier: TEST_USERS.student.email,
    });
    await expect(page).toHaveURL(new RegExp(TEST_USERS.student.expectedDashboardPath));
    await logout(page);
  });

  test('login with invalid password shows error notification and rejects access', async ({ page }) => {
    await page.goto('/auth/login', { waitUntil: 'domcontentloaded' });

    await page.fill('input[name="identifier"]', TEST_USERS.student.identifier);
    await page.fill('input[name="password"]', 'WrongPassword123!');
    await page.click('button[type="submit"]');

    await expect(page).toHaveURL(/\/auth\/login/);
    await expect(page.locator('.alert-danger, div[role="alert"]')).toContainText(/Invalid email or password/i);
  });

  test('organizer can log in and reach organizer dashboard', async ({ page }) => {
    await loginAs(page, TEST_USERS.organizer);
    await expect(page).toHaveURL(new RegExp(TEST_USERS.organizer.expectedDashboardPath));
    await logout(page);
  });

  test('HOD can log in and reach departmental HOD dashboard', async ({ page }) => {
    await loginAs(page, TEST_USERS.hod);
    await expect(page).toHaveURL(new RegExp(TEST_USERS.hod.expectedDashboardPath));
    await logout(page);
  });

  test('Students Affairs Dean can log in and reach dean dashboard', async ({ page }) => {
    await loginAs(page, TEST_USERS.dean);
    await expect(page).toHaveURL(new RegExp(TEST_USERS.dean.expectedDashboardPath));
    await logout(page);
  });

  test('Super Admin can log in and reach admin dashboard', async ({ page }) => {
    await loginAs(page, TEST_USERS.superadmin);
    await expect(page).toHaveURL(new RegExp(TEST_USERS.superadmin.expectedDashboardPath));
    await logout(page);
  });

  test('unauthenticated user is blocked from protected dashboards', async ({ page }) => {
    await assertAccessDenied(page, '/student/dashboard');
    await assertAccessDenied(page, '/organizer/dashboard');
    await assertAccessDenied(page, '/hod/dashboard');
    await assertAccessDenied(page, '/dean/dashboard');
    await assertAccessDenied(page, '/admin/dashboard');
  });

  test('student is strictly forbidden from accessing superadmin, hod, and organizer dashboards', async ({ page }) => {
    await loginAs(page, TEST_USERS.student);

    // Attempt unauthorized portals
    await assertAccessDenied(page, '/admin/dashboard');
    await assertAccessDenied(page, '/hod/dashboard');
    await assertAccessDenied(page, '/organizer/dashboard');
    await assertAccessDenied(page, '/dean/dashboard');

    await logout(page);
  });

  test('organizer is forbidden from accessing superadmin and hod portals', async ({ page }) => {
    await loginAs(page, TEST_USERS.organizer);

    await assertAccessDenied(page, '/admin/dashboard');
    await assertAccessDenied(page, '/hod/dashboard');

    await logout(page);
  });
});
