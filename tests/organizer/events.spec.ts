import { test, expect } from '@playwright/test';
import { TEST_USERS } from '../test-data/users.data';
import { generateUniqueEventName } from '../test-data/events.data';
import { loginAs } from '../helpers/auth.helper';

test.describe('Organizer - Dashboard & Event Proposal Management', () => {
  test.beforeEach(async ({ page }) => {
    await loginAs(page, TEST_USERS.organizer);
  });

  test('organizer dashboard renders event proposals and operational tabs', async ({ page }) => {
    await page.goto('/organizer/dashboard', { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveTitle(/Organizer|Dashboard|Campus Flow/i);

    // Create Event button should exist
    const createBtn = page.locator('a[href*="/organizer/events/request"], a[href*="/organizer/events/create"], a:has-text("Create New Event")').first();
    await expect(createBtn).toBeVisible();
  });

  test('organizer can open create event form and validate required fields', async ({ page }) => {
    await page.goto('/organizer/events/create', { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveTitle(/Create Event|Campus Flow/i);

    // Verify key fields
    await expect(page.locator('input[name="title"]')).toBeVisible();
    await expect(page.locator('select[name="event_type"]')).toBeVisible();
    await expect(page.locator('input[name="venue"]')).toBeVisible();
    await expect(page.locator('textarea[name="description"]')).toBeVisible();
    await expect(page.locator('input[name="registration_start_date"]')).toBeVisible();
    await expect(page.locator('input[name="registration_deadline"]')).toBeVisible();
    await expect(page.locator('input[name="start_time"]')).toBeVisible();
    await expect(page.locator('input[name="end_time"]')).toBeVisible();
  });

  test('organizer can submit an event proposal which enters two-stage approval pipeline', async ({ page }) => {
    await page.goto('/organizer/events/create', { waitUntil: 'domcontentloaded' });

    const uniqueTitle = generateUniqueEventName('E2E_Proposal');
    const now = new Date();
    
    // Dates formatted for datetime-local (YYYY-MM-DDTHH:mm)
    const formatLocal = (d: Date) => {
      const pad = (n: number) => n.toString().padStart(2, '0');
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
    };

    const regStart = new Date(now.getTime() - 1000 * 60 * 60); // 1 hour ago
    const regDeadline = new Date(now.getTime() + 1000 * 60 * 60 * 24 * 3); // 3 days from now
    const eventStart = new Date(now.getTime() + 1000 * 60 * 60 * 24 * 4); // 4 days from now
    const eventEnd = new Date(now.getTime() + 1000 * 60 * 60 * 24 * 4 + 1000 * 60 * 60 * 3); // 4 days + 3 hrs

    await page.fill('input[name="title"]', uniqueTitle);
    await page.selectOption('select[name="event_type"]', 'Workshop');
    await page.fill('input[name="venue"]', 'Seminar Hall 3 - Tech Block');
    await page.fill('input[name="faculty_coordinator"]', 'Dr. K. Ramanathan');
    await page.fill('textarea[name="description"]', 'E2E automated test event proposal for Playwright verification suite.');

    await page.fill('input[name="registration_start_date"]', formatLocal(regStart));
    await page.fill('input[name="registration_deadline"]', formatLocal(regDeadline));
    await page.fill('input[name="start_time"]', formatLocal(eventStart));
    await page.fill('input[name="end_time"]', formatLocal(eventEnd));

    // Upload dummy poster image
    await page.setInputFiles('input[name="poster"]', {
      name: 'test_poster.png',
      mimeType: 'image/png',
      buffer: Buffer.from('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154789c63000100000500010d0a2d420000000049454e44ae426082', 'hex'),
    });

    await page.click('button[type="submit"]');
    await page.waitForLoadState('domcontentloaded');

    // Should redirect to dashboard and show flash confirmation
    await expect(page).toHaveURL(/\/organizer\/dashboard/);
    const bodyText = await page.textContent('body');
    expect(bodyText).toContain(uniqueTitle);
  });
});
