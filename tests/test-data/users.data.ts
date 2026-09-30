/**
 * Campus Flow E2E - Canonical Test Users & Credentials
 * Reads from process.env with fallbacks to the confirmed college accounts.
 */

export interface TestUser {
  identifier: string; // Email or Roll Number
  email: string;
  password: string;
  role: 'student' | 'organizer' | 'hod' | 'students_affairs_dean' | 'super_admin';
  displayName: string;
  expectedDashboardPath: string;
}

export const TEST_USERS = {
  student: {
    identifier: process.env.TEST_STUDENT_ROLL || 'DEMO2026CS001',
    email: process.env.TEST_STUDENT_EMAIL || 'student.demo@college.edu',
    password: process.env.TEST_STUDENT_PASSWORD || 'Demo@123',
    role: 'student' as const,
    displayName: 'Demo Student',
    expectedDashboardPath: '/student/dashboard',
  },
  organizer: {
    identifier: process.env.TEST_ORGANIZER_ROLL || 'DEMO2026ORG001',
    email: process.env.TEST_ORGANIZER_EMAIL || 'organizer.demo@college.edu',
    password: process.env.TEST_ORGANIZER_PASSWORD || 'Demo@123',
    role: 'organizer' as const,
    displayName: 'Demo Organizer',
    expectedDashboardPath: '/organizer/dashboard',
  },
  hod: {
    identifier: process.env.TEST_HOD_EMAIL || 'admin.cse@college.edu',
    email: process.env.TEST_HOD_EMAIL || 'admin.cse@college.edu',
    password: process.env.TEST_HOD_PASSWORD || 'Pass@123',
    role: 'hod' as const,
    displayName: 'Dr. K. Ramanathan',
    expectedDashboardPath: '/hod/dashboard',
  },
  dean: {
    identifier: process.env.TEST_DEAN_EMAIL || 'admin@college.edu',
    email: process.env.TEST_DEAN_EMAIL || 'admin@college.edu',
    password: process.env.TEST_DEAN_PASSWORD || 'Pass@123',
    role: 'students_affairs_dean' as const,
    displayName: 'Dr. S. K. Narayanan',
    expectedDashboardPath: '/dean/dashboard',
  },
  superadmin: {
    identifier: process.env.TEST_SUPERADMIN_EMAIL || 'superadmin@college.edu',
    email: process.env.TEST_SUPERADMIN_EMAIL || 'superadmin@college.edu',
    password: process.env.TEST_SUPERADMIN_PASSWORD || 'Admin@123',
    role: 'super_admin' as const,
    displayName: 'Chief Super Admin',
    expectedDashboardPath: '/admin/dashboard',
  },
};
