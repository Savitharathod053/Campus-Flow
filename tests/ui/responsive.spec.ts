import { test, expect } from '@playwright/test';
import { assertNoHorizontalOverflow } from '../utils/ui.utils';

const VIEWPORTS = [
  { name: 'Desktop Full HD (1920x1080)', width: 1920, height: 1080 },
  { name: 'Desktop Standard (1366x768)', width: 1366, height: 768 },
  { name: 'Tablet iPad (768x1024)', width: 768, height: 1024 },
  { name: 'Mobile iPhone (390x844)', width: 390, height: 844 },
  { name: 'Mobile Android (412x915)', width: 412, height: 915 },
];

test.describe('Responsive Layout & No Horizontal Overflow', () => {
  for (const vp of VIEWPORTS) {
    test(`homepage renders without horizontal overflow at ${vp.name}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto('/', { waitUntil: 'domcontentloaded' });
      await assertNoHorizontalOverflow(page);
    });

    test(`events catalog renders without horizontal overflow at ${vp.name}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto('/events', { waitUntil: 'domcontentloaded' });
      await assertNoHorizontalOverflow(page);
    });

    test(`auth login page renders without horizontal overflow at ${vp.name}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto('/auth/login', { waitUntil: 'domcontentloaded' });
      await assertNoHorizontalOverflow(page);
    });
  }
});
