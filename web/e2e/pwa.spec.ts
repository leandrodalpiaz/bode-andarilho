import { expect, test } from "@playwright/test";

test("publica contrato instalável, controla o shell e reage à atualização", async ({ page }) => {
  await page.route("**/api/v1/config", async (route) => {
    await route.fulfill({
      json: {
        supabase_url: "http://127.0.0.1:4173/supabase",
        supabase_publishable_key: "publishable-test-key",
      },
    });
  });

  await page.goto("/");
  await page.waitForFunction(() => Boolean(navigator.serviceWorker?.controller) || Boolean(navigator.serviceWorker?.ready));

  const contract = await page.evaluate(async () => {
    const registration = await navigator.serviceWorker.ready;
    const manifest = await fetch("/manifest.webmanifest").then((response) => response.json());
    const cacheNames = await caches.keys();
    return {
      scriptUrl: registration.active?.scriptURL || "",
      controlled: Boolean(navigator.serviceWorker.controller),
      manifest,
      cacheNames,
    };
  });

  expect(contract.scriptUrl).toContain("/sw.js");
  expect(contract.manifest.display).toBe("standalone");
  expect(contract.manifest.icons).toEqual(expect.arrayContaining([
    expect.objectContaining({ src: "/icon-192.png", sizes: "192x192", type: "image/png" }),
    expect.objectContaining({ src: "/icon-512.png", sizes: "512x512", type: "image/png" }),
  ]));
  expect(contract.cacheNames).toContain("bode-andarilho-shell-v3");

  await page.evaluate(() => window.dispatchEvent(new Event("pwa-update")));
  await expect(page.getByRole("status")).toContainText("Nova versão disponível");
  await expect(page.getByRole("button", { name: "Atualizar agora" })).toBeVisible();
});
