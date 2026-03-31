# src/miniapp.py
# ============================================
# BODE ANDARILHO - TELEGRAM MINI APP
# ============================================
#
# Fornece formulários web para cadastro de membros, eventos e lojas,
# servidos diretamente pelo Starlette no Render.
#
# Rotas Starlette registradas em main.py:
#   GET  /webapp/cadastro_membro  <- get_cadastro_membro()
#   GET  /webapp/cadastro_evento  <- get_cadastro_evento()
#   GET  /webapp/cadastro_loja    <- get_cadastro_loja()
#   POST /api/cadastro_membro     <- api_cadastro_membro()
#   POST /api/cadastro_evento     <- api_cadastro_evento()
#   POST /api/cadastro_loja       <- api_cadastro_loja()
#   POST /api/lojas               <- api_listar_lojas()
#
# Segurança:
#   Toda submissão inclui o initData do Telegram WebApp SDK.
#   O servidor verifica a assinatura HMAC-SHA256 antes de processar.
#   O telegram_id é extraído **exclusivamente** do initData verificado,
#   nunca do corpo da requisição.
# ============================================

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, unquote

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.sheets_supabase import (
    buscar_membro,
    cadastrar_membro,
    cadastrar_evento,
    cadastrar_loja,
    listar_lojas,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# URLS DOS WEBAPPS (lidas do ambiente em import-time)
# ─────────────────────────────────────────────────────────────────────────────
def _webapp_base_url() -> str:
    raw = (os.getenv("RENDER_EXTERNAL_URL", "") or "").strip().rstrip("/")
    lowered = raw.lower()
    if not raw:
        return ""
    if not lowered.startswith("https://"):
        logger.warning("Mini App desativada: RENDER_EXTERNAL_URL precisa usar HTTPS. Valor atual: %s", raw)
        return ""
    if "seu-app.onrender.com" in lowered or "example.com" in lowered:
        logger.warning("Mini App desativada: RENDER_EXTERNAL_URL ainda está com placeholder. Valor atual: %s", raw)
        return ""
    return raw


_RENDER_URL = _webapp_base_url()
WEBAPP_URL_MEMBRO = f"{_RENDER_URL}/webapp/cadastro_membro" if _RENDER_URL else ""
WEBAPP_URL_EVENTO = f"{_RENDER_URL}/webapp/cadastro_evento" if _RENDER_URL else ""
WEBAPP_URL_LOJA   = f"{_RENDER_URL}/webapp/cadastro_loja"   if _RENDER_URL else ""

_GRUPO_PRINCIPAL_ID = os.getenv("GRUPO_PRINCIPAL_ID", "")


# ─────────────────────────────────────────────────────────────────────────────
# VERIFICAÇÃO DE SEGURANÇA (HMAC-SHA256 — padrão Telegram Mini App)
# ─────────────────────────────────────────────────────────────────────────────

def verify_telegram_webapp_data(init_data: str, bot_token: str) -> Optional[dict]:
    """
    Verifica a assinatura do initData conforme:
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

    Retorna o dict do usuário Telegram se válido; None caso contrário.
    Rejeita tokens com mais de 24 h (proteção contra replay attacks).
    """
    if not init_data or not bot_token:
        return None
    try:
        # parse_qsl URL-decodifica os valores automaticamente — obrigatório para
        # que o data_check_string bata com o que o Telegram assinou.
        params: Dict[str, str] = dict(parse_qsl(init_data, strict_parsing=False))

        hash_value = params.pop("hash", "")
        if not hash_value:
            return None

        # auth_date não pode ser muito antigo (24 h)
        auth_date = int(params.get("auth_date", 0))
        if time.time() - auth_date > 86400:
            logger.warning("initData expirado (auth_date=%s)", auth_date)
            return None

        # String de verificação: pares chave=valor ordenados por chave, separados por \n
        data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))

        # Chave secreta: HMAC-SHA256("WebAppData", bot_token)
        secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"), digestmod=hashlib.sha256).digest()
        expected = hmac.new(secret, data_check.encode("utf-8"), digestmod=hashlib.sha256).hexdigest()

        if not hmac.compare_digest(expected, hash_value):
            logger.warning("Assinatura initData inválida.")
            return None

        # parse_qsl já decodificou o valor de "user"; só precisa fazer o parse JSON
        return json.loads(params.get("user", "{}"))

    except Exception as e:
        logger.warning("Erro na verificação initData: %s", e)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS INTERNOS
# ─────────────────────────────────────────────────────────────────────────────

def _parse_data_ddmmyyyy(texto: str) -> Optional[datetime]:
    try:
        return datetime.strptime(texto.strip(), "%d/%m/%Y")
    except Exception:
        return None


def _escape_md(s: str) -> str:
    for ch in r"\_*[]()~`>#+-=|{}.!":
        s = (s or "").replace(ch, f"\\{ch}")
    return s


def _teclado_pos_publicacao(id_evento: str, agape_str: str) -> InlineKeyboardMarkup:
    """Teclado de confirmação de presença publicado no grupo (mesmo padrão do fluxo conversacional)."""
    tipo = (agape_str or "").lower()
    linhas: List[List[InlineKeyboardButton]] = []
    if "gratuito" in tipo:
        linhas.append([InlineKeyboardButton("🍽 Participar com ágape (gratuito)", callback_data=f"confirmar|{id_evento}|gratuito")])
        linhas.append([InlineKeyboardButton("🚫 Participar sem ágape", callback_data=f"confirmar|{id_evento}|sem")])
    elif "pago" in tipo:
        linhas.append([InlineKeyboardButton("🍽 Participar com ágape (pago)", callback_data=f"confirmar|{id_evento}|pago")])
        linhas.append([InlineKeyboardButton("🚫 Participar sem ágape", callback_data=f"confirmar|{id_evento}|sem")])
    else:
        linhas.append([InlineKeyboardButton("✅ Confirmar presença", callback_data=f"confirmar|{id_evento}|sem")])
    linhas.append([InlineKeyboardButton("👥 Ver confirmados", callback_data=f"ver_confirmados|{id_evento}")])
    return InlineKeyboardMarkup(linhas)


