import { test as base, Page } from '@playwright/test';
import { TEST_USERS } from '../test-data/users.data';
import { loginAs } from '../helpers/auth.helper';

type AuthFixtures = {
  studentPage: Page;
  organizerPage: Page;
  hodPage: Page;
  deanPage: Page;
  adminPage: Page;
};

export const test = base.extend<AuthFixtures>({
  studentPage: async ({ browser }, use) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await loginAs(page, TEST_USERS.student);
    await use(page);
    await context.close();
  },

  organizerPage: async ({ browser }, use) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await loginAs(page, TEST_USERS.organizer);
    await use(page);
    await context.close();
  },

  hodPage: async ({ browser }, use) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await loginAs(page, TEST_USERS.hod);
    await use(page);
    await context.close();
  },

  deanPage: async ({ browser }, use) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await loginAs(page, TEST_USERS.dean);
    await use(page);
    await context.close();
  },

  adminPage: async ({ browser }, use) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await loginAs(page, TEST_USERS.superadmin);
    await use(page);
    await context.close();
  },
});

export { expect } from '@playwright/test';
