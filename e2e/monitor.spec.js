const { test, expect } = require("@playwright/test");

async function login(page) {
  await page.goto("/monitor");
  await page.locator("#loginUsername").fill("national_admin");
  await page.locator("#loginPassword").fill("admin1234");
  await page.locator("#monitorLogin button").click();
  await expect(page.getByRole("heading", { name: "대한민국 통합 관제 지도" })).toBeVisible();
  await expect(page.locator(".region-status-icon").first()).toBeVisible();
}

test("monitor login has no horizontal overflow", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith("desktop"), "desktop project only");
  await page.goto("/monitor");
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth
  );
  expect(overflow).toBeLessThanOrEqual(1);
  await expect(page).toHaveScreenshot("monitor-login.png", {
    animations: "disabled",
    fullPage: true,
    mask: [page.locator("#clock"), page.locator("[data-ago]")]
  });
});

test("monitor map and side panels stay inside the workspace", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith("desktop"), "desktop project only");
  await login(page);
  const layout = await page.evaluate(() => {
    const workspace = document.querySelector(".workspace").getBoundingClientRect();
    const map = document.querySelector("#map").getBoundingClientRect();
    const detail = document.querySelector(".detail-panel").getBoundingClientRect();
    return {
      workspaceHeight: workspace.height,
      mapHeight: map.height,
      mapBottom: map.bottom,
      workspaceBottom: workspace.bottom,
      detailBottom: detail.bottom
    };
  });
  expect(layout.workspaceHeight).toBeLessThanOrEqual(700);
  expect(layout.mapHeight).toBeGreaterThan(350);
  expect(layout.mapBottom).toBeLessThanOrEqual(layout.workspaceBottom + 1);
  expect(layout.detailBottom).toBeLessThanOrEqual(layout.workspaceBottom + 1);
  await expect(page).toHaveScreenshot("monitor-dashboard.png", {
    animations: "disabled",
    fullPage: true,
    mask: [page.locator("#clock"), page.locator("[data-ago]")],
    maxDiffPixelRatio: 0.01
  });
});

test("mobile dashboard does not clip Korean controls", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith("mobile"), "mobile project only");
  await login(page);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth
  );
  expect(overflow).toBeLessThanOrEqual(1);
  await expect(page.getByRole("heading", { name: "활성 알림", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "사용자 상세", exact: true })).toBeVisible();
  await expect(page).toHaveScreenshot("monitor-mobile.png", {
    animations: "disabled",
    fullPage: true,
    mask: [page.locator("#clock"), page.locator("[data-ago]")],
    maxDiffPixelRatio: 0.01
  });
});