# ─────────────────────────────────────────────────────────────────────────────
# ESTILOS E JS BASE COMPARTILHADOS
# ─────────────────────────────────────────────────────────────────────────────

_CSS = """
:root{
  --bg:var(--tg-theme-bg-color,#fff);
  --text:var(--tg-theme-text-color,#000);
  --hint:var(--tg-theme-hint-color,#888);
  --link:var(--tg-theme-link-color,#2481cc);
  --btn:var(--tg-theme-button-color,#2481cc);
  --btn-text:var(--tg-theme-button-text-color,#fff);
  --sec:var(--tg-theme-secondary-bg-color,#f1f1f1);
  --border:rgba(128,128,128,.2);
  --select-bg:var(--tg-theme-secondary-bg-color,#f1f1f1);
  --select-text:var(--tg-theme-text-color,#000);
}
*{box-sizing:border-box;margin:0;padding:0}
body{
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg);color:var(--text);
  color-scheme:light dark;
  min-height:100vh;padding:12px 12px 84px;
}
h1{font-size:17px;font-weight:700;margin-bottom:14px}
.card{background:var(--sec);border-radius:12px;padding:12px 14px;margin-bottom:12px}
.card-title{font-size:12px;font-weight:600;color:var(--hint);
  text-transform:uppercase;letter-spacing:.6px;margin-bottom:12px}
.field{margin-bottom:14px}
.field:last-child{margin-bottom:0}
label{display:block;font-size:13px;color:var(--hint);margin-bottom:3px;font-weight:500}
input,textarea{
  width:100%;background:transparent;border:none;
  border-bottom:1px solid var(--border);padding:6px 0;
  font-size:16px;color:var(--text);outline:none;font-family:inherit;
  -webkit-appearance:none;appearance:none;
}
select{
  width:100%;background-color:var(--select-bg);border:none;
  border-bottom:1px solid var(--border);padding:6px 0;
  font-size:16px;color:var(--select-text);outline:none;font-family:inherit;
  -webkit-appearance:none;appearance:none;
}
select{
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 6'%3E%3Cpath fill='%23888' d='M5 6L0 0h10z'/%3E%3C/svg%3E");
  background-repeat:no-repeat;background-position:right 2px center;
  background-size:10px 6px;padding-right:20px;
}
option{background-color:var(--bg);color:var(--text)}
select:focus{border-bottom:1px solid var(--btn)}
textarea{
  border:1px solid var(--border);border-radius:8px;
  padding:8px;resize:none;min-height:64px;
}
input::placeholder,textarea::placeholder{color:var(--hint)}
.err{color:#ff3b30;font-size:12px;margin-top:3px;display:none}
.err.on{display:block}
.toast{
  position:fixed;bottom:76px;left:50%;transform:translateX(-50%);
  background:rgba(0,0,0,.75);color:#fff;padding:8px 18px;
  border-radius:20px;font-size:14px;display:none;z-index:99;
  white-space:nowrap;max-width:80vw;overflow:hidden;text-overflow:ellipsis;
}
.toast.on{display:block}
.info{font-size:12px;color:var(--hint);margin-top:3px}
.actions{position:sticky;bottom:0;background:linear-gradient(to top,var(--bg) 75%,rgba(255,255,255,0));padding:12px 0 20px;margin-top:8px}
.actions-stack{display:flex;flex-direction:column;gap:10px}
.btn-primary{
  width:100%;background:var(--btn);color:var(--btn-text);border:none;border-radius:12px;
  padding:14px 16px;font-size:16px;font-weight:700;box-shadow:0 8px 22px rgba(0,0,0,.12)
}
.btn-primary:disabled{opacity:.65}
.btn-secondary{
  width:100%;background:var(--sec);color:var(--text);border:1px solid var(--border);border-radius:12px;
  padding:13px 16px;font-size:15px;font-weight:600
}
"""

_JS_BASE = """
const tg=(window.Telegram && window.Telegram.WebApp) ? window.Telegram.WebApp : null;
if(tg){
  try{tg.ready();}catch(e){}
  try{tg.expand();}catch(e){}
}
function tgMB(action,...args){
  if(!tg || !tg.MainButton || typeof tg.MainButton[action] !== 'function') return;
  try{tg.MainButton[action](...args);}catch(e){}
}
function closeMiniApp(){
  if(tg && typeof tg.close === 'function'){
    try{tg.close();return;}catch(e){}
  }
  if(window.history.length > 1){
    window.history.back();
  }else{
    window.location.href='/';
  }
}
function setPrimaryLoading(isLoading){
  const btn=document.getElementById('btn_publicar_evento');
  if(btn){
    btn.disabled=!!isLoading;
    btn.textContent=isLoading?'Publicando...':'Publicar Evento';
  }
}
function showToast(msg,dur){
  const t=document.getElementById('toast');
  t.textContent=msg;t.classList.add('on');
  clearTimeout(t._tid);
  t._tid=setTimeout(()=>t.classList.remove('on'),dur||3000);
}
function setErr(id,msg){
  const e=document.getElementById(id+'_err');
  if(e){e.textContent=msg;e.classList.add('on');}
}
function clearErr(id){
  const e=document.getElementById(id+'_err');
  if(e) e.classList.remove('on');
}
function val(id){return((document.getElementById(id)||{}).value||'').trim();}
function req(id,label){
  const v=val(id);
  if(!v){setErr(id,label+' é obrigatório.');return false;}
  clearErr(id);return true;
}
function maskDate(el){
  el.addEventListener('input',function(){
    let s=this.value.replace(/\\D/g,'');
    if(s.length<=2)this.value=s;
    else if(s.length<=4)this.value=s.slice(0,2)+'/'+s.slice(2);
    else this.value=s.slice(0,2)+'/'+s.slice(2,4)+'/'+s.slice(4,8);
  });
}
"""

