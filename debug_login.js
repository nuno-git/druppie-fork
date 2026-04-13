const { chromium } = require('playwright');
const fs = require('fs');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  const page = await context.newPage();

  // Collect console messages
  const consoleLogs = [];
  page.on('console', msg => {
    consoleLogs.push({ type: msg.type(), text: msg.text() });
  });

  // Collect page errors
  const pageErrors = [];
  page.on('pageerror', err => {
    pageErrors.push(err.message);
  });

  // Collect network failures
  const networkErrors = [];
  page.on('requestfailed', req => {
    networkErrors.push({ url: req.url(), failure: req.failure()?.errorText });
  });

  // Collect all responses for debugging
  const responses = [];
  page.on('response', resp => {
    if (resp.status() >= 400 || resp.url().includes('keycloak') || resp.url().includes('auth')) {
      responses.push({ url: resp.url(), status: resp.status() });
    }
  });

  let step = 0;
  const screenshot = async (name) => {
    step++;
    const path = `/home/nuno/Documents/druppie-testing-research/debug_screenshot_${step}_${name}.png`;
    await page.screenshot({ path, fullPage: true });
    console.log(`Screenshot ${step}: ${name} -> ${path}`);
  };

  try {
    // Step 1: Navigate to /chat
    console.log('\n=== STEP 1: Navigate to http://localhost:5373/chat ===');
    await page.goto('http://localhost:5373/chat', { waitUntil: 'networkidle', timeout: 15000 });
    console.log('URL after navigate:', page.url());
    await screenshot('initial_page');

    // Step 2: Get page content / look for login button
    console.log('\n=== STEP 2: Looking for login elements ===');
    const bodyText = await page.textContent('body');
    console.log('Body text (first 500 chars):', bodyText?.substring(0, 500));

    // Look for buttons
    const buttons = await page.$$eval('button, a[href*="login"], a[href*="auth"], [role="button"]', els =>
      els.map(e => ({ tag: e.tagName, text: e.textContent?.trim(), href: e.href, id: e.id, class: e.className }))
    );
    console.log('Buttons/links found:', JSON.stringify(buttons, null, 2));
    await screenshot('before_login_click');

    // Step 3: Click login button
    console.log('\n=== STEP 3: Clicking login button ===');
    // Try various selectors
    let loginClicked = false;
    for (const selector of [
      'button:has-text("Login")',
      'button:has-text("Sign in")',
      'button:has-text("Log in")',
      'a:has-text("Login")',
      'a:has-text("Sign in")',
      'a:has-text("Log in")',
      '#login-button',
      '[data-testid="login"]',
    ]) {
      const el = await page.$(selector);
      if (el) {
        console.log(`Found login element with selector: ${selector}`);
        await el.click();
        loginClicked = true;
        break;
      }
    }

    if (!loginClicked) {
      // Maybe we got redirected to Keycloak automatically
      console.log('No login button found, checking if already on Keycloak...');
      console.log('Current URL:', page.url());
    }

    // Wait a bit for redirect
    await page.waitForTimeout(3000);
    console.log('URL after login click/redirect:', page.url());
    await screenshot('after_login_click');

    // Step 4: Handle Keycloak login form
    console.log('\n=== STEP 4: Keycloak login form ===');
    const currentUrl = page.url();
    console.log('Current URL:', currentUrl);

    if (currentUrl.includes('keycloak') || currentUrl.includes('auth')) {
      console.log('On Keycloak page, filling in credentials...');

      // Look for username/password fields
      const inputs = await page.$$eval('input', els =>
        els.map(e => ({ type: e.type, name: e.name, id: e.id, placeholder: e.placeholder }))
      );
      console.log('Input fields:', JSON.stringify(inputs, null, 2));

      await screenshot('keycloak_form');

      // Fill username
      const usernameField = await page.$('#username') || await page.$('input[name="username"]');
      if (usernameField) {
        await usernameField.fill('admin');
        console.log('Filled username');
      }

      // Fill password
      const passwordField = await page.$('#password') || await page.$('input[name="password"]');
      if (passwordField) {
        await passwordField.fill('Admin123!');
        console.log('Filled password');
      }

      await screenshot('keycloak_filled');

      // Submit
      const submitBtn = await page.$('#kc-login') || await page.$('input[type="submit"]') || await page.$('button[type="submit"]');
      if (submitBtn) {
        console.log('Clicking submit...');
        await submitBtn.click();
      }

      // Wait for redirect
      await page.waitForTimeout(5000);
      console.log('URL after Keycloak submit:', page.url());
      await screenshot('after_keycloak_submit');

    } else {
      console.log('Not on Keycloak page. URL:', currentUrl);
    }

    // Step 5: Check post-login state
    console.log('\n=== STEP 5: Post-login state ===');
    console.log('Final URL:', page.url());

    const finalBodyText = await page.textContent('body');
    console.log('Body text (first 500 chars):', finalBodyText?.substring(0, 500));
    await screenshot('final_state');

    // Wait a bit more and check again
    await page.waitForTimeout(3000);
    console.log('URL after additional wait:', page.url());
    await screenshot('after_extra_wait');

    // Step 6: Check for errors
    console.log('\n=== STEP 6: Error analysis ===');
    console.log('Console logs:', JSON.stringify(consoleLogs, null, 2));
    console.log('\nPage errors:', JSON.stringify(pageErrors, null, 2));
    console.log('\nNetwork errors:', JSON.stringify(networkErrors, null, 2));
    console.log('\nHTTP responses (errors + auth):', JSON.stringify(responses, null, 2));

    // Check localStorage/sessionStorage for tokens
    const storage = await page.evaluate(() => {
      const ls = {};
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        ls[key] = localStorage.getItem(key)?.substring(0, 100) + '...';
      }
      const ss = {};
      for (let i = 0; i < sessionStorage.length; i++) {
        const key = sessionStorage.key(i);
        ss[key] = sessionStorage.getItem(key)?.substring(0, 100) + '...';
      }
      return { localStorage: ls, sessionStorage: ss };
    });
    console.log('\nStorage:', JSON.stringify(storage, null, 2));

    // Check cookies
    const cookies = await context.cookies();
    console.log('\nCookies:', JSON.stringify(cookies.map(c => ({ name: c.name, domain: c.domain, path: c.path })), null, 2));

    // Try to evaluate Keycloak state
    const kcState = await page.evaluate(() => {
      if (window.keycloak) {
        return {
          authenticated: window.keycloak.authenticated,
          token: window.keycloak.token?.substring(0, 50) + '...',
          subject: window.keycloak.subject
        };
      }
      return 'No window.keycloak found';
    });
    console.log('\nKeycloak JS state:', JSON.stringify(kcState, null, 2));

  } catch (err) {
    console.error('Error during debug:', err.message);
    await screenshot('error_state');
  }

  await browser.close();
})();
