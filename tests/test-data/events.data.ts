/**
 * Campus Flow E2E - Dynamic Test Data Generator
 * Generates unique event names, transaction IDs, and registration codes
 * to ensure database safety and avoid collisions with production records.
 */

export function generateUniqueTimestamp(): string {
  return `${Date.now()}`;
}

export function generateUniqueEventName(prefix = 'E2E_Test_Event'): string {
  const ts = Date.now().toString().slice(-6);
  return `${prefix}_${ts}`;
}

export function generateTestTransactionId(prefix = 'TXN_E2E'): string {
  const rand = Math.floor(100000000000 + Math.random() * 900000000000); // 12-digit UTR
  return `${rand}`;
}

export interface TestEventData {
  title: string;
  description: string;
  venue: string;
  eventType: string;
  maxParticipants: number;
  isFree: boolean;
  registrationFee?: number;
  upiId?: string;
  upiNumber?: string;
  allowedDepartments?: string;
  allowedYears?: string;
}

export function getMockEventData(isFree = true): TestEventData {
  const title = generateUniqueEventName(isFree ? 'E2E_Free_Workshop' : 'E2E_Paid_Hackathon');
  return {
    title,
    description: `End-to-End automated testing event created by Playwright on ${new Date().toISOString()}. Non-production test data.`,
    venue: 'Auditorium Hall C - Block 2',
    eventType: 'WORKSHOP',
    maxParticipants: 50,
    isFree,
    registrationFee: isFree ? 0 : 250,
    upiId: isFree ? undefined : 'organizer.demo@upi',
    upiNumber: isFree ? undefined : '9876543210',
    allowedDepartments: 'ALL',
    allowedYears: 'ALL',
  };
}
