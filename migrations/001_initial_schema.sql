-- Initial schema for the MTG collection sync project.
--
-- HISTORICAL: originally applied to Supabase project heiyckeurcfjpnhmsjfo
-- (retired). As of 2026-07-08 this schema lives in the shared tracker
-- project (oxpgmwiwwmehaireeqnb) instead -- see mtg-tracker's
-- supabase/migrations/20260708213202_collection_sync_schema.sql for the
-- version of record. Kept here for history only; do not reapply.

create table cards (
  scryfall_id uuid primary key,
  oracle_id uuid,
  name text not null,
  mana_cost text,
  cmc numeric,
  type_line text,
  oracle_text text,
  power text,
  toughness text,
  color_identity text[],
  colors text[],
  keywords text[],
  set_code text,
  collector_number text,
  rarity text,
  legalities jsonb,
  updated_at timestamptz default now()
);
create index idx_cards_name on cards (name);
create index idx_cards_set on cards (set_code);
create index idx_cards_oracle_id on cards (oracle_id);

create table collection (
  id bigint generated always as identity primary key,
  scryfall_id uuid references cards (scryfall_id),
  name text not null,
  set_code text,
  collector_number text,
  foil boolean default false,
  quantity int default 1,
  condition text,
  language text,
  binder_name text,
  binder_type text,
  purchase_price numeric,
  last_synced timestamptz default now(),
  unique (scryfall_id, foil, binder_name)
);
create index idx_collection_scryfall_id on collection (scryfall_id);
create index idx_collection_binder on collection (binder_name, binder_type);

create view collection_enriched as
select col.id, col.name, col.quantity, col.foil, col.condition,
       col.binder_name, col.binder_type, col.purchase_price,
       c.mana_cost, c.cmc, c.type_line, c.oracle_text, c.power, c.toughness,
       c.color_identity, c.keywords, c.rarity, c.legalities
from collection col
left join cards c on col.scryfall_id = c.scryfall_id;
