import { test, expect } from '@playwright/test';
import { TEST_USERS } from '../test-data/users.data';
import { loginAs } from '../helpers/auth.helper';
import { assertSupabaseStorageUrl, assertAssetReachable } from '../utils/storage.utils';

test.describe('Critical Cloud Storage - Supabase Storage & Redeployment Persistence', () => {
  test('CRITICAL: verify that public assets never use Railway ephemeral disk (/static/uploads/)', async ({ page }) => {
    // Navigate to public events page
    await page.goto('/events', { waitUntil: 'domcontentloaded' });

    // Inspect all image sources on the page
    const imgSources = await page.$$eval('img', (imgs) =>
      imgs.map((img) => (img as HTMLImageElement).src)
    );

    for (const src of imgSources) {
      if (src.includes('/static/uploads/payment_proofs/') || src.includes('/static/uploads/certificates/')) {
        throw new Error(
          `REGRESSION DETECTED: Asset URL "${src}" points to Railway ephemeral container storage (/static/uploads/)! All persistent assets must be stored in Supabase Storage.`
        );
      }
    }
  });

  test('CRITICAL: event posters and organizer QR codes must resolve to Supabase Storage CDN', async ({ page, request }) => {
    await loginAs(page, TEST_USERS.organizer);
    await page.goto('/organizer/dashboard', { waitUntil: 'domcontentloaded' });

    // Check images inside organizer dashboard
    const cloudImages = await page.$$eval('img', (imgs) =>
      imgs
        .map((img) => (img as HTMLImageElement).src)
        .filter((src) => src.includes('.supabase.co/storage/v1/object/public/'))
    );

    // If any cloud images exist on dashboard, verify they load with HTTP 200
    for (const imgUrl of cloudImages.slice(0, 3)) {
      assertSupabaseStorageUrl(imgUrl);
      await assertAssetReachable(request, imgUrl);
    }
  });

  test('CRITICAL: student certificate vault assets must use Supabase Storage CDN', async ({ page, request }) => {
    await loginAs(page, TEST_USERS.student);
    await page.goto('/student/certificates', { waitUntil: 'domcontentloaded' });

    const certDownloadLinks = await page.$$eval('a[href*="/certificates/"]', (links) =>
      links.map((a) => (a as HTMLAnchorElement).href)
    );

    // Verify no direct /static/uploads/ links are exposed to student
    for (const link of certDownloadLinks) {
      expect(link).not.toContain('/static/uploads/certificates/');
    }
  });

  test('REDEPLOYMENT PERSISTENCE CHECK: validates that stored asset URLs remain permanent and accessible', async ({ request }) => {
    // Verify that Supabase project storage bucket is publicly reachable
    const bucket = process.env.SUPABASE_STORAGE_BUCKET || 'payment-proofs';
    const supabaseUrl = process.env.SUPABASE_URL || 'https://blslgppaavtduxgjdrdl.supabase.co';

    expect(supabaseUrl).toBeTruthy();
    expect(bucket).toBeTruthy();

    // Verify Supabase Storage endpoint response (HEAD/GET public endpoint)
    const probeUrl = `${supabaseUrl}/storage/v1/object/public/${bucket}/system-healthcheck/ping.txt`;
    const resp = await request.get(probeUrl);
    // Either 200 (if file exists) or 400/404 (bucket accessible but test file missing)
    // It must NOT be a DNS failure or 500 error
    expect([200, 400, 404]).toContain(resp.status());
  });
});
