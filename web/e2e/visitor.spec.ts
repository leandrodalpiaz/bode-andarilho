import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("visitante solicita presença e consulta o recibo", async ({ page }) => {
  let submittedPresence: Record<string, unknown> | null = null;
  let idempotencyKey = "";

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/config") {
      await route.fulfill({ json: { captcha_required: false } });
      return;
    }
    if (path === "/api/v1/public/eventos/token-publico" && request.method() === "GET") {
      await route.fulfill({
        json: {
          titulo: "Sessão aberta",
          evento_at: "2026-09-10T23:00:00Z",
          descricao: "Encontro semanal",
          rito: "REAA",
          traje_obrigatorio: "Traje maçônico",
          status: "published",
          visibilidade: "public",
          loja: { nome: "Loja Piloto", cidade: "São Paulo", uf: "SP" },
        },
      });
      return;
    }
    if (path === "/api/v1/public/eventos/token-publico/presencas" && request.method() === "POST") {
      submittedPresence = request.postDataJSON() as Record<string, unknown>;
      idempotencyKey = request.headers()["idempotency-key"] || "";
      await route.fulfill({ status: 201, json: { status: "pending", receipt: "recibo-opaco" } });
      return;
    }
    if (path === "/api/v1/public/presencas/recibo-opaco" && request.method() === "GET") {
      await route.fulfill({
        json: {
          visitante_nome: "Visitante Teste",
          status: "pending",
          created_at: "2026-09-01T13:00:00Z",
        },
      });
      return;
    }
    await route.fulfill({ status: 404, json: { error: { message: `Rota simulada ausente: ${path}` } } });
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/evento/token-publico");

  await expect(page.getByRole("heading", { name: "Sessão aberta" })).toBeVisible();
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);

  await page.getByLabel("Seu nome").fill("Visitante Teste");
  await page.getByLabel("E-mail (opcional)").fill("visitante@example.com");
  await page.getByLabel("Ágape").selectOption("com");
  await page.getByRole("button", { name: "Solicitar presença" }).click();

  await expect(page.getByText("Solicitação recebida")).toBeVisible();
  await expect(page.getByText("recibo-opaco")).toBeVisible();
  expect(submittedPresence).toMatchObject({
    nome: "Visitante Teste",
    email: "visitante@example.com",
    agape: "com",
  });
  expect(idempotencyKey).not.toBe("");

  await page.getByRole("link", { name: "Consultar status do recibo" }).click();
  await expect(page.getByRole("heading", { name: "Status da solicitação" })).toBeVisible();
  await expect(page.getByText("Pendente de revisão")).toBeVisible();
});
