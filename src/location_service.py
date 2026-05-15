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
    

# ============================================
# EXTENSÃO GEOGRÁFICA (RAIO DE DISTÂNCIA E COORDENADAS)
# ============================================

import math
import json
import os

_PATH_COORDS_CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "municipios_coords.json")
_cache_coords: Dict[str, Any] = {}


def calcular_distancia_haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calcula a distância circular (ortodrômica) entre duas coordenadas geográficas
    utilizando a Fórmula de Haversine. Retorna a distância em quilômetros (km).
    """
    R = 6371.0  # Raio médio da Terra em km
    
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    
    a = (
        math.sin(d_lat / 2.0) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(d_lon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    
    return R * c


def _carregar_cache_coords() -> None:
    global _cache_coords
    if _cache_coords:
        return
        
    try:
        os.makedirs(os.path.dirname(_PATH_COORDS_CACHE), exist_ok=True)
        if os.path.exists(_PATH_COORDS_CACHE):
            with open(_PATH_COORDS_CACHE, "r", encoding="utf-8") as f:
                _cache_coords = json.load(f) or {}
            logger.info("Cache de coordenadas geográficas carregado do arquivo.")
        else:
            _cache_coords = {}
    except Exception as e:
        logger.debug("Erro ao carregar cache de coordenadas local: %s", e)
        _cache_coords = {}


def _salvar_cache_coords() -> None:
    try:
        os.makedirs(os.path.dirname(_PATH_COORDS_CACHE), exist_ok=True)
        with open(_PATH_COORDS_CACHE, "w", encoding="utf-8") as f:
            json.dump(_cache_coords, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("Falha ao salvar cache de coordenadas local: %s", e)


def obter_coordenadas_cidade(cidade: str, uf: str) -> Optional[tuple[float, float]]:
    """
    Busca a latitude e longitude de uma cidade brasileira.
    1. Procura no cache JSON local persistido.
    2. Consulta API pública (Nominatim OpenStreetMap) e persiste no arquivo local.
    """
    if not cidade or not uf:
        return None
        
    _carregar_cache_coords()
    
    cid_clean = str(cidade).strip().lower()
    uf_clean = str(uf).strip().upper()
    chave = f"{cid_clean}-{uf_clean}"
    
    # Retorna do cache
    if chave in _cache_coords:
        val = _cache_coords[chave]
        return (float(val[0]), float(val[1])) if val else None

    # Consulta remota (Nominatim)
    try:
        # A API Nominatim exige um User-Agent válido para evitar bloqueios
        headers = {"User-Agent": "BodeAndarilhoBot/2.0 (contato@bodeandarilho.net)"}
        
        # Enriquecer query string com cidade, estado e pais para máxima precisão
        query = f"{cidade}, {uf}, Brazil"
        url = f"https://nominatim.openstreetmap.org/search?format=json&limit=1&q={requests.utils.quote(query)}"
        
        logger.info("Geocodificando '%s-%s' via Nominatim API...", cidade, uf)
        resp = requests.get(url, headers=headers, timeout=8)
        resp.raise_for_status()
        
        payload = resp.json()
        if payload and len(payload) > 0:
            lat = float(payload[0].get("lat"))
            lon = float(payload[0].get("lon"))
            coords = [lat, lon]
            
            _cache_coords[chave] = coords
            _salvar_cache_coords()
            logger.info("Coordenadas gravadas em cache: %s = %s", chave, coords)
            return (lat, lon)
            
        # Registra no cache como None para evitar tentativas repetitivas em nomes errados
        _cache_coords[chave] = None
        _salvar_cache_coords()
        return None
        
    except Exception as e:
        logger.warning("Falha ao consultar API Nominatim para %s-%s: %s", cidade, uf, e)
        return None


def filtrar_locais_por_raio(
    cidade_origem: str,
    uf_origem: str,
    destinos: List[Dict[str, str]],
    raio_km: float = 100.0
) -> List[Dict[str, Any]]:
    """
    Calcula o raio a partir de um local e filtra uma lista de destinos com suas distâncias.
    Parâmetros:
      - cidade_origem, uf_origem: Referência central.
      - destinos: Lista de dicts contendo {"cidade": "...", "uf": "..."}
      - raio_km: Limite de raio em quilômetros.
    
    Retorna uma lista de dicionários com chaves originais acrescidas da chave `distancia_km`
    ordenada do mais próximo para o mais distante.
    """
    origem_coords = obter_coordenadas_cidade(cidade_origem, uf_origem)
    if not origem_coords:
        logger.warning("Não foi possível obter coordenadas de origem: %s-%s", cidade_origem, uf_origem)
        return []
        
    lat1, lon1 = origem_coords
    resultado = []
    
    # Agrupar cidades únicas de destino para otimizar chamadas à API/Cache e evitar throttling
    cidades_unicas = {}
    for d in destinos:
        c = str(d.get("cidade", "")).strip()
        u = str(d.get("uf", "")).strip().upper()
        if c and u:
            cidades_unicas[(c, u)] = None

    # Mapeia as distâncias
    import time
    for (c, u) in cidades_unicas.keys():
        coords = obter_coordenadas_cidade(c, u)
        if coords:
            dist = calcular_distancia_haversine(lat1, lon1, coords[0], coords[1])
            cidades_unicas[(c, u)] = dist
            # Pequeno delay se for necessário consultar a API real sequencialmente 
            # para não disparar o limitador de requisições do Nominatim
            if (f"{c.lower()}-{u.upper()}" not in _cache_coords):
                time.sleep(1.1) 

    # Filtra e monta a resposta com a distância computada
    for d in destinos:
        c = str(d.get("cidade", "")).strip()
        u = str(d.get("uf", "")).strip().upper()
        dist = cidades_unicas.get((c, u))
        
        if dist is not None and dist <= raio_km:
            item = dict(d)
            item["distancia_km"] = dist
            resultado.append(item)
            
    # Ordena da menor distância para a maior
    resultado.sort(key=lambda x: x["distancia_km"])
    return resultado

