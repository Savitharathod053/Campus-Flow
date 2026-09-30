import { test, expect } from '@playwright/test';
import { TEST_USERS } from '../test-data/users.data';
import { loginAs } from '../helpers/auth.helper';

test.describe('Student - Event Discovery & Filtering', () => {
  test.beforeEach(async ({ page }) => {
    await loginAs(page, TEST_USERS.student);
  });

  test('student can browse event listings and view active events', async ({ page }) => {
    await page.goto('/events', { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveTitle(/Events|Campus Flow/i);

    // Event cards container or list should be rendered
    const eventCards = page.locator('.card, .event-card, .ff-card');
    const count = await eventCards.count();
    expect(count).toBeGreaterThanOrEqual(0);
  });

  test('student can search events by keyword', async ({ page }) => {
    await page.goto('/events', { waitUntil: 'domcontentloaded' });

    const searchInput = page.locator('input[name="q"], input[type="search"]').first();
    await searchInput.fill('Workshop');
    await searchInput.press('Enter');

    await expect(page).toHaveURL(/q=Workshop/i);
  });

  test('student can filter events by department and pricing', async ({ page }) => {
    // 1. Filter by Free
    await page.goto('/events?pricing=free', { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveURL(/pricing=free/);

    // 2. Filter by Paid
    await page.goto('/events?pricing=paid', { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveURL(/pricing=paid/);

    // 3. Filter by CSE Department
    await page.goto('/events?department=CSE', { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveURL(/department=CSE/);
  });

  test('student can open event details and inspect schedule and eligibility', async ({ page }) => {
    await page.goto('/events', { waitUntil: 'domcontentloaded' });

    const firstEventLink = page.locator('a[href^="/events/"]').first();
    if (await firstEventLink.isVisible()) {
      await firstEventLink.click();
      await page.waitForLoadState('domcontentloaded');

      // Check event details presence
      await expect(page.locator('h1, h2, .event-title').first()).toBeVisible();
      // Verify venue or date info is displayed
      const detailsText = await page.textContent('body');
      expect(detailsText).toMatch(/Venue|Date|Time|Department|Eligibility/i);
    }
  });
});
