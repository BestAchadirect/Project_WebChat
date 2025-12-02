// @ts-check
const { test, expect } = require('@playwright/test');

test.describe('Chat Widget', () => {
    test.beforeEach(async ({ page }) => {
        // Assuming the app is running locally on port 5173 (Vite default)
        await page.goto('http://localhost:5173');
    });

    test('should open chat widget and send a message', async ({ page }) => {
        // 1. Verify header is present
        await expect(page.locator('h1')).toHaveText('Project WebChat');

        // 2. Locate input and send message
        const input = page.locator('input[type="text"]');
        await input.fill('Hello, world!');
        await page.locator('button:has-text("Send")').click();

        // 3. Verify user message appears
        await expect(page.locator('text=Hello, world!')).toBeVisible();

        // 4. Verify bot response appears (after mock delay)
        // Note: In a real test, we might wait for a specific response or API call
        await expect(page.locator('text=I received your message: Hello, world!')).toBeVisible({ timeout: 5000 });
    });
});