def _html_wrap(title: str, body: str, script: str) -> str:
    return (
        f'<!DOCTYPE html><html lang="pt-BR">'
        f'<head><meta charset="UTF-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">'
        f'<title>{title} — Bode Andarilho</title>'
        f'<script src="https://telegram.org/js/telegram-web-app.js"></script>'
        f'<style>{_CSS}</style></head>'
        f'<body><h1>🐐 {title}</h1>'
        f'{body}'
        f'<div id="toast" class="toast"></div>'
        f'<script>{_JS_BASE}{script}</script>'
        f'</body></html>'
    )


# ─────────────────────────────────────────────────────────────────────────────
# HTML — CADASTRO DE MEMBRO
# ─────────────────────────────────────────────────────────────────────────────

def html_cadastro_membro() -> str:
    body = """
<div class="card">
  <div class="card-title">Identificação</div>
  <div class="field">
    <label for="nome">Nome completo *</label>
    <input id="nome" type="text" placeholder="Como consta no quadro da loja" autocomplete="name">
    <div id="nome_err" class="err"></div>
  </div>
  <div class="field">
    <label for="data_nasc">Data de nascimento * <span class="info">(DD/MM/AAAA)</span></label>
    <input id="data_nasc" type="text" placeholder="25/03/1985" maxlength="10" inputmode="numeric">
    <div id="data_nasc_err" class="err"></div>
  </div>
  <div class="field">
    <label for="grau">Grau *</label>
    <select id="grau">
      <option value="">Selecione…</option>
      <option>Aprendiz</option>
      <option>Companheiro</option>
      <option>Mestre</option>
      <option>Mestre Instalado</option>
    </select>
    <div id="grau_err" class="err"></div>
  </div>
  <div class="field">
    <label for="vm">Venerável Mestre? *</label>
    <select id="vm">
      <option value="">Selecione…</option>
      <option value="Sim">Sim</option>
      <option value="Não">Não</option>
    </select>
    <div id="vm_err" class="err"></div>
  </div>
</div>
<div class="card">
  <div class="card-title">Sua Loja</div>
  <div class="field">
    <label for="loja">Nome da loja *</label>
    <input id="loja" type="text" placeholder="Ex.: Luz da Fraternidade">
    <div id="loja_err" class="err"></div>
  </div>
  <div class="field">
    <label for="numero_loja">Número <span class="info">(0 se não houver)</span></label>
    <input id="numero_loja" type="text" value="0" inputmode="numeric" maxlength="8">
  </div>
  <div class="field">
    <label for="oriente">Oriente *</label>
    <input id="oriente" type="text" placeholder="Ex.: São Paulo / SP">
    <div id="oriente_err" class="err"></div>
  </div>
  <div class="field">
    <label for="potencia">Potência *</label>
    <input id="potencia" type="text" placeholder="Ex.: GLESP">
    <div id="potencia_err" class="err"></div>
  </div>
</div>
"""
    script = """
maskDate(document.getElementById('data_nasc'));
function validate(){
  let ok=true;
  ok=req('nome','Nome')&&ok;
  const dn=val('data_nasc');
  if(!dn.match(/^\\d{2}\\/\\d{2}\\/\\d{4}$/)){
    setErr('data_nasc','Use o formato DD/MM/AAAA.');ok=false;
  }else clearErr('data_nasc');
  ok=req('grau','Grau')&&ok;
  ok=req('vm','Venerável Mestre')&&ok;
  ok=req('loja','Nome da loja')&&ok;
  ok=req('oriente','Oriente')&&ok;
  ok=req('potencia','Potência')&&ok;
  return ok;
}
tg.MainButton.setText('Confirmar Cadastro');
tg.MainButton.show();
tg.MainButton.onClick(async()=>{
  if(!validate())return;
  tg.MainButton.showProgress(false);
  tg.MainButton.disable();
  try{
    const r=await fetch('/api/cadastro_membro',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        init_data:tg.initData,
        nome:val('nome'),
        data_nasc:val('data_nasc'),
        grau:val('grau'),
        vm:val('vm'),
        loja:val('loja'),
        numero_loja:val('numero_loja')||'0',
        oriente:val('oriente'),
        potencia:val('potencia')
      })
    });
    const j=await r.json();
    if(j.ok){tg.close();}
    else{showToast(j.error||'Erro. Tente novamente.');tg.MainButton.hideProgress();tg.MainButton.enable();}
  }catch{showToast('Falha de conexão. Tente novamente.');tg.MainButton.hideProgress();tg.MainButton.enable();}
});
"""
    return _html_wrap("Cadastro de Membro", body, script)


# ─────────────────────────────────────────────────────────────────────────────
# HTML — CADASTRO DE LOJA
# ─────────────────────────────────────────────────────────────────────────────

