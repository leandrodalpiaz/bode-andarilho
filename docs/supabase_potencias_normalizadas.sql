-- Normalizacao de potencias principais e complemento jurisdicional.
-- Execute no Supabase SQL Editor antes de publicar a versao do bot.

alter table public.membros
    add column if not exists potencia_complemento text;

alter table public.lojas
    add column if not exists potencia_complemento text;

alter table public.eventos
    add column if not exists potencia_complemento text;

alter table public.confirmacoes
    add column if not exists potencia_complemento text;

-- Preserva o valor antigo em complemento antes de normalizar a potencia principal.
update public.membros
set potencia_complemento = coalesce(nullif(potencia_complemento, ''), potencia)
where potencia is not null
  and potencia <> ''
  and upper(potencia) not in ('GOB', 'CMSB', 'COMAB');

update public.lojas
set potencia_complemento = coalesce(nullif(potencia_complemento, ''), potencia)
where potencia is not null
  and potencia <> ''
  and upper(potencia) not in ('GOB', 'CMSB', 'COMAB');

update public.eventos
set potencia_complemento = coalesce(nullif(potencia_complemento, ''), potencia)
where potencia is not null
  and potencia <> ''
  and upper(potencia) not in ('GOB', 'CMSB', 'COMAB');

update public.confirmacoes
set potencia_complemento = coalesce(nullif(potencia_complemento, ''), potencia)
where potencia is not null
  and potencia <> ''
  and upper(potencia) not in ('GOB', 'CMSB', 'COMAB');

-- GOB e suas variantes.
update public.membros set potencia = 'GOB' where upper(potencia) like 'GOB%';
update public.lojas set potencia = 'GOB' where upper(potencia) like 'GOB%';
update public.eventos set potencia = 'GOB' where upper(potencia) like 'GOB%';
update public.confirmacoes set potencia = 'GOB' where upper(potencia) like 'GOB%';

-- GOB tambem exige complemento jurisdicional; registros GOB puros ficam para revisao.
update public.membros set potencia_complemento = coalesce(nullif(potencia_complemento, ''), 'GOB')
where potencia = 'GOB' and coalesce(potencia_complemento, '') = '';

update public.lojas set potencia_complemento = coalesce(nullif(potencia_complemento, ''), 'GOB')
where potencia = 'GOB' and coalesce(potencia_complemento, '') = '';

update public.eventos set potencia_complemento = coalesce(nullif(potencia_complemento, ''), 'GOB')
where potencia = 'GOB' and coalesce(potencia_complemento, '') = '';

update public.confirmacoes set potencia_complemento = coalesce(nullif(potencia_complemento, ''), 'GOB')
where potencia = 'GOB' and coalesce(potencia_complemento, '') = '';

-- Grandes Lojas estaduais vinculadas a CMSB.
update public.membros set potencia = 'CMSB'
where upper(potencia_complemento) in ('GRANDE LOJA - RS', 'GRANDE LOJA RS', 'GLMERGS', 'GLESP')
   or upper(potencia_complemento) like 'GL%';

update public.lojas set potencia = 'CMSB'
where upper(potencia_complemento) in ('GRANDE LOJA - RS', 'GRANDE LOJA RS', 'GLMERGS', 'GLESP')
   or upper(potencia_complemento) like 'GL%';

update public.eventos set potencia = 'CMSB'
where upper(potencia_complemento) in ('GRANDE LOJA - RS', 'GRANDE LOJA RS', 'GLMERGS', 'GLESP')
   or upper(potencia_complemento) like 'GL%';

update public.confirmacoes set potencia = 'CMSB'
where upper(potencia_complemento) in ('GRANDE LOJA - RS', 'GRANDE LOJA RS', 'GLMERGS', 'GLESP')
   or upper(potencia_complemento) like 'GL%';

-- Grandes Orientes estaduais vinculados a COMAB.
update public.membros set potencia = 'COMAB'
where upper(potencia_complemento) in ('GORGS', 'GOSC', 'GOP', 'GOMG', 'GOPR')
   or upper(potencia_complemento) like 'GO%';

update public.lojas set potencia = 'COMAB'
where upper(potencia_complemento) in ('GORGS', 'GOSC', 'GOP', 'GOMG', 'GOPR')
   or upper(potencia_complemento) like 'GO%';

update public.eventos set potencia = 'COMAB'
where upper(potencia_complemento) in ('GORGS', 'GOSC', 'GOP', 'GOMG', 'GOPR')
   or upper(potencia_complemento) like 'GO%';

update public.confirmacoes set potencia = 'COMAB'
where upper(potencia_complemento) in ('GORGS', 'GOSC', 'GOP', 'GOMG', 'GOPR')
   or upper(potencia_complemento) like 'GO%';
