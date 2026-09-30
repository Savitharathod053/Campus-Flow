import { test, expect } from '@playwright/test';

test.describe('Smoke - Application Health & Static Assets', () => {
  test('static CSS and Bootstrap assets load with HTTP 200', async ({ request, page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });

    // Verify main stylesheet
    const cssLinks = await page.$$eval('link[rel="stylesheet"]', (links) =>
      links.map((l) => (l as HTMLLinkElement).href)
    );

    expect(cssLinks.length).toBeGreaterThan(0);

    for (const href of cssLinks.slice(0, 3)) {
      if (href.startsWith('http')) {
        const resp = await request.get(href);
        expect(resp.status(), `Stylesheet ${href} should load with 200`).toBe(200);
      }
    }
  });

  test('non-existent route returns clean 404 page rather than 500 server crash', async ({ page }) => {
    const response = await page.goto('/random-non-existent-route-xyz-999', {
      waitUntil: 'domcontentloaded',
    });

    expect(response?.status()).toBe(404);
  });
});