def html_cadastro_loja() -> str:
    body = """
<div class="card">
  <div class="card-title">Dados da Loja</div>
  <div class="field">
    <label for="nome_loja">Nome da loja *</label>
    <input id="nome_loja" type="text" placeholder="Ex.: Luz da Fraternidade">
    <div id="nome_loja_err" class="err"></div>
  </div>
  <div class="field">
    <label for="numero">Número <span class="info">(0 se não houver)</span></label>
    <input id="numero" type="text" value="0" inputmode="numeric" maxlength="8">
  </div>
  <div class="field">
    <label for="oriente">Oriente *</label>
    <input id="oriente" type="text" placeholder="Ex.: São Paulo / SP">
    <div id="oriente_err" class="err"></div>
  </div>
  <div class="field">
    <label for="rito">Rito *</label>
    <input id="rito" type="text" placeholder="Ex.: Brasileiro / Escocês / York">
    <div id="rito_err" class="err"></div>
  </div>
  <div class="field">
    <label for="potencia">Potência *</label>
    <input id="potencia" type="text" placeholder="Ex.: GLESP">
    <div id="potencia_err" class="err"></div>
  </div>
  <div class="field">
    <label for="endereco">Endereço da loja ou link do Google Maps *</label>
    <input id="endereco" type="text" placeholder="Ex.: https://maps.app.goo.gl/... ou Rua X, 123 - Centro">
    <div id="endereco_err" class="err"></div>
    <div class="info">Preferencialmente, cole o link do Google Maps para facilitar a localização exata.</div>
  </div>
</div>
"""
    script = """
function validate(){
  let ok=true;
  ok=req('nome_loja','Nome da loja')&&ok;
  ok=req('oriente','Oriente')&&ok;
  ok=req('rito','Rito')&&ok;
  ok=req('potencia','Potência')&&ok;
  ok=req('endereco','Endereço')&&ok;
  return ok;
}
tg.MainButton.setText('Salvar Loja');
tg.MainButton.show();
tg.MainButton.onClick(async()=>{
  if(!validate())return;
  tg.MainButton.showProgress(false);
  tg.MainButton.disable();
  try{
    const r=await fetch('/api/cadastro_loja',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        init_data:tg.initData,
        nome:val('nome_loja'),
        numero:val('numero')||'0',
        oriente:val('oriente'),
        rito:val('rito'),
        potencia:val('potencia'),
        endereco:val('endereco')
      })
    });
    const j=await r.json();
    if(j.ok){tg.close();}
    else{showToast(j.error||'Erro. Tente novamente.');tg.MainButton.hideProgress();tg.MainButton.enable();}
  }catch{showToast('Falha de conexão. Tente novamente.');tg.MainButton.hideProgress();tg.MainButton.enable();}
});
"""
    return _html_wrap("Cadastro de Loja", body, script)


# ─────────────────────────────────────────────────────────────────────────────
# HTML — CADASTRO DE EVENTO
# ─────────────────────────────────────────────────────────────────────────────

