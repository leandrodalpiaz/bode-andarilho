# ============================================
# BODE ANDARILHO — SERVIÇO DE LOCALIZAÇÃO (IBGE)
# ============================================
#
# Camada de integração com a API de Localidades do IBGE
# para carregar dinamicamente UFs e Municípios com cache de 24h.
# ============================================

import logging
import time
from typing import List, Dict, Any
import requests

logger = logging.getLogger(__name__)

# TTL de 24 horas para cache geográfico (dados raramente mudam)
_CACHE_TTL = 24 * 60 * 60 

_cache_estados: Dict[str, Any] = {}
_cache_cidades: Dict[str, Any] = {}


def buscar_estados_uf() -> List[Dict[str, str]]:
    """
    Busca a lista de estados (UF) ordenada por nome da API do IBGE.
    Retorna cache em memória de 24h se disponível.
    Retorno formato: [{"sigla": "AC", "nome": "Acre"}, ...]
    """
    global _cache_estados
    
    agora = time.time()
    if "estados" in _cache_estados:
        dados, ts = _cache_estados["estados"]
        if agora - ts < _CACHE_TTL:
            return dados

    try:
        url = "https://servicodados.ibge.gov.br/api/v1/localidades/estados?orderBy=nome"
        logger.info("Consultando IBGE API para carregar UFs...")
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        
        payload = resp.json() or []
        resultado = []
        for item in payload:
            sigla = str(item.get("sigla", "")).upper()
            nome = str(item.get("nome", ""))
            if sigla and nome:
                resultado.append({"sigla": sigla, "nome": nome})
        
        if resultado:
            _cache_estados["estados"] = (resultado, agora)
            return resultado
            
    except Exception as e:
        logger.error("Falha ao carregar estados da API do IBGE: %s", e)
        # Se tiver cache antigo expirado, retorna como fallback em caso de erro de rede
        if "estados" in _cache_estados:
            return _cache_estados["estados"][0]

    # Fallback estático absoluto (segurança mínima se IBGE estiver 100% indisponível)
    return [
        {"sigla": "AC", "nome": "Acre"}, {"sigla": "AL", "nome": "Alagoas"}, {"sigla": "AP", "nome": "Amapá"},
        {"sigla": "AM", "nome": "Amazonas"}, {"sigla": "BA", "nome": "Bahia"}, {"sigla": "CE", "nome": "Ceará"},
        {"sigla": "DF", "nome": "Distrito Federal"}, {"sigla": "ES", "nome": "Espírito Santo"}, {"sigla": "GO", "nome": "Goiás"},
        {"sigla": "MA", "nome": "Maranhão"}, {"sigla": "MT", "nome": "Mato Grosso"}, {"sigla": "MS", "nome": "Mato Grosso do Sul"},
        {"sigla": "MG", "nome": "Minas Gerais"}, {"sigla": "PA", "nome": "Pará"}, {"sigla": "PB", "nome": "Paraíba"},
        {"sigla": "PR", "nome": "Paraná"}, {"sigla": "PE", "nome": "Pernambuco"}, {"sigla": "PI", "nome": "Piauí"},
        {"sigla": "RJ", "nome": "Rio de Janeiro"}, {"sigla": "RN", "nome": "Rio Grande do Norte"}, {"sigla": "RS", "nome": "Rio Grande do Sul"},
        {"sigla": "RO", "nome": "Rondônia"}, {"sigla": "RR", "nome": "Roraima"}, {"sigla": "SC", "nome": "Santa Catarina"},
        {"sigla": "SP", "nome": "São Paulo"}, {"sigla": "SE", "nome": "Sergipe"}, {"sigla": "TO", "nome": "Tocantins"}
    ]


def buscar_cidades_por_uf(uf: str) -> List[str]:
    """
    Busca todos os municípios de um determinado estado (UF) da API do IBGE.
    Utiliza cache em memória de 24h por UF.
    Retorna lista ordenada de nomes de cidades.
    """
    global _cache_cidades
    
    if not uf:
        return []
        
    uf_key = str(uf).upper().strip()
    agora = time.time()
    
    if uf_key in _cache_cidades:
        dados, ts = _cache_cidades[uf_key]
        if agora - ts < _CACHE_TTL:
            return dados

    try:
        url = f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf_key}/municipios?orderBy=nome"
        logger.info(f"Consultando IBGE API para carregar municípios de {uf_key}...")
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        
        payload = resp.json() or []
        resultado = []
        for item in payload:
            nome = str(item.get("nome", "")).strip()
            if nome:
                resultado.append(nome)
                
        if resultado:
            _cache_cidades[uf_key] = (resultado, agora)
            return resultado
            
    except Exception as e:
        logger.error(f"Falha ao carregar municípios de {uf_key} do IBGE: {e}")
        if uf_key in _cache_cidades:
            return _cache_cidades[uf_key][0]

    return []
