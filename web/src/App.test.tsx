import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App, Notice } from "./App";

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("componentes essenciais da PWA", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("expõe avisos de erro como alerta acessível", () => {
    render(<Notice title="Atenção" tone="warning">Revise os dados.</Notice>);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Atenção");
    expect(alert).toHaveTextContent("Revise os dados.");
  });

  it("envia uma solicitação pública pendente com chave de idempotência", async () => {
    window.history.replaceState({}, "", "/evento/token-publico");
    let submittedBody: Record<string, unknown> | null = null;
    let submittedKey = "";
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), window.location.origin).pathname;
      if (path === "/api/v1/config") {
        return jsonResponse({ captcha_required: false });
      }
      if (path === "/api/v1/public/eventos/token-publico" && (init?.method || "GET") === "GET") {
        return jsonResponse({
          titulo: "Sessão aberta",
          evento_at: "2026-09-10T23:00:00Z",
          descricao: "Encontro semanal",
          status: "published",
          visibilidade: "public",
          loja: { nome: "Loja Piloto", cidade: "São Paulo", uf: "SP" },
        });
      }
      if (path === "/api/v1/public/eventos/token-publico/presencas" && init?.method === "POST") {
        submittedBody = JSON.parse(String(init.body));
        submittedKey = new Headers(init.headers).get("Idempotency-Key") || "";
        return jsonResponse({ status: "pending", receipt: "recibo-opaco" }, 201);
      }
      return jsonResponse({ error: { message: `Rota simulada ausente: ${path}` } }, 404);
    });
    vi.stubGlobal("fetch", fetchMock as typeof fetch);

    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Sessão aberta" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Seu nome"), "Visitante Teste");
    await user.type(screen.getByLabelText("E-mail (opcional)"), "visitante@example.com");
    await user.click(screen.getByRole("button", { name: "Solicitar presença" }));

    expect(await screen.findByText("Solicitação recebida")).toBeInTheDocument();
    expect(screen.getByText("recibo-opaco")).toBeInTheDocument();
    expect(submittedBody).toMatchObject({
      nome: "Visitante Teste",
      email: "visitante@example.com",
      agape: "sem",
    });
    expect(submittedKey).not.toBe("");
  });
});