def html_cadastro_evento() -> str:
    body = """
<div id="lojas_card" class="card" style="display:none">
  <div class="card-title">Atalho - Lojas cadastradas</div>
  <div class="field">
    <label for="loja_sel">Selecione para auto-preencher</label>
    <select id="loja_sel">
      <option value="">Preencher manualmente...</option>
    </select>
  </div>
</div>

<div class="card">
  <div class="card-title">A sessão</div>
  <div class="field">
    <label for="data_ev">Data * <span class="info">(DD/MM/AAAA)</span></label>
    <input id="data_ev" type="text" placeholder="25/03/2026" maxlength="10" inputmode="numeric">
    <div id="data_ev_err" class="err"></div>
  </div>
  <div class="field">
    <label for="horario">Horário *</label>
    <input id="horario" type="time" value="19:30">
    <div id="horario_err" class="err"></div>
  </div>
  <div class="field">
    <label for="grau">Grau mínimo *</label>
    <select id="grau">
      <option value="">Selecione...</option>
      <option>Aprendiz</option>
      <option>Companheiro</option>
      <option>Mestre</option>
      <option>Mestre Instalado</option>
    </select>
    <div id="grau_err" class="err"></div>
  </div>
  <div class="field">
    <label for="tipo_sessao">Tipo de sessão *</label>
    <input id="tipo_sessao" type="text" placeholder="Ex.: Ordinária, Magna, Iniciação">
    <div id="tipo_sessao_err" class="err"></div>
  </div>
  <div class="field">
    <label for="traje">Traje *</label>
    <input id="traje" type="text" placeholder="Ex.: Traje escuro / Terno e gravata">
    <div id="traje_err" class="err"></div>
  </div>
  <div class="field">
    <label for="agape">Ágape *</label>
    <select id="agape">
      <option value="">Selecione...</option>
      <option value="Nao">Não haverá ágape</option>
      <option value="Sim (Gratuito)">Sim - Gratuito</option>
      <option value="Sim (Pago)">Sim - Pago (dividido)</option>
    </select>
    <div id="agape_err" class="err"></div>
  </div>
  <div class="field">
    <label for="observacoes">Ordem do dia / observações <span class="info">(opcional)</span></label>
    <textarea id="observacoes" placeholder="Informações adicionais da sessão..."></textarea>
  </div>
</div>

<div class="card">
  <div class="card-title">Dados da Loja</div>
  <div class="field">
    <label for="nome_loja">Nome da loja *</label>
    <input id="nome_loja" type="text" placeholder="Ex.: Luz da Fraternidade">
    <div id="nome_loja_err" class="err"></div>
  </div>
  <div class="field">
    <label for="numero_loja">Número <span class="info">(0 se não houver)</span></label>
    <input id="numero_loja" type="text" value="0" inputmode="numeric" maxlength="8">
  </div>
  <div class="field">
    <label for="oriente">Oriente *</label>
    <input id="oriente" type="text" placeholder="Ex.: São Paulo / SP">
    <div id="oriente_err" class="err"></div>
  </div>
  <div class="field">
    <label for="rito">Rito *</label>
    <input id="rito" type="text" placeholder="Ex.: Brasileiro / Escocês">
    <div id="rito_err" class="err"></div>
  </div>
  <div class="field">
    <label for="potencia">Potência *</label>
    <input id="potencia" type="text" placeholder="Ex.: GLESP">
    <div id="potencia_err" class="err"></div>
  </div>
  <div class="field">
    <label for="endereco">Endereço da sessão ou link do Google Maps *</label>
    <input id="endereco" type="text" placeholder="Ex.: https://maps.app.goo.gl/... ou Rua X, 123 - Centro">
    <div id="endereco_err" class="err"></div>
    <div class="info">Preferencialmente, cole o link do Google Maps para que o bot gere o atalho de mapa.</div>
  </div>
</div>

<div id="salvar_loja_card" class="card" style="display:none">
  <div class="card-title">Salvar Loja</div>
  <div class="field">
    <label>Deseja salvar esta loja para reutilizar nos próximos eventos?</label>
    <div class="info">Os dados informados neste evento serão aproveitados para criar o atalho da loja.</div>
  </div>
  <div class="field">
    <button id="btn_salvar_loja" type="button" style="width:100%;background:var(--btn);color:var(--btn-text);border:none;border-radius:10px;padding:12px;font-size:15px;font-weight:600">Salvar loja</button>
  </div>
  <div class="field">
    <button id="btn_pular_loja" type="button" style="width:100%;background:var(--sec);color:var(--text);border:1px solid var(--border);border-radius:10px;padding:12px;font-size:15px">Agora não</button>
  </div>
</div>

<div id="acoes_publicacao" class="actions">
  <div class="actions-stack">
    <button id="btn_publicar_evento" type="button" class="btn-primary">Publicar Evento</button>
    <button id="btn_cancelar_evento" type="button" class="btn-secondary">Cancelar</button>
  </div>
</div>
"""
    script = r"""
maskDate(document.getElementById('data_ev'));
let lojasCarregadas=[];
let lojaSelecionadaViaAtalho=false;
let enviandoEvento=false;

function norm(v){
  return (v||'').toString().trim().toLowerCase();
}

function dadosLojaAtual(){
  return {
    nome: val('nome_loja'),
    numero: val('numero_loja')||'0',
    oriente: val('oriente'),
    rito: val('rito'),
    potencia: val('potencia'),
    endereco: val('endereco')
  };
}

function lojaJaExiste(dados){
  return lojasCarregadas.some(l =>
    norm(l.nome)===norm(dados.nome) &&
    norm(l.numero||'0')===norm(dados.numero||'0') &&
    norm(l.rito)===norm(dados.rito)
  );
}

function mostrarPromptSalvarLoja(){
  document.querySelectorAll('.card').forEach(card=>{
    if(card.id!=='salvar_loja_card') card.style.display='none';
  });
  document.getElementById('salvar_loja_card').style.display='block';
  const acoes=document.getElementById('acoes_publicacao');
  if(acoes) acoes.style.display='none';
  tgMB('hide');
}

(async()=>{
  try{
    const r=await fetch('/api/lojas',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({init_data:(tg && tg.initData) || ''})
    });
    const j=await r.json();
    if(j.ok&&j.lojas&&j.lojas.length>0){
      lojasCarregadas=j.lojas;
      const sel=document.getElementById('loja_sel');
      j.lojas.forEach((l,i)=>{
        const o=document.createElement('option');
        o.value=i;
        o.textContent=l.nome+(l.numero&&l.numero!=='0'?' '+l.numero:'');
        o.dataset.loja=JSON.stringify(l);
        sel.appendChild(o);
      });
      document.getElementById('lojas_card').style.display='block';
    }
  }catch(e){}
})();

document.getElementById('loja_sel').addEventListener('change',function(){
  if(!this.value){
    lojaSelecionadaViaAtalho=false;
    return;
  }
  lojaSelecionadaViaAtalho=true;
  const o=this.options[this.selectedIndex];
  const l=JSON.parse(o.dataset.loja||'{}');
  if(l.nome)document.getElementById('nome_loja').value=l.nome;
  if(l.numero)document.getElementById('numero_loja').value=l.numero;
  if(l.oriente)document.getElementById('oriente').value=l.oriente;
  if(l.rito)document.getElementById('rito').value=l.rito;
  if(l.potencia)document.getElementById('potencia').value=l.potencia;
  if(l.endereco)document.getElementById('endereco').value=l.endereco;
});

function validate(){
  let ok=true;
  const dv=val('data_ev');
  if(!dv.match(/^\\d{2}\\/\\d{2}\\/\\d{4}$/)){
    setErr('data_ev','Use o formato DD/MM/AAAA.');ok=false;
  }else clearErr('data_ev');
  ok=req('horario','Horário')&&ok;
  ok=req('grau','Grau mínimo')&&ok;
  ok=req('tipo_sessao','Tipo de sessão')&&ok;
  ok=req('traje','Traje')&&ok;
  ok=req('agape','Ágape')&&ok;
  ok=req('nome_loja','Nome da loja')&&ok;
  ok=req('oriente','Oriente')&&ok;
  ok=req('rito','Rito')&&ok;
  ok=req('potencia','Potência')&&ok;
  ok=req('endereco','Endereço')&&ok;
  return ok;
}

async function salvarLojaAtual(){
  const dados=dadosLojaAtual();
  const r=await fetch('/api/cadastro_loja',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      init_data:(tg && tg.initData) || '',
      nome:dados.nome,
      numero:dados.numero,
      oriente:dados.oriente,
      rito:dados.rito,
      potencia:dados.potencia,
      endereco:dados.endereco
    })
  });
  return await r.json();
}

async function publicarEvento(){
  if(enviandoEvento)return;
  if(!validate())return;
  enviandoEvento=true;
  setPrimaryLoading(true);
  tgMB('showProgress', false);
  tgMB('disable');
  try{
    const r=await fetch('/api/cadastro_evento',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        init_data:(tg && tg.initData) || '',
        data:val('data_ev'),
        horario:val('horario'),
        grau:val('grau'),
        tipo_sessao:val('tipo_sessao'),
        traje:val('traje'),
        agape:val('agape'),
        observacoes:(document.getElementById('observacoes').value||'').trim(),
        nome_loja:val('nome_loja'),
        numero_loja:val('numero_loja')||'0',
        oriente:val('oriente'),
        rito:val('rito'),
        potencia:val('potencia'),
        endereco:val('endereco')
      })
    });
    const j=await r.json();
    if(j.ok){
      const dadosLoja=dadosLojaAtual();
      const deveOferecerSalvar=!lojaSelecionadaViaAtalho && !lojaJaExiste(dadosLoja);
      if(deveOferecerSalvar){
        showToast('Evento publicado com sucesso.');
        mostrarPromptSalvarLoja();
      }else{
        closeMiniApp();
      }
    }
    else{
      showToast(j.error||'Erro. Tente novamente.');
      tgMB('hideProgress');
      tgMB('enable');
      setPrimaryLoading(false);
      enviandoEvento=false;
    }
  }catch{
    showToast('Falha de conexão. Tente novamente.');
    tgMB('hideProgress');
    tgMB('enable');
    setPrimaryLoading(false);
    enviandoEvento=false;
  }
}

window.publicarEvento = publicarEvento;
window.cancelarEvento = closeMiniApp;
tgMB('setText', 'Publicar Evento');
tgMB('show');
if(tg && tg.MainButton && typeof tg.MainButton.onClick === 'function'){
  try{tg.MainButton.onClick(publicarEvento);}catch(e){}
}
const btnPublicar = document.getElementById('btn_publicar_evento');
if(btnPublicar) btnPublicar.onclick = publicarEvento;
const btnCancelar = document.getElementById('btn_cancelar_evento');
if(btnCancelar) btnCancelar.onclick = closeMiniApp;

document.getElementById('btn_salvar_loja').addEventListener('click',async()=>{
  const btnSalvar=document.getElementById('btn_salvar_loja');
  const btnPular=document.getElementById('btn_pular_loja');
  btnSalvar.disabled=true;
  btnPular.disabled=true;
  try{
    const j=await salvarLojaAtual();
    if(j.ok){closeMiniApp();}
    else{
      showToast(j.error||'Não foi possível salvar a loja.');
      btnSalvar.disabled=false;
      btnPular.disabled=false;
    }
  }catch{
    showToast('Falha de conexão. Tente novamente.');
    btnSalvar.disabled=false;
    btnPular.disabled=false;
  }
});

document.getElementById('btn_pular_loja').addEventListener('click', closeMiniApp);
"""
    return _html_wrap("Cadastro de Evento", body, script)



