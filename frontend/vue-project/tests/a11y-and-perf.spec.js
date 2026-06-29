import { test, expect } from '@playwright/test';
import { AxeBuilder } from '@axe-core/playwright';

const BASE = 'http://127.0.0.1:9000';
const ROUTES = [
  { path: '/login', name: 'Login' },
  { path: '/', name: 'Dashboard' },
  { path: '/indicator-ide', name: 'IndicatorIDE' },
  { path: '/screener', name: 'Screener' },
  { path: '/watchlist', name: 'Watchlist' },
  { path: '/ai-analysis', name: 'AIAnalysis' },
  { path: '/backtest', name: 'Backtest' },
  { path: '/factor-manager', name: 'FactorManager' },
  { path: '/strategy-templates', name: 'StrategyTemplates' },
  { path: '/reports-center', name: 'ReportsCenter' },
  { path: '/account', name: 'Account' },
];

// H01-H04: axe-core a11y scan
test.describe('H: Accessibility', () => {
  for (const route of ROUTES) {
    test(`H01-H04 ${route.name} a11y`, async ({ page }) => {
      test.setTimeout(30000);
      await page.goto(BASE + '/#' + route.path, { waitUntil: 'networkidle', timeout: 20000 }).catch(() => {});
      await page.waitForTimeout(2000);
      
      const results = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
        .analyze();
      
      const critical = results.violations.filter(v => v.impact === 'critical');
      const serious = results.violations.filter(v => v.impact === 'serious');
      
      if (results.violations.length > 0) {
        console.log('\n' + route.name + ': ' + results.violations.length + ' violations');
        for (const v of results.violations) {
          console.log('  [' + v.impact + '] ' + v.id + ': ' + v.help + ' (' + v.nodes.length + ' nodes)');
        }
      }
      
      expect(critical.length).toBe(0);
      expect(serious.length).toBeLessThanOrEqual(5);
    });
  }
});

// F01: Performance baseline
test.describe('F01: Performance', () => {
  for (const route of ROUTES) {
    test('F01 ' + route.name + ' perf', async ({ page }) => {
      test.setTimeout(20000);
      await page.goto(BASE + '/#' + route.path, { waitUntil: 'networkidle', timeout: 15000 }).catch(() => {});
      await page.waitForTimeout(2000);
      
      const metrics = await page.evaluate(() => {
        const p = performance;
        const paint = p.getEntriesByType('paint');
        const navEntries = p.getEntriesByType('navigation');
        const nav = navEntries.length > 0 ? navEntries[0] : null;
        return {
          domContentLoaded: nav ? nav.domContentLoadedEventEnd : -1,
          loadEvent: nav ? nav.loadEventEnd : -1,
          domInteractive: nav ? nav.domInteractive : -1,
          firstPaint: paint.find(e => e.name === 'first-paint')?.startTime || -1,
          firstContentfulPaint: paint.find(e => e.name === 'first-contentful-paint')?.startTime || -1,
        };
      });
      
      console.log('\n' + route.name + ' perf: FCP=' + metrics.firstContentfulPaint.toFixed(0) + 'ms Load=' + metrics.loadEvent.toFixed(0) + 'ms');
      
      expect(metrics.firstContentfulPaint).toBeLessThan(8000);
      expect(metrics.loadEvent).toBeLessThan(15000);
    });
  }
});
