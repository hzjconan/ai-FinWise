/* Standalone documentation browser checks. No application server or database. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ channel: process.env.VISUAL_BROWSER_CHANNEL || 'chrome', headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 2 });
    const page = await context.newPage();
    const errors = [], externalRequests = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => { if (/^https?:/.test(request.url())) externalRequests.push(request.url()); });
    await page.goto(pathToFileURL(path.join(__dirname, 'robot-training-flow.html')).href);
    const text = id => page.locator(`#${id}`).innerText();
    assert.equal(await text('parameter-state'), 'θ₀ · 未更新');
    assert.equal(await text('prediction-value'), '尚未预测');
    assert.equal(await page.locator('#previous').isDisabled(), true);

    await page.locator('#next').click(); // Clear gradients, not weights.
    assert.equal(await text('parameter-state'), 'θ₀ · 未更新');
    await page.locator('#next').click(); // Forward.
    assert.equal(await text('prediction-value'), '+0.067307');
    assert.equal(await text('loss-value'), '尚未计算');
    await page.locator('#next').click(); // Loss.
    assert.equal(await text('loss-value'), '3.122642');
    await page.locator('#next').click(); // Backward must not update weights.
    assert.equal(await text('parameter-state'), 'θ₀ · 未更新');
    await page.locator('#next').click(); // Step updates weights, not cached prediction.
    assert.equal(await text('parameter-state'), 'θ₁ · 已更新');
    assert.equal(await text('prediction-value'), '+0.067307');
    assert.match(await text('step-takeaway'), /再做一次前向/);
    await page.locator('#next').click();
    assert.equal(await text('prediction-value'), '+0.001509');
    assert.equal(await text('loss-value'), '2.914682');
    assert.equal(await page.locator('#next').isDisabled(), true);
    await page.locator('#reset').click();
    assert.equal(await text('parameter-state'), 'θ₀ · 未更新');
    assert.equal(await text('loss-value'), '尚未计算');
    await page.locator('#play').click();
    await page.waitForFunction(() => document.getElementById('panel-update').dataset.stage === '1');
    await page.locator('#play').click(); // Pause must stop the timer.
    await page.waitForTimeout(1300);
    assert.equal(await page.locator('#panel-update').getAttribute('data-stage'), '1');
    await page.locator('#reset').click();
    await page.locator('#play').click();
    await page.waitForFunction(() => document.getElementById('panel-update').dataset.stage === '6', null, { timeout: 12000 });
    assert.equal(await text('prediction-value'), '+0.001509');
    assert.equal(await page.locator('#play').isDisabled(), true);

    await page.locator('#tab-history').click();
    assert.equal(await page.locator('#panel-update').isVisible(), false);
    assert.equal(await text('selected-train'), '0.0008');
    assert.equal(await text('selected-val'), '3.8373');
    assert.equal(await page.locator('#epoch-select option').count(), 31);
    await page.locator('#epoch-select').selectOption('0');
    assert.equal(await text('selected-train'), '—');
    assert.equal(await text('selected-val'), '2.5624');
    await page.locator('#epoch-select').selectOption('5');
    assert.equal(await text('selected-train'), '0.6525');
    assert.equal(await text('selected-val'), '4.3447');
    await page.locator('#history-chart circle[data-epoch="10"]').first().click();
    assert.equal(await text('selected-epoch'), '10');
    assert.equal(await text('selected-val'), '4.1917');
    await page.locator('#history-chart circle[data-epoch="20"]').first().focus();
    await page.keyboard.press('Enter');
    assert.equal(await text('selected-val'), '3.8907');

    await page.locator('#tab-checkpoint').click();
    assert.equal(await text('checkpoint-adam'), '80');
    assert.equal(await text('checkpoint-delta'), '0');
    await page.locator('input[value="without"]').check();
    assert.equal(await text('checkpoint-adam'), '40');
    assert.equal(await text('checkpoint-delta'), '0.029396');
    assert.equal(await text('checkpoint-val'), '4.342761');
    await page.locator('input[value="full"]').check();
    assert.equal(await text('checkpoint-delta'), '0');

    // Accessible tab keyboard navigation and timer reset.
    await page.locator('#tab-history').focus();
    await page.keyboard.press('Home');
    assert.equal(await page.locator('#tab-update').getAttribute('aria-selected'), 'true');
    await page.locator('#reset').click();
    await page.keyboard.press('ArrowRight');
    assert.equal(await page.locator('#panel-update').getAttribute('data-stage'), '1');
    await page.locator('#reset').click();
    for (let i = 0; i < 3; i++) await page.locator('#next').click();
    const screenshots = process.env.VISUAL_SCREENSHOT_DIR || os.tmpdir();
    fs.mkdirSync(screenshots, { recursive: true });
    await page.locator('#training-diagram').screenshot({ path: path.join(screenshots, 'robot-training-flow-preview.png') });
    await page.screenshot({ path: path.join(os.tmpdir(), 'robot-training-flow-desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    for (const tab of ['update', 'history', 'checkpoint']) {
      await page.locator(`#tab-${tab}`).click();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, `${tab} overflows mobile viewport`);
      assert.equal(await page.locator(`#panel-${tab} .metric-value`).evaluateAll(nodes => nodes.every(node =>
        node.getBoundingClientRect().height <= parseFloat(getComputedStyle(node).lineHeight) * 1.2
      )), true, `${tab} splits a metric number across lines`);
    }
    await page.screenshot({ path: path.join(os.tmpdir(), 'robot-training-flow-mobile.png'), fullPage: true });
    assert.deepEqual(errors, []);
    assert.deepEqual(externalRequests, []);
    const staticPage = await context.newPage();
    await staticPage.goto(pathToFileURL(path.join(__dirname, 'robot-training-flow.svg')).href);
    assert.equal(await staticPage.getByText('过去三帧视频').isVisible(), true);
    assert.equal(await staticPage.getByText('Adam：更新参数').isVisible(), true);
    await staticPage.close();
    console.log('PASS: update ordering, real-record replay, reset/autoplay, validation history, checkpoint toggle, keyboard tabs, mobile layout, offline use.');
    await context.close();
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