# ─────────────────────────────────────────────────────────────────────────────
# HANDLERS GET (servem os HTMLs)
# ─────────────────────────────────────────────────────────────────────────────

async def get_cadastro_membro(request: Request) -> HTMLResponse:
    return HTMLResponse(html_cadastro_membro())


async def get_cadastro_evento(request: Request) -> HTMLResponse:
    return HTMLResponse(html_cadastro_evento())


async def get_cadastro_loja(request: Request) -> HTMLResponse:
    return HTMLResponse(html_cadastro_loja())


# ─────────────────────────────────────────────────────────────────────────────
# API — LISTAR LOJAS (para o form de evento)
# ─────────────────────────────────────────────────────────────────────────────

async def api_listar_lojas(request: Request) -> JSONResponse:
    bot_token: str = request.app.state.bot_token
    try:
        body: dict = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "lojas": []}, status_code=400)

    init_data = (body.get("init_data") or "").strip()
    user = verify_telegram_webapp_data(init_data, bot_token)
    if not user:
        return JSONResponse({"ok": False, "lojas": []}, status_code=403)

    telegram_id = user.get("id")
    if not telegram_id:
        return JSONResponse({"ok": False, "lojas": []}, status_code=403)

    lojas = listar_lojas(int(telegram_id)) or []
    result = []
    for lj in lojas[:10]:
        result.append({
            "nome":     lj.get("Nome da Loja", ""),
            "numero":   str(lj.get("Número") or "0"),
            "oriente":  lj.get("Oriente da Loja") or lj.get("Oriente", ""),
            "rito":     lj.get("Rito", ""),
            "potencia": lj.get("Potência", ""),
            "endereco": lj.get("Endereço", ""),
        })
    return JSONResponse({"ok": True, "lojas": result})


# ─────────────────────────────────────────────────────────────────────────────
# API — CADASTRO DE MEMBRO
# ─────────────────────────────────────────────────────────────────────────────

