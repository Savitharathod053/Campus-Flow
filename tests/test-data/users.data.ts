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
    identifier: (process.env.TEST_STUDENT_ROLL || '').trim() || 'DEMO2026CS001',
    email: (process.env.TEST_STUDENT_EMAIL || '').trim() || 'student.demo@college.edu',
    password: (process.env.TEST_STUDENT_PASSWORD || '').trim() || 'Demo@123',
    role: 'student' as const,
    displayName: 'Demo Student',
    expectedDashboardPath: '/student/dashboard',
  },
  organizer: {
    identifier: (process.env.TEST_ORGANIZER_ROLL || '').trim() || 'DEMO2026ORG001',
    email: (process.env.TEST_ORGANIZER_EMAIL || '').trim() || 'organizer.demo@college.edu',
    password: (process.env.TEST_ORGANIZER_PASSWORD || '').trim() || 'Demo@123',
    role: 'organizer' as const,
    displayName: 'Demo Organizer',
    expectedDashboardPath: '/organizer/dashboard',
  },
  hod: {
    identifier: (process.env.TEST_HOD_EMAIL || '').trim() || 'admin.cse@college.edu',
    email: (process.env.TEST_HOD_EMAIL || '').trim() || 'admin.cse@college.edu',
    password: (process.env.TEST_HOD_PASSWORD || '').trim() || 'Pass@123',
    role: 'hod' as const,
    displayName: 'Dr. K. Ramanathan',
    expectedDashboardPath: '/hod/dashboard',
  },
  dean: {
    identifier: (process.env.TEST_DEAN_EMAIL || '').trim() || 'admin@college.edu',
    email: (process.env.TEST_DEAN_EMAIL || '').trim() || 'admin@college.edu',
    password: (process.env.TEST_DEAN_PASSWORD || '').trim() || 'Pass@123',
    role: 'students_affairs_dean' as const,
    displayName: 'Dr. S. K. Narayanan',
    expectedDashboardPath: '/dean/dashboard',
  },
  superadmin: {
    identifier: (process.env.TEST_SUPERADMIN_EMAIL || '').trim() || 'superadmin@college.edu',
    email: (process.env.TEST_SUPERADMIN_EMAIL || '').trim() || 'superadmin@college.edu',
    password: (process.env.TEST_SUPERADMIN_PASSWORD || '').trim() || 'Admin@123',
    role: 'super_admin' as const,
    displayName: 'Chief Super Admin',
    expectedDashboardPath: '/admin/dashboard',
  },
};
