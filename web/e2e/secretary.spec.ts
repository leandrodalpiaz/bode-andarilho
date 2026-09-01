import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const nowSeconds = Math.floor(Date.now() / 1000);
const authUser = {
  id: "00000000-0000-4000-8000-000000000001",
  aud: "authenticated",
  role: "authenticated",
  email: "secretario@example.com",
  email_confirmed_at: "2026-09-01T12:00:00Z",
  phone: "",
  app_metadata: { provider: "email", providers: ["email"] },
  user_metadata: {},
  identities: [],
  created_at: "2026-09-01T12:00:00Z",
  updated_at: "2026-09-01T12:00:00Z",
};

test("secretário entra por OTP, cria sessão e aprova presença", async ({ page }) => {
  let otpEmail = "";
  let verifiedCode = "";
  let createdEvent: Record<string, unknown> | null = null;
  let eventIdempotencyKey = "";
  let reviewAuthorization = "";
  let reviewIdempotencyKey = "";

  await page.route("**/supabase/auth/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/otp") && request.method() === "POST") {
      otpEmail = (request.postDataJSON() as { email: string }).email;
      await route.fulfill({ json: {} });
      return;
    }
    if (path.endsWith("/verify") && request.method() === "POST") {
      verifiedCode = (request.postDataJSON() as { token: string }).token;
      await route.fulfill({
        json: {
          access_token: "secretary-access-token",
          token_type: "bearer",
          expires_in: 3600,
          expires_at: nowSeconds + 3600,
          refresh_token: "secretary-refresh-token",
          user: authUser,
        },
      });
      return;
    }
    await route.fulfill({ status: 404, json: { message: `Auth simulado ausente: ${path}` } });
  });

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/config") {
      await route.fulfill({
        json: {
          supabase_url: "http://127.0.0.1:4173/supabase",
          supabase_publishable_key: "publishable-test-key",
        },
      });
      return;
    }
    if (path === "/api/v1/me" && request.method() === "GET") {
      await route.fulfill({
        json: {
          profile: { id: "profile-secretary", auth_user_id: authUser.id, email: authUser.email },
          is_global_admin: false,
          store_roles: { "1": ["secretary"] },
          stores: [{ id: 1, nome: "Loja Piloto", status: "active" }],
        },
      });
      return;
    }
    if (path === "/api/v1/eventos" && request.method() === "GET") {
      await route.fulfill({
        json: {
          items: [{
            id: 10,
            loja_id: 1,
            titulo: "Sessão aberta",
            evento_at: "2026-09-10T23:00:00Z",
            status: "published",
            visibilidade: "public",
            public_url: "/evento/token-publico",
          }],
        },
      });
      return;
    }
    if (path === "/api/v1/eventos" && request.method() === "POST") {
      createdEvent = request.postDataJSON() as Record<string, unknown>;
      eventIdempotencyKey = request.headers()["idempotency-key"] || "";
      await route.fulfill({
        status: 201,
        json: { id: 11, ...(createdEvent || {}), status: "draft", visibilidade: "private" },
      });
      return;
    }
    if (path === "/api/v1/eventos/10/presencas" && request.method() === "GET") {
      await route.fulfill({
        json: {
          items: [{
            id: 22,
            evento_id: 10,
            visitante_nome: "Visitante Teste",
            visitante_email: "visitante@example.com",
            agape: "com",
            status: "pending",
          }],
        },
      });
      return;
    }
    if (path === "/api/v1/presencas/22/aprovar" && request.method() === "POST") {
      reviewAuthorization = request.headers().authorization || "";
      reviewIdempotencyKey = request.headers()["idempotency-key"] || "";
      await route.fulfill({
        json: {
          id: 22,
          evento_id: 10,
          visitante_nome: "Visitante Teste",
          visitante_email: "visitante@example.com",
          agape: "com",
          status: "approved",
        },
      });
      return;
    }
    await route.fulfill({ status: 404, json: { error: { message: `Rota simulada ausente: ${path}` } } });
  });

  await page.goto("/");
  await page.getByLabel("E-mail").fill("SECRETARIO@example.com");
  await page.getByRole("button", { name: "Enviar código por e-mail" }).click();
  await expect(page.getByText("Código enviado")).toBeVisible();
  await page.getByLabel("Código").fill("123456");
  await page.getByRole("button", { name: "Confirmar código" }).click();

  await expect(page.getByRole("heading", { name: "secretario@example.com" })).toBeVisible();
  expect(otpEmail).toBe("secretario@example.com");
  expect(verifiedCode).toBe("123456");
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);

  await page.getByLabel("Título", { exact: true }).fill("Sessão automatizada");
  await page.getByLabel("Data e hora", { exact: true }).fill("2026-09-12T19:30");
  await page.getByRole("combobox", { name: "Loja", exact: true }).selectOption("1");
  await page.getByRole("button", { name: "Salvar sessão" }).click();
  await expect(page.getByText("Sessão automatizada")).toBeVisible();
  expect(createdEvent).toMatchObject({ titulo: "Sessão automatizada", loja_id: 1 });
  expect(eventIdempotencyKey).not.toBe("");

  await page.getByRole("article").filter({ hasText: "Sessão aberta" }).getByRole("button", { name: "Presenças" }).click();
  const presence = page.getByRole("article").filter({ hasText: "Visitante Teste" });
  await expect(presence).toBeVisible();
  await presence.getByRole("button", { name: "Aprovar" }).click();
  await expect(presence.getByText("approved")).toBeVisible();
  expect(reviewAuthorization).toBe("Bearer secretary-access-token");
  expect(reviewIdempotencyKey).not.toBe("");
});