async def api_cadastro_membro(request: Request) -> JSONResponse:
    bot_token: str = request.app.state.bot_token
    try:
        body: dict = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "JSON inválido."}, status_code=400)

    init_data = (body.get("init_data") or "").strip()
    user = verify_telegram_webapp_data(init_data, bot_token)
    if not user:
        return JSONResponse({"ok": False, "error": "Não autorizado."}, status_code=403)

    telegram_id = user.get("id")
    if not telegram_id:
        return JSONResponse({"ok": False, "error": "Usuário não identificado."}, status_code=403)

    # Sanitizar e validar campos
    nome       = (body.get("nome")       or "").strip()[:200]
    data_nasc  = (body.get("data_nasc")  or "").strip()[:10]
    grau       = (body.get("grau")       or "").strip()[:50]
    vm         = (body.get("vm")         or "").strip()[:10]
    loja       = (body.get("loja")       or "").strip()[:200]
    numero_loja= (body.get("numero_loja")or "0").strip()[:10]
    oriente    = (body.get("oriente")    or "").strip()[:200]
    potencia   = (body.get("potencia")   or "").strip()[:200]

    if not all([nome, data_nasc, grau, vm, loja, oriente, potencia]):
        return JSONResponse({"ok": False, "error": "Preencha todos os campos obrigatórios."}, status_code=400)

    try:
        datetime.strptime(data_nasc, "%d/%m/%Y")
    except ValueError:
        return JSONResponse({"ok": False, "error": "Data de nascimento inválida (DD/MM/AAAA)."}, status_code=400)

    graus_validos = {"Aprendiz", "Companheiro", "Mestre", "Mestre Instalado"}
    if grau not in graus_validos:
        return JSONResponse({"ok": False, "error": "Grau inválido."}, status_code=400)

    ja_existe = buscar_membro(int(telegram_id))

    dados: Dict[str, Any] = {
        "Telegram ID":        str(telegram_id),
        "Nome":               nome,
        "Data de nascimento": data_nasc,
        "Grau":               grau,
        "Venerável Mestre":   vm,
        "Loja":               loja,
        "Número da loja":     numero_loja,
        "Oriente":            oriente,
        "Potência":           potencia,
        "Status":             "Ativo",
        "Nivel":              "1",
    }

    ok = cadastrar_membro(dados)
    if not ok:
        return JSONResponse({"ok": False, "error": "Falha ao salvar. Tente novamente."}, status_code=500)

    try:
        bot = request.app.state.telegram_app.bot
        nome_esc = _escape_md(nome)
        if ja_existe:
            msg = f"✅ *Cadastro atualizado\\!*\n\nSaudações, Ir\\.·\\. {nome_esc}\\. Seus dados foram atualizados\\."
        else:
            msg = (
                f"✅ *Cadastro realizado a contento\\!*\n\n"
                f"Bem\\-vindo ao Bode Andarilho, Ir\\.·\\. {nome_esc}\\!\n"
                f"Use /start para acessar o Painel do Obreiro\\."
            )
        await bot.send_message(chat_id=telegram_id, text=msg, parse_mode="MarkdownV2")
    except Exception as e:
        logger.warning("Falha ao enviar confirmação de cadastro para %s: %s", telegram_id, e)

    return JSONResponse({"ok": True})


# ─────────────────────────────────────────────────────────────────────────────
# API — CADASTRO DE LOJA
# ─────────────────────────────────────────────────────────────────────────────

async def api_cadastro_loja(request: Request) -> JSONResponse:
    bot_token: str = request.app.state.bot_token
    try:
        body: dict = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "JSON inválido."}, status_code=400)

    init_data = (body.get("init_data") or "").strip()
    user = verify_telegram_webapp_data(init_data, bot_token)
    if not user:
        return JSONResponse({"ok": False, "error": "Não autorizado."}, status_code=403)

    telegram_id = user.get("id")
    if not telegram_id:
        return JSONResponse({"ok": False, "error": "Usuário não identificado."}, status_code=403)

    nome     = (body.get("nome")     or "").strip()[:200]
    numero   = (body.get("numero")   or "0").strip()[:10]
    oriente  = (body.get("oriente")  or "").strip()[:200]
    rito     = (body.get("rito")     or "").strip()[:200]
    potencia = (body.get("potencia") or "").strip()[:200]
    endereco = (body.get("endereco") or "").strip()[:400]

    if not all([nome, oriente, rito, potencia, endereco]):
        return JSONResponse({"ok": False, "error": "Preencha todos os campos obrigatórios."}, status_code=400)

    dados_loja: Dict[str, Any] = {
        "nome":     nome,
        "numero":   numero,
        "oriente":  oriente,
        "rito":     rito,
        "potencia": potencia,
        "endereco": endereco,
    }

    ok = cadastrar_loja(int(telegram_id), dados_loja)
    if not ok:
        return JSONResponse({"ok": False, "error": "Falha ao salvar a loja. Tente novamente."}, status_code=500)

    try:
        bot = request.app.state.telegram_app.bot
        nome_esc = _escape_md(nome)
        await bot.send_message(
            chat_id=telegram_id,
            text=f"✅ *Loja cadastrada\\!*\n\n🏛 *{nome_esc}* registrada com sucesso\\.\nEla estará disponível como atalho no cadastro de eventos\\.",
            parse_mode="MarkdownV2",
        )
    except Exception as e:
        logger.warning("Falha ao confirmar cadastro de loja para %s: %s", telegram_id, e)

    return JSONResponse({"ok": True})


# ─────────────────────────────────────────────────────────────────────────────
# API — CADASTRO DE EVENTO
# ─────────────────────────────────────────────────────────────────────────────

