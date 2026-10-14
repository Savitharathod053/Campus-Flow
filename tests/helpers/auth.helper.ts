import { Page, expect } from '@playwright/test';
import { TestUser } from '../test-data/users.data';

/**
 * Logs in a user through the standard Campus Flow /auth/login interface.
 * Handles roll number for students/organizers, and email for faculty/admins.
 */
export async function loginAs(page: Page, user: TestUser): Promise<void> {
  await page.goto('/auth/login', { waitUntil: 'domcontentloaded' });

  // Fill credentials
  await page.fill('input[name="identifier"]', user.identifier);
  await page.fill('input[name="password"]', user.password);

  // Submit form and wait for POST response
  await Promise.all([
    page.waitForResponse(
      (resp) => resp.url().includes('/auth/login') && resp.request().method() === 'POST',
      { timeout: 30000 }
    ).catch(() => null),
    page.click('button[type="submit"]', { timeout: 30000 }),
  ]);

  await page.waitForLoadState('domcontentloaded');

  // Check if redirection succeeded
  const currentUrl = page.url();
  if (currentUrl.endsWith('/auth/login')) {
    const alertEl = page.locator('.alert-danger, div[role="alert"]');
    const alertCount = await alertEl.count();
    let alertMsg = '';
    if (alertCount > 0) {
      alertMsg = (await alertEl.first().textContent())?.trim() || '';
    }
    throw new Error(
      `Login failed for role "${user.role}" with identifier "${user.identifier}". ` +
      `URL remained at "${page.url()}". ${alertMsg ? `Server alert: "${alertMsg}"` : 'No alert message displayed.'}`
    );
  }

  // Ensure redirect away from login page
  await expect(page).not.toHaveURL(/\/auth\/login$/);
}

/**
 * Logs out the current user via /auth/logout.
 */
export async function logout(page: Page): Promise<void> {
  await page.goto('/auth/logout', { waitUntil: 'domcontentloaded' });
  await expect(page).toHaveURL(/\/(#.*)?$/);
}

/**
 * Asserts that attempting to access a protected route is blocked (either 403 or redirected to /auth/login).
 */
export async function assertAccessDenied(page: Page, protectedUrl: string): Promise<void> {
  const response = await page.goto(protectedUrl, { waitUntil: 'domcontentloaded' });
  
  if (response) {
    const status = response.status();
    const currentUrl = page.url();
    const isForbidden = status === 403;
    const isRedirectedToLogin = currentUrl.includes('/auth/login');
    const isUnauthorized = status === 401;

    expect(isForbidden || isRedirectedToLogin || isUnauthorized).toBeTruthy();
  }
}
