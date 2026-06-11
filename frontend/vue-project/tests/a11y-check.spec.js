import { test, expect } from '@playwright/test';
import { AxeBuilder } from '@axe-core/playwright';

const BASE = 'http://127.0.0.1:9000';
const ROUTES = [
  { path: '/login', name: 'Login' },
  { path: '/', name: 'Dashboard' },
  { path: '/backtest', name: 'Backtest' },
  { path: '/reports-center', name: 'Reports' },
  { path: '/account', name: 'Account' },
];

test.describe('H: a11y scan', () => {
  for (const route of ROUTES) {
    test('H01-H04 ' + route.name, async ({ page }) => {
      test.setTimeout(60000);
      await page.goto(BASE + '/#' + route.path, { waitUntil: 'networkidle', timeout: 30000 }).catch(() => {});
      await page.waitForTimeout(3000);
      
      const results = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa'])
        .analyze();
      
      const critical = results.violations.filter(v => v.impact === 'critical');
      const serious = results.violations.filter(v => v.impact === 'serious');
      
      if (results.violations.length > 0) {
        console.log('\n' + route.name + ': ' + results.violations.length + ' violations');
        for (const v of results.violations) {
          console.log('  [' + v.impact + '] ' + v.id + ': ' + v.help);
        }
      }
      
      expect(critical.length).toBe(0);
    });
  }
});
