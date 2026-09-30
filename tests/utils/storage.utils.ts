import { expect, APIRequestContext } from '@playwright/test';

/**
 * Validates that an asset URL is a permanent Supabase Storage URL
 * and STRICTLY DOES NOT point to Railway's ephemeral container disk (/static/uploads/).
 */
export function assertSupabaseStorageUrl(url: string | null | undefined, expectedFolder?: string): void {
  expect(url).toBeTruthy();
  const safeUrl = url as string;

  // STRICT REQUIREMENT: Ephemeral disk fallback must NEVER appear
  expect(safeUrl).not.toContain('/static/uploads/');
  expect(safeUrl).not.toContain('uploads/');

  // MUST be a valid Supabase Storage public CDN URL
  expect(safeUrl).toMatch(/^https:\/\/[a-zA-Z0-9-]+\.supabase\.co\/storage\/v1\/object\/public\/payment-proofs?\//);

  if (expectedFolder) {
    expect(safeUrl).toContain(`/${expectedFolder}/`);
  }
}

/**
 * Verifies that a public Supabase Storage URL actually resolves with HTTP 200.
 */
export async function assertAssetReachable(request: APIRequestContext, url: string): Promise<void> {
  const response = await request.get(url);
  expect(response.status(), `Asset ${url} returned HTTP ${response.status()}`).toBe(200);
}