async def api_cadastro_evento(request: Request) -> JSONResponse:
    bot_token: str = request.app.state.bot_token
    try:
        body: dict = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "JSON inválido."}, status_code=400)

    init_data = (body.get("init_data") or "").strip()
    user = verify_telegram_webapp_data(init_data, bot_token)
    if not user:
        return JSONResponse({"ok": False, "error": "Não autorizado."}, status_code=403)

    telegram_id = user.get("id")
    if not telegram_id:
        return JSONResponse({"ok": False, "error": "Usuário não identificado."}, status_code=403)

    # Sanitizar campos
    data_str    = (body.get("data")       or "").strip()[:10]
    horario     = (body.get("horario")    or "").strip()[:5]
    grau        = (body.get("grau")       or "").strip()[:50]
    tipo_sessao = (body.get("tipo_sessao")or "").strip()[:200]
    traje       = (body.get("traje")      or "").strip()[:200]
    agape       = (body.get("agape")      or "").strip()[:50]
    observacoes = (body.get("observacoes")or "").strip()[:500]
    nome_loja   = (body.get("nome_loja")  or "").strip()[:200]
    numero_loja = (body.get("numero_loja")or "0").strip()[:10]
    oriente     = (body.get("oriente")    or "").strip()[:200]
    rito        = (body.get("rito")       or "").strip()[:200]
    potencia    = (body.get("potencia")   or "").strip()[:200]
    endereco    = (body.get("endereco")   or "").strip()[:400]

    if not all([data_str, horario, grau, tipo_sessao, traje, agape, nome_loja, oriente, rito, potencia, endereco]):
        return JSONResponse({"ok": False, "error": "Preencha todos os campos obrigatórios."}, status_code=400)

    dt = _parse_data_ddmmyyyy(data_str)
    if not dt:
        return JSONResponse({"ok": False, "error": "Data inválida. Use DD/MM/AAAA."}, status_code=400)

    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if dt < hoje:
        return JSONResponse({"ok": False, "error": "A data não pode ser no passado."}, status_code=400)

    dia_semana = dt.strftime("%A")

    evento: Dict[str, Any] = {
        "Data do evento":              data_str,
        "Dia da semana":               dia_semana,
        "Hora":                        horario,
        "Nome da loja":                nome_loja,
        "Número da loja":              numero_loja,
        "Oriente":                     oriente,
        "Grau":                        grau,
        "Tipo de sessão":              tipo_sessao,
        "Rito":                        rito,
        "Potência":                    potencia,
        "Traje obrigatório":           traje,
        "Ágape":                       agape,
        "Observações":                 observacoes,
        "Telegram ID do grupo":        _GRUPO_PRINCIPAL_ID,
        "Telegram ID do secretário":   str(telegram_id),
        "Status":                      "Ativo",
        "Endereço da sessão":          endereco,
    }

    id_evento = cadastrar_evento(evento)
    if not id_evento:
        return JSONResponse({"ok": False, "error": "Falha ao salvar o evento. Tente novamente."}, status_code=500)

    # Publicar no grupo e notificar secretário
    try:
        bot = request.app.state.telegram_app.bot

        dia_semana_pt = {
            "Monday": "segunda",
          "Tuesday": "terça",
            "Wednesday": "quarta",
            "Thursday": "quinta",
            "Friday": "sexta",
          "Saturday": "sábado",
            "Sunday": "domingo",
        }.get(dia_semana, "")

        data_hora = f"{_escape_md(data_str)} ({_escape_md(dia_semana_pt)}) • {_escape_md(horario)}" if dia_semana_pt else f"{_escape_md(data_str)} • {_escape_md(horario)}"
        nome_esc   = _escape_md(nome_loja)
        num_fmt    = f" {_escape_md(numero_loja)}" if numero_loja and numero_loja != "0" else ""
        endereco_raw = (endereco or "").strip()
        endereco_url = endereco_raw if endereco_raw.startswith(("http://", "https://")) else ""
        texto_grupo = (
            "NOVA SESSÃO\n\n"
            f"{data_hora}\n"
            f"Grau: {_escape_md(grau)}\n\n"
            "LOJA\n"
            f"{nome_esc}{num_fmt}\n"
            f"{_escape_md(oriente)} - {_escape_md(potencia)}\n\n"
            "SESSÃO\n"
            f"Tipo: {_escape_md(tipo_sessao)}\n"
            f"Rito: {_escape_md(rito)}\n"
            f"Traje: {_escape_md(traje)}\n"
            f"Ágape: {_escape_md(agape)}\n\n"
            "ORDEM DO DIA / OBSERVAÇÕES\n"
            f"{_escape_md(observacoes) or '-'}\n\n"
        )

        if endereco_url:
            texto_grupo += f"Local: [Abrir no mapa]({endereco_url})"
        else:
            texto_grupo += f"Local: {_escape_md(endereco)}"

        try:
            grupo_id_int = int(_GRUPO_PRINCIPAL_ID)
            await bot.send_message(
                chat_id=grupo_id_int,
                text=texto_grupo,
                parse_mode="Markdown",
                reply_markup=_teclado_pos_publicacao(id_evento, agape),
            )
        except Exception as eg:
            logger.warning("Falha ao publicar evento no grupo: %s", eg)

        await bot.send_message(
            chat_id=telegram_id,
            text="✅ *Evento cadastrado e publicado no grupo\\!*",
            parse_mode="MarkdownV2",
        )
    except Exception as e:
        logger.warning("Falha ao confirmar evento para %s: %s", telegram_id, e)

    return JSONResponse({"ok": True})
